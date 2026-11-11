"""Parts every step view shares: the title row, the round selector with "What changed", the Validator."""

import difflib

import streamlit as st

from ui.citations import Citer
from ui.theme import esc, html_block, pill
from ui.view import STEP_LABELS, RunView, StepInfo

FIELD_LABELS = {
    "target_segment_id": "Target segment", "target_description": "Target", "positioning_statement": "Positioning",
    "value_proposition": "Value proposition", "pricing_direction": "Pricing direction", "channels": "Channels",
    "rationale": "Rationale", "supporting_source_ids": "Sources", "concept": "Concept", "tagline": "Tagline",
    "key_messages": "Messages", "content_ideas": "Content ideas", "visual_direction": "Visual direction",
    "market_overview": "Market overview", "competitors": "Competitors", "customer_needs": "Customer needs",
    "segments": "Segments", "data_quality_notes": "Data quality notes", "sources": "Sources",
}


def pills(view: RunView, info: StepInfo) -> str:
    parts = [pill(info.status)]
    if info.rounds > 1:
        parts.append(pill("done", f"{info.rounds} rounds"))
    if info.blocking and info.unresolved:
        parts.append(pill("limit"))
    elif info.warnings:
        parts.append(pill("warning", f"{info.warnings} warning{'s' if info.warnings > 1 else ''}"))
    return " ".join(parts)


def title_head(view: RunView, info: StepInfo) -> None:
    html_block(f'<h1 style="margin:0 0 6px;padding:0">{esc(STEP_LABELS[info.key])}</h1>'
               f'<div style="margin:0 0 10px">{pills(view, info)}</div>')


def title_sentence(sentence: str) -> None:
    html_block(f'<p class="pm-sub" style="margin:0 0 22px">{sentence}</p>')


def title_row(view: RunView, info: StepInfo, sentence: str) -> None:
    title_head(view, info)
    title_sentence(sentence)


def round_picker(view: RunView, key: str) -> int:
    """The round on screen (1-based); a selector only when the step ran more than once."""
    versions = view.rounds.get(key) or []
    if len(versions) <= 1:
        return len(versions)
    options = list(range(1, len(versions) + 1))
    chosen = st.radio("Round", options, index=len(versions) - 1, key=f"round_{view.run_id}_{key}",
                      horizontal=True, label_visibility="collapsed",
                      format_func=lambda i: f"Round {i}" + (" · latest" if i == len(versions) else ""))
    return chosen or len(versions)


def _short(value) -> str:
    if isinstance(value, list):
        return "; ".join(_short(v) for v in value)
    if isinstance(value, dict):
        return " · ".join(str(v) for v in value.values() if isinstance(v, str))
    return str(value)


def what_changed(view: RunView, key: str, chosen: int, citer: Citer) -> None:
    """The fields that differ from the previous round, old in grey, new in ink."""
    versions = view.rounds.get(key) or []
    if chosen < 2 or chosen > len(versions):
        return
    old, new = versions[chosen - 2], versions[chosen - 1]
    changed = [k for k in new if new.get(k) != old.get(k)]
    why = reason_for_round(view, key, chosen)
    if not changed:
        html_block(f'<div class="pm-changed"><div class="k">What changed since round {chosen - 1}</div>'
                   f'Nothing: the {key} came back the same. {esc(why)}</div>')
        return
    rows = []
    for k in changed:
        if k.endswith("source_ids"):
            added = [i for i in new[k] if i not in (old.get(k) or [])]
            dropped = [i for i in (old.get(k) or []) if i not in new[k]]
            body = ("<div>" + (f"Added {citer.ids(added)} " if added else "")
                    + (f"Dropped <del>{esc(', '.join(dropped))}</del>" if dropped else "") + "</div>")
        elif isinstance(new[k], list) and new[k] and isinstance(new[k][0], dict):  # segments, competitors, messages
            body = f"<div>{esc(_short(new[k])[:400])}</div>"
        else:
            body = f"<div>{inline_diff(_short(old.get(k, '')), _short(new[k]), citer)}</div>"
        rows.append(f'<div class="k">{esc(FIELD_LABELS.get(k, k))}</div>{body}')
    html_block(f'<div class="pm-changed"><div class="k" style="font-size:13px">What changed since round {chosen - 1}'
               f' · {len(changed)} field{"s" if len(changed) > 1 else ""}</div>'
               f'<div style="font-size:13px;color:var(--muted);margin:0 0 4px">{esc(why)}</div>{"".join(rows)}</div>')


def inline_diff(old: str, new: str, citer: Citer) -> str:
    """The new text with the words it added highlighted and the words it dropped struck through, in place."""
    a, b = old.split(), new.split()
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op in ("delete", "replace"):
            out.append("\x03" + " ".join(a[i1:i2]) + "\x04")
        if op in ("insert", "replace"):
            out.append("\x01" + " ".join(b[j1:j2]) + "\x02")
        if op == "equal":
            out.append(" ".join(b[j1:j2]))
    html = citer.text(" ".join(out))
    return (html.replace("\x01", "<ins>").replace("\x02", "</ins>")
            .replace("\x03", "<del>").replace("\x04", "</del>"))


def reason_for_round(view: RunView, key: str, chosen: int) -> str:
    """Why the step ran again: your feedback, or the Validator's blocking issues."""
    if key == "strategy":
        rejected = [d for d in view.decisions() if not d.get("approved")]
        stage_runs = view.validations_of("strategy")
        # A rejection comes after the strategy was shown to you; count the reviews before this round
        if rejected and chosen - 1 <= len(stage_runs):
            previous = stage_runs[chosen - 2] if chosen - 2 < len(stage_runs) else None
            if previous is not None and previous.passed:
                feedback = rejected[0].get("feedback")
                return f"You sent it back{': ‘' + feedback + '’' if feedback else ''}."
    stage_runs = view.validations_of(key)
    if 0 <= chosen - 2 < len(stage_runs) and not stage_runs[chosen - 2].passed:
        n = len(stage_runs[chosen - 2].blocking_issues)
        return f"The Validator found {n} blocking issue{'s' if n > 1 else ''} in round {chosen - 1}."
    return ""


def validator_block(view: RunView, stage: str, chosen: int, info: StepInfo) -> None:
    runs = view.validations_of(stage)
    if not runs:
        return
    result = runs[min(chosen, len(runs)) - 1] if chosen else runs[-1]
    blocking = [i for i in result.issues if i.severity == "blocking"]
    warnings = [i for i in result.issues if i.severity == "warning"]
    word = "passed" if result.passed else f"{len(blocking)} blocking"
    st.subheader(f"Validator · round {min(chosen, len(runs)) or len(runs)} · {word}, "
                 f"{len(warnings)} warning{'s' if len(warnings) != 1 else ''}")
    if info.unresolved and result is runs[-1]:
        html_block('<div class="pm-notice">Revision limit reached: the blocking issues below are still open. '
                   'They are listed at the top of the blueprint.</div>')
    if not result.issues:
        st.caption("No issues: every rule and the judge passed.")
        return
    rows = []
    for i in [*blocking, *warnings]:
        status = "blocking" if i.severity == "blocking" else "warning"
        if status == "blocking" and result is not runs[-1]:
            word = "Blocking · sent back for revision"
        else:
            word = None
        rows.append(f'<div class="pm-issue">{pill(status, word)}<div class="t"><b>{esc(i.check)}</b> · {esc(i.message)}</div></div>')
    html_block("".join(rows))


def version(view: RunView, key: str, chosen: int, model):
    """The output of the chosen round as its Pydantic model (the latest when there is one round)."""
    versions = view.rounds.get(key) or []
    if 1 <= chosen <= len(versions):
        return model.model_validate(versions[chosen - 1])
    return getattr(view, key)
