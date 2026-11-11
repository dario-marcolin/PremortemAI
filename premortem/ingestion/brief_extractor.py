"""Document text → CompanyBrief."""

from langchain_core.messages import HumanMessage, SystemMessage

from premortem.config import RunSettings
from premortem.llm import get_llm, invoke_structured
from premortem.prompts import load_prompt
from premortem.schemas import CompanyBrief


def extract_brief(text: str, settings: RunSettings | None = None) -> CompanyBrief:
    """settings=None: the settings of the current run (inside the graph)."""
    llm = get_llm("brief", settings).with_structured_output(CompanyBrief)
    return invoke_structured(
        llm,
        [
            SystemMessage(load_prompt("brief_extractor")),
            HumanMessage(f"<document>\n{text}\n</document>"),
        ]
    )
