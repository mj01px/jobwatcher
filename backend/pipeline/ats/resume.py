"""Extract plain text from an uploaded resume (PDF, DOCX or TXT).

Pure-Python readers (pypdf, python-docx) so the desktop build needs no system
libraries. A scanned PDF (images, no text layer) yields almost nothing, which we
treat as an error with an explanation rather than sending an empty resume to the
model.
"""

from __future__ import annotations

import io
import logging
from pathlib import PurePosixPath

logger = logging.getLogger(__name__)

MAX_BYTES = 5 * 1024 * 1024
# Below this, there is nothing meaningful to analyse (empty file, or a scanned
# PDF with no text layer).
MIN_CHARS = 200
ALLOWED_SUFFIXES = (".pdf", ".docx", ".txt")


class ResumeError(ValueError):
    """The upload is missing, too big, an unsupported type or has no readable text."""


def _from_pdf(content: bytes) -> str:
    # pypdf raises a wide, undocumented range of exceptions on odd PDFs (custom
    # fonts, broken xref, encryption). Any of them means "unreadable", not a crash,
    # so we catch broadly and turn it into a friendly ResumeError.
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(content))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as error:
        logger.warning("PDF extraction failed: %s", type(error).__name__)
        raise ResumeError(
            "Could not read this PDF. It may be scanned, encrypted or unusual. "
            "Try exporting it again or send a DOCX."
        ) from error


def _from_docx(content: bytes) -> str:
    from docx import Document

    try:
        document = Document(io.BytesIO(content))
        parts = [paragraph.text for paragraph in document.paragraphs]
        # CVs often keep contact details and skills in tables.
        for table in document.tables:
            for row in table.rows:
                parts.extend(cell.text for cell in row.cells)
        return "\n".join(parts)
    except Exception as error:
        logger.warning("DOCX extraction failed: %s", type(error).__name__)
        raise ResumeError("Could not read this DOCX file. It may be corrupted.") from error


def _normalise(text: str) -> str:
    # Collapse the runs of blank lines and trailing spaces that PDF extraction
    # leaves behind, without merging real line breaks.
    lines = [line.strip() for line in text.replace("\r", "\n").split("\n")]
    kept: list[str] = []
    blank = False
    for line in lines:
        if line:
            kept.append(line)
            blank = False
        elif not blank:
            kept.append("")
            blank = True
    return "\n".join(kept).strip()


def extract_resume_text(filename: str, content: bytes) -> str:
    """Return the resume's text, ready for the prompt.

    Raises:
        ResumeError: on an empty upload, a file over ``MAX_BYTES``, an unsupported
            extension, or a file whose readable text is shorter than ``MIN_CHARS``.
    """
    if not content:
        raise ResumeError("The uploaded file is empty.")
    if len(content) > MAX_BYTES:
        raise ResumeError(f"The file is larger than {MAX_BYTES // (1024 * 1024)} MB.")

    suffix = PurePosixPath(filename or "").suffix.lower()
    if suffix == ".pdf":
        text = _from_pdf(content)
    elif suffix == ".docx":
        text = _from_docx(content)
    elif suffix == ".txt":
        text = content.decode("utf-8", errors="replace")
    else:
        raise ResumeError("Unsupported file type. Send a PDF, DOCX or TXT resume.")

    cleaned = _normalise(text)
    if len(cleaned) < MIN_CHARS:
        raise ResumeError(
            "Almost no text could be read from this file. If it is a scanned PDF "
            "(an image), send a version with real text or a DOCX."
        )
    return cleaned
