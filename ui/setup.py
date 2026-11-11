"""Screen A, the first screen: the model access (your key, or ours from .env in local mode), web search,
the document and the review setting, then Run. Zero setup: paste a key, pick a sample, run."""

import json
import os
import tempfile
from dataclasses import replace
from pathlib import Path

import streamlit as st

from premortem import config
from premortem.config import RunSettings, current_mode
from premortem.ingestion.parser import ALLOWED_EXTENSIONS, DocumentParseError
from premortem.llm import check_model
from premortem.providers import PRESETS, detect_provider
from premortem.runner import Run
from ui.live import LiveRun
from ui.theme import esc, html_block
from ui.view import ROOT

CUSTOM = "custom"
ROLE_LABELS = {"brief": "Brief extractor", "analyst": "Analyst", "strategist": "Strategist", "creative": "Creative",
               "validator": "Validator", "blueprint": "Blueprint summary"}


def samples() -> list[tuple[Path, str]]:
    out = [(ROOT / "data" / "demo" / "demo_company.pdf", "Verdo Foods · protein crisps launching in France (the demo)")]
    for case in json.loads((ROOT / "eval" / "cases" / "cases.json").read_text()):
        path = ROOT / case["document"]
        if path.exists() and case["id"] != "demo_fr":
            out.append((path, f"{case['category'].split(': ', 1)[-1].capitalize()} · {case['country']}"))
    return out


def searches_used() -> int:
    """Web searches made in this browser session, on any run (the Tavily cap of the public app)."""
    runs = st.session_state.get("session_runs", [])
    return sum(len(r.run.searches) for r in runs)


def model_section() -> tuple[RunSettings | None, str | None]:
    """The settings of the next run, or the reason the run cannot start."""
    st.subheader("Model access")
    if current_mode() == "local":
        try:
            default = RunSettings.from_env(mode="local").provider
        except ValueError as e:
            return None, str(e)
        # Every preset with its own key in .env (GEMINI_API_KEY, ANTHROPIC_API_KEY…), plus the default one
        ready = [p for p in PRESETS if os.getenv(f"{p.upper()}_API_KEY", "").strip()]
        options = [default, *[p for p in ready if p != default]]
        provider = default
        if len(options) > 1:
            provider = st.selectbox("Provider", options, key="local_provider",
                                    format_func=lambda p: f"{PRESETS[p].label if p in PRESETS else p} · key from .env",
                                    help="The providers with a key in .env. Add GEMINI_API_KEY, ANTHROPIC_API_KEY… to see more.")
        try:
            settings = RunSettings.from_env(mode="local", provider=provider)
        except ValueError as e:
            return None, str(e)
        label = PRESETS[settings.provider].label if settings.provider in PRESETS else settings.provider
        if not settings.llm_api_key:
            return settings, f"Missing in .env: {settings.provider.upper()}_API_KEY or LLM_API_KEY."
        html_block(f'<p class="pm-provider"><span class="dot"></span>Using the key from .env · {esc(label)}</p>')
        st.session_state.provider_label = label.split(" (")[0]
        return settings, None

    tavily = RunSettings.from_env(mode="public").tavily_api_key  # ours, from the Secrets
    key = st.text_input("Your LLM API key", type="password", key="llm_key", placeholder="sk-ant-…, AIza…, gsk_…, sk-or-…",
                        help="Kept in this browser session only: never written to disk, to the logs or to the run files.")
    guess = detect_provider(key)
    options = [*PRESETS, CUSTOM]
    provider = st.selectbox("Provider", options, index=options.index(guess) if guess else 0, key=f"provider_{guess}",
                            format_func=lambda p: PRESETS[p].label if p in PRESETS else "Custom (OpenAI-compatible)",
                            help="Detected from the key prefix. Change it if the guess is wrong.")
    if provider == CUSTOM:
        a, b = st.columns(2)
        base_url = a.text_input("Base URL", placeholder="https://…/v1", key="custom_url")
        model = b.text_input("Model", key="custom_model")
        big = st.text_input("Bigger model for the blueprint summary (optional)", key="custom_big")
        st.caption("Any service with an OpenAI-compatible API: Together, DeepSeek, a university server, a local Ollama.")
    else:
        detected = "Detected from the key: " if guess == provider and key.strip() else ""
        st.caption(f"{detected}{PRESETS[provider].label}. {PRESETS[provider].note}")
    if not key.strip():
        st.session_state.provider_label = None
        return None, "Paste an LLM API key to run the pipeline, or open a saved run with no key."
    try:
        settings = (RunSettings.custom(base_url, key, model, big or None, tavily_api_key=tavily) if provider == CUSTOM
                    else RunSettings.preset(provider, key, tavily_api_key=tavily))
    except ValueError as e:
        return None, str(e)
    st.session_state.provider_label = PRESETS[provider].label.split(" (")[0] if provider in PRESETS else "Custom"

    signature = (provider, key[-6:], settings.models["analyst"])
    if st.button("Check key", icon=":material/key:", help="Three tiny requests: a plain call, a tool call, a structured output."):
        with st.spinner("Checking the model…"):
            st.session_state.key_check = (signature, check_model(settings))
    checked = st.session_state.get("key_check")
    if checked and checked[0] == signature:
        rows = "".join(f'<div class="pm-check {"ok" if c.ok else "no"}"><span class="ic">{"✓" if c.ok else "✕"}</span>'
                       f'<span><b style="font-weight:500">{esc(c.name.capitalize())}</b> · {esc(c.message)}</span></div>'
                       for c in checked[1])
        html_block(rows)
        failed = next((c for c in checked[1] if not c.ok), None)
        if failed:
            return None, failed.message
    return settings, None


def search_section(settings: RunSettings | None) -> bool:
    """Web search status; False when the session cap is used up (the run then uses the document only)."""
    st.subheader("Web search")
    has_key = bool(settings and settings.tavily_api_key) or bool(RunSettings.from_env(mode="public").tavily_api_key)
    if not has_key:
        html_block('<div class="pm-notice">Web search unavailable: no Tavily key. The agents will work from the document only.</div>')
        return False
    if current_mode() == "local":
        html_block('<p class="pm-provider"><span class="dot"></span>Tavily key from .env</p>')
        return True
    left = max(config.SEARCHES_PER_SESSION - searches_used(), 0)
    if left == 0:
        html_block('<div class="pm-notice">The web searches of this session are used up. '
                   'The next run works from the document only.</div>')
        return False
    html_block(f'<p class="pm-provider"><span class="dot"></span>Provided by the team · {left} of '
               f'{config.SEARCHES_PER_SESSION} searches left in this session</p>')
    st.caption("A run uses about 10 to 30 searches.")
    return True


def document_section() -> Path | None:
    st.subheader("Company document")
    source = st.segmented_control("Document", ["Sample document", "Upload your own"], default="Sample document",
                                  key="doc_source", label_visibility="collapsed")
    if source == "Upload your own":
        upload = st.file_uploader("Company or product document", type=[e.lstrip(".") for e in sorted(ALLOWED_EXTENSIONS)],
                                  help="Text must be selectable (no scans).", key="upload")
        if upload is None:
            return None
        path = Path(tempfile.mkdtemp(prefix="premortem_")) / upload.name
        path.write_bytes(upload.getvalue())
        return path
    options = samples()
    chosen = st.radio("Sample", [p for p, _ in options], key="sample", label_visibility="collapsed",
                      format_func=lambda p: p.name, captions=[c for _, c in options])
    return chosen


def start(path: Path, settings: RunSettings, search_ok: bool, review: bool, evaluate: bool) -> None:
    if not search_ok and settings.tavily_api_key:
        settings = replace(settings, tavily_api_key=None)
    try:
        run = Run(path, settings=settings)
    except DocumentParseError as e:
        st.session_state.start_error = str(e)
        return
    live = LiveRun(run, review=review, evaluate=evaluate)
    st.session_state.live = live
    st.session_state.setdefault("session_runs", []).append(live)
    st.session_state.current = {"kind": "live"}
    st.session_state.step = None
    st.session_state.start_error = None
    live.start()
    st.session_state.goto = "run"


def page() -> None:
    html_block('<h1 style="margin:0 0 6px;padding:0">New run</h1>'
               '<p class="pm-sub">Five agents turn a company document into a launch plan. You review the strategy before '
               'the campaign is written, and every claim links to its source.</p>')
    left, right = st.columns([3, 2], gap="large")
    with left:
        settings, key_error = model_section()
        search_ok = search_section(settings)
        path = document_section()
    with right, st.container(border=True, key="run_summary"):
        st.subheader("This run")
        review = st.toggle("Pause for my review of the strategy", value=True, key="review_strategy",
                           help="Off: the strategy is approved automatically, as in the evaluation.")
        stages = ["Brief", "Analysis", "Strategy", "Campaign", "Blueprint"]
        strip = '<span class="a">→</span>'.join(
            f'<span class="s{" rv" if s == "Strategy" and review else ""}">{s}{" · your review" if s == "Strategy" and review else ""}</span>'
            for s in stages)
        html_block(f'<div class="pm-strip" style="margin:0 0 14px">{strip}</div>')
        evaluate = st.toggle("Evaluate the result", value=False, key="auto_eval",
                             help="When the run ends, score the blueprint. Two calls to the judge model.")
        if settings is not None:
            rows = "".join(f"<tr><td>{ROLE_LABELS[r]}</td><td>{esc(m)}</td></tr>" for r, m in settings.models.items())
            html_block(f'<div class="pm-label" style="margin-top:10px">Model of each agent</div><table class="pm-models">{rows}</table>')
        st.write("")
        reason = key_error or (None if path else "Choose a sample document or upload one.")
        st.button("Run the pipeline", type="primary", icon=":material/play_arrow:", width="stretch",
                  disabled=bool(reason), on_click=start, args=(path, settings, search_ok, review, evaluate) if not reason else None,
                  key="run_button")
        if reason:
            st.caption(reason)
        if st.session_state.get("start_error"):
            st.error(st.session_state.start_error)
        st.caption("A run takes about 3 minutes on Anthropic, longer on free tiers.")
