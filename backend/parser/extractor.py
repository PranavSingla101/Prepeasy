import re
import pdfplumber
import fitz  # pymupdf


def extract_text(pdf_path: str) -> str:
    """Extract raw text from a PDF file. Falls back to PyMuPDF if pdfplumber yields < 100 chars."""
    try:
        text = _extract_pdfplumber(pdf_path)
    except Exception as e:
        _raise_if_encrypted(e)
        text = ""

    if len(text.strip()) < 100:
        try:
            text = _extract_pymupdf(pdf_path)
        except Exception as e:
            _raise_if_encrypted(e)
            raise ValueError(
                f"Could not extract text from PDF — file may be corrupt or unreadable: {e}"
            ) from e

    return _clean(text)


def _raise_if_encrypted(exc: Exception) -> None:
    msg = str(exc).lower()
    if any(kw in msg for kw in ("encrypt", "password", "protected")):
        raise ValueError(
            "PDF is password-protected — remove the password before uploading"
        ) from exc


def _extract_pdfplumber(pdf_path: str) -> str:
    with pdfplumber.open(pdf_path) as pdf:
        pages = []
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                pages.append(page_text)
        return "\n".join(pages)


def _extract_pymupdf(pdf_path: str) -> str:
    doc = fitz.open(pdf_path)
    pages = []
    for page in doc:
        pages.append(page.get_text())
    doc.close()
    return "\n".join(pages)


def _clean(text: str) -> str:
    # Collapse 3+ consecutive newlines to 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Strip lines that are only whitespace
    lines = [line.rstrip() for line in text.splitlines()]
    return "\n".join(lines).strip()
