"""LaunchState → Launch Blueprint (Markdown).

Everything is rendered directly from the state with templates/blueprint.md.j2, so the
blueprint cannot drift from what the agents decided. The executive summary is the only
part written by an LLM. Source ids (S1, S2...) become numbered references [1], [2] in
order of first appearance, with the Sources list at the end.
"""

import re
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from langchain_core.messages import HumanMessage, SystemMessage

from premortem import config
from premortem.config import RunSettings
from premortem.agents.analyst import SOURCE_ID
from premortem.agents.revision import blocking_issues
from premortem.llm import current_settings, get_llm
from premortem.prompts import load_prompt
from premortem.schemas import Analysis, Source, Stage, ValidationIssue
from premortem.state import LaunchState

TEMPLATES = Path(__file__).parent / "templates"
# A bracket group ("[S2]", "[S1, S3]") or a bare id with its leading comma ("1.3M adults, S3")
CITATION = re.compile(r"\[[^\]]*\]|(?:,\s*)?\bS[1-9]\d*\b")


class References:
    """Numbers source ids in order of first use. Unknown ids are kept, marked with '?'."""

    def __init__(self, sources: list[Source]):
        self.sources = {s.id: s for s in sources}
        self.numbers: dict[str, int] = {}

    def number(self, source_id: str) -> str:
        if source_id not in self.sources:
            return f"{source_id}?"
        return str(self.numbers.setdefault(source_id, len(self.numbers) + 1))

    def cite(self, source_ids: list[str]) -> str:
        return f"[{', '.join(self.number(i) for i in source_ids)}]" if source_ids else ""

    def refs(self, text: str) -> str:
        """Renumber the ids inside text: "[S2, S3]" → "[1, 2]", a bare listed ", S2" → " [1]".
        A bare unlisted token (e.g. "Galaxy S24") is left intact."""

        def sub(match: re.Match) -> str:
            token = match.group()
            if token.startswith("["):
                return SOURCE_ID.sub(lambda m: self.number(m.group()), token)
            source_id = token.lstrip(", \t\n")
            if source_id not in self.sources:
                return token
            return f"{' ' if token.startswith(',') else ''}[{self.number(source_id)}]"

        return CITATION.sub(sub, text)

    def listed(self) -> list[tuple[int, Source]]:
        """Every source, cited ones first; sources the blueprint never cites come last."""
        for source_id in self.sources:
            self.number(source_id)
        return sorted(((int(n), self.sources[i]) for i, n in self.numbers.items()), key=lambda x: x[0])


def _cell(text: str) -> str:
    """A value that fits in one Markdown table cell."""
    return re.sub(r"\s*\n\s*", " ", str(text)).replace("|", "\\|")


def validation_log(state: LaunchState) -> list[dict]:
    """Every ValidationResult in run order, with each issue's status.

    A blocking issue is resolved when the latest validation of its stage no longer
    raises the same check as blocking.
    """
    attempts: dict[str, int] = {}
    log = []
    for result in state.get("validations") or []:
        attempts[result.stage] = attempts.get(result.stage, 0) + 1
        still_blocking = {i.check for i in blocking_issues(state, result.stage)}
        issues = [
            (i, "warning" if i.severity == "warning"
             else "blocking, unresolved" if i.check in still_blocking else "blocking, resolved")
            for i in result.issues
        ]
        log.append({"stage": result.stage, "attempt": attempts[result.stage], "result": result, "issues": issues})
    return log


def open_issues(state: LaunchState) -> list[tuple[Stage, ValidationIssue]]:
    return [(stage, i) for stage in ("strategy", "campaign") for i in blocking_issues(state, stage)]


def _summary_input(state: LaunchState) -> str:
    analysis: Analysis = state["analysis"]
    segment = analysis.find_segment(state["strategy"].target_segment_id)
    unresolved = "\n".join(f"- [{stage}] {i.check}: {i.message}" for stage, i in open_issues(state)) or "None."
    return (
        f"<brief>\n{state['brief'].model_dump_json(indent=2)}\n</brief>\n\n"
        f"<segments>\n{analysis.model_dump_json(include={'segments'}, indent=2)}\n</segments>\n\n"
        f"<data_quality_notes>\n{analysis.model_dump_json(include={'data_quality_notes'}, indent=2)}\n"
        "</data_quality_notes>\n\n"
        f"<target_segment>\n{segment.model_dump_json(indent=2) if segment else 'Not found in the analysis.'}\n"
        "</target_segment>\n\n"
        f"<strategy>\n{state['strategy'].model_dump_json(indent=2)}\n</strategy>\n\n"
        f"<campaign>\n{state['campaign'].model_dump_json(indent=2)}\n</campaign>\n\n"
        f"<unresolved_blocking_issues>\n{unresolved}\n</unresolved_blocking_issues>\n\n"
        "The company approved this strategy at the human approval step.\n\n"
        "Write the executive summary."
    )


def write_executive_summary(state: LaunchState, settings: RunSettings | None = None) -> str:
    """The blueprint role: the big model of the preset, one call per run."""
    try:
        response = get_llm("blueprint", settings).invoke([SystemMessage(load_prompt("executive_summary")), HumanMessage(_summary_input(state))])
    except Exception as e:  # the rest of the blueprint is still worth saving
        return f"*The executive summary could not be written: {e}*"
    # Source ids are not allowed in the summary: strip any that slip through
    return re.sub(r"\s*\[S\d+(?:,\s*S\d+)*\]", "", response.text).strip()


# The target segment's row: its id in bold. Blueprints written before Nov 2026 put an arrow before it
# ("**→ SEG2**") and a note about the arrow; the screen and the PDF read both and draw the new look.
TARGET_CELL = re.compile(r"^\*\*(?:→ )?(SEG\w+)\*\*$")
TARGET_NOTE = "The highlighted row, in bold, is the target segment chosen in the strategy."
OLD_TARGET_NOTE = "→ marks the target segment chosen in the strategy."


def current_target_marker(markdown: str) -> str:
    """A blueprint with the old arrow marker, in the current form (a no-op on a current blueprint)."""
    return re.sub(r"^\| \*\*→ (SEG\w+)\*\* \|", r"| **\1** |", markdown, flags=re.M).replace(OLD_TARGET_NOTE, TARGET_NOTE)

MODELS_PREFIX = "Models:"


def models_line(models: dict[str, str] | None) -> str:
    """"Models: claude-sonnet-5-5 (agents) · claude-opus-5-5 (blueprint)", from role -> model id.
    The id's LangChain prefix ("anthropic:") is dropped; one model for every role is named once."""
    if not models:
        return ""
    name = lambda role: (models.get(role) or "").split(":", 1)[-1]
    agents = sorted({name(r) for r in config.ROLES if r != "blueprint" and models.get(r)})
    summary = name("blueprint")
    if agents == [summary] or not summary:
        return f"{MODELS_PREFIX} {', '.join(agents)}"
    return f"{MODELS_PREFIX} {', '.join(agents)} (agents) · {summary} (blueprint)"


def _run_models(settings: RunSettings | None) -> dict[str, str] | None:
    try:
        return (settings or current_settings()).models
    except RuntimeError:  # rendered outside a run with no settings (tests, re-renders)
        return None


def render_blueprint(state: LaunchState, summary: str | None = None, settings: RunSettings | None = None) -> str:
    """The blueprint as Markdown. summary=None asks the LLM for the executive summary
    (settings=None: the settings of the current run, inside the graph)."""
    references = References(state["analysis"].sources)
    env = Environment(
        loader=FileSystemLoader(TEMPLATES), trim_blocks=True, lstrip_blocks=True,
        keep_trailing_newline=True, undefined=StrictUndefined,
    )
    env.filters.update(cite=references.cite, refs=references.refs, cell=_cell)
    return env.get_template("blueprint.md.j2").render(
        brief=state["brief"],
        analysis=state["analysis"],
        strategy=state["strategy"],
        target=state["analysis"].find_segment(state["strategy"].target_segment_id),
        campaign=state["campaign"],
        strategy_revisions=state.get("strategy_revisions", 0),
        summary=write_executive_summary(state, settings) if summary is None else summary,
        open_issues=open_issues(state),
        log=validation_log(state),
        max_revisions=config.MAX_REVISIONS,
        references=references.listed,
        generated=date.today().isoformat(),
        models=models_line(_run_models(settings)),
    )


def save_blueprint(state: LaunchState, path: str | Path, summary: str | None = None,
                   settings: RunSettings | None = None) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_blueprint(state, summary, settings))
    return path
