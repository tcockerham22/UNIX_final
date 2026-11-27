"""Small, dependency-free document text extractors for cloud chat uploads."""

from __future__ import annotations

import subprocess
import tempfile
from io import BytesIO
from pathlib import PurePath
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

DOCX_DOCUMENT_XML_LIMIT = 10 * 1024 * 1024
PDF_TEXT_TIMEOUT_SECONDS = 60


def extract_document_text(filename: str, content: bytes) -> str | None:
    """Extract readable text from common text files, Word, and PDF uploads."""
    extension = PurePath(filename).suffix.lower()
    if extension in {".txt", ".md", ".csv", ".json", ".rtf"}:
        return content.decode("utf-8", errors="replace").strip() or None
    if extension == ".docx":
        return _extract_docx_text(content)
    if extension == ".pdf":
        return _extract_pdf_text(content)
    return None


def _extract_pdf_text(content: bytes) -> str | None:
    """Read a PDF with an available Python library, then fall back to pdftotext."""
    # Prefer libraries that can read from memory so no file needs to be written.
    for module_name in ("pypdf", "PyPDF2"):
        try:
            module = __import__(module_name)
            reader = module.PdfReader(BytesIO(content))
            text = "\n".join(
                (page.extract_text() or "") for page in reader.pages
            ).strip()
            if text:
                return text
        except Exception:
            continue

    # Most VM images already have Poppler's pdftotext. It needs a path, so use
    # a private temporary file and remove it as soon as the call finishes.
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf") as temporary:
            temporary.write(content)
            temporary.flush()
            completed = subprocess.run(
                ["pdftotext", "-layout", temporary.name, "-"],
                capture_output=True,
                text=True,
                timeout=PDF_TEXT_TIMEOUT_SECONDS,
                check=False,
            )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return (completed.stdout or "").strip() or None


def _extract_docx_text(content: bytes) -> str:
    """Read paragraphs from a DOCX archive without extracting files to disk."""
    try:
        with ZipFile(BytesIO(content)) as archive:
            document_info = archive.getinfo("word/document.xml")
            if document_info.file_size > DOCX_DOCUMENT_XML_LIMIT:
                raise ValueError("The Word document contains too much text to process.")
            document_xml = archive.read(document_info)
    except (BadZipFile, KeyError) as error:
        raise ValueError("This .docx file is invalid or unreadable.") from error

    try:
        document = ElementTree.fromstring(document_xml)
    except ElementTree.ParseError as error:
        raise ValueError("This .docx file contains invalid document data.") from error

    word_namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    paragraphs = []
    for paragraph in document.iter(f"{word_namespace}p"):
        parts = []
        for element in paragraph.iter():
            if element.tag == f"{word_namespace}t":
                parts.append(element.text or "")
            elif element.tag == f"{word_namespace}tab":
                parts.append("\t")
            elif element.tag in {f"{word_namespace}br", f"{word_namespace}cr"}:
                parts.append("\n")
        text = "".join(parts).strip()
        if text:
            paragraphs.append(text)

    extracted_text = "\n".join(paragraphs).strip()
    if not extracted_text:
        raise ValueError("No readable text was found in the Word document.")
    return extracted_text
