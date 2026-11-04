from pathlib import Path

import pytest
from fpdf import FPDF

from premortem import config
from premortem.ingestion.parser import DocumentParseError, parse_document

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("name", ["sample.pdf", "sample.docx"])
def test_fixture_parses_to_text(name):
    text = parse_document(FIXTURES / name)
    assert "Acme Snacks" in text


def test_markdown_and_txt(tmp_path):
    for name in ["doc.md", "doc.txt"]:
        path = tmp_path / name
        path.write_text("Acme Snacks sells chickpea snacks.")
        assert "Acme Snacks" in parse_document(path)


@pytest.mark.parametrize("name", ["data.csv", "image.png", "noextension"])
def test_wrong_extension_raises(tmp_path, name):
    path = tmp_path / name
    path.write_text("x")
    with pytest.raises(DocumentParseError, match="Unsupported file type"):
        parse_document(path)


def test_missing_file_raises(tmp_path):
    with pytest.raises(DocumentParseError, match="File not found"):
        parse_document(tmp_path / "missing.pdf")


def test_empty_file_raises(tmp_path):
    path = tmp_path / "empty.txt"
    path.write_text("   \n")
    with pytest.raises(DocumentParseError, match="No text could be extracted"):
        parse_document(path)


def test_pdf_without_text_raises(tmp_path):
    # Stands in for a scanned PDF: a page with no text layer.
    pdf = FPDF()
    pdf.add_page()
    pdf.rect(20, 20, 100, 100)
    path = tmp_path / "scanned.pdf"
    pdf.output(str(path))
    with pytest.raises(DocumentParseError, match="No text could be extracted"):
        parse_document(path)


def test_corrupted_file_raises(tmp_path):
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"not really a pdf")
    with pytest.raises(DocumentParseError, match="corrupted"):
        parse_document(path)


def test_long_document_is_truncated_with_warning(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DOC_TOKEN_BUDGET", 10)
    path = tmp_path / "long.txt"
    path.write_text("word " * 100)
    with pytest.warns(UserWarning, match="truncated"):
        text = parse_document(path)
    assert len(text) == 40
