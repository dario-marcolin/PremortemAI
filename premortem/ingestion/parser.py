"""File → plain text, ready to be placed in the LLM context."""

import warnings
from pathlib import Path

from markitdown import MarkItDown

from premortem import config

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".pptx", ".md", ".txt"}
CHARS_PER_TOKEN = 4  # rough estimate, good enough for a budget check
# MarkItDown falls back to plain text on a broken binary file, so check the signature first
MAGIC_BYTES = {".pdf": b"%PDF", ".docx": b"PK", ".pptx": b"PK"}


class DocumentParseError(ValueError):
    """The document cannot be turned into usable text."""


def estimate_tokens(text: str) -> int:
    return len(text) // CHARS_PER_TOKEN


def parse_document(path: str | Path) -> str:
    path = Path(path)
    if path.suffix.lower() not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise DocumentParseError(f"Unsupported file type '{path.suffix}' for {path.name}. Allowed: {allowed}")
    if not path.is_file():
        raise DocumentParseError(f"File not found: {path}")
    magic = MAGIC_BYTES.get(path.suffix.lower())
    if magic:
        with path.open("rb") as f:
            if f.read(len(magic)) != magic:
                raise DocumentParseError(f"{path.name} is not a valid {path.suffix} file or is corrupted.")

    try:
        text = MarkItDown().convert(str(path)).text_content or ""
    except Exception as e:
        raise DocumentParseError(f"Could not read {path.name}: {e}") from e

    text = text.strip()
    if not text:
        raise DocumentParseError(
            f"No text could be extracted from {path.name}. "
            "If it is a scanned PDF, export it with selectable text (OCR is not supported)."
        )

    tokens = estimate_tokens(text)
    if tokens > config.DOC_TOKEN_BUDGET:
        warnings.warn(
            f"{path.name} is about {tokens} tokens, above the budget of {config.DOC_TOKEN_BUDGET}: "
            "the text was truncated and the end of the document is ignored.",
            stacklevel=2,
        )
        text = text[: config.DOC_TOKEN_BUDGET * CHARS_PER_TOKEN]
    return text
