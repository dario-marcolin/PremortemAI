"""Document text → CompanyBrief."""

from langchain_core.messages import HumanMessage, SystemMessage

from premortem.llm import get_llm
from premortem.prompts import load_prompt
from premortem.schemas import CompanyBrief


def extract_brief(text: str) -> CompanyBrief:
    llm = get_llm().with_structured_output(CompanyBrief)
    return llm.invoke(
        [
            SystemMessage(load_prompt("brief_extractor")),
            HumanMessage(f"<document>\n{text}\n</document>"),
        ]
    )
