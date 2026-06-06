from __future__ import annotations

import base64
import re
import tempfile
from pathlib import Path

import fitz

from app.pdf.models import ParsedDocument, ParsedPage, ParsedPdf


RENDER_DPI = 150
MAX_LABELS_PER_PAGE = 200


def parse_pdf(pdf_path: str | Path, working_dir: str | Path | None = None) -> ParsedPdf:
    path = Path(pdf_path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")
    if not path.is_file():
        raise ValueError(f"Expected a PDF file path, got: {path}")

    output_dir = _prepare_working_dir(working_dir)
    pages: list[ParsedPage] = []

    try:
        with fitz.open(path) as document:
            if document.is_encrypted and not document.authenticate(""):
                raise ValueError("This PDF is password-protected and cannot be parsed without a password.")

            for page_index in range(document.page_count):
                page_number = page_index + 1
                page = document.load_page(page_index)
                text = page.get_text("text").strip()
                image_path = output_dir / f"{path.stem}_page_{page_number:03d}.png"

                # 150 DPI keeps drawing text readable for Claude vision while avoiding oversized images/token payloads.
                pixmap = page.get_pixmap(dpi=RENDER_DPI, alpha=False)
                pixmap.save(str(image_path))

                pages.append(
                    ParsedPage(
                        page_number=page_number,
                        text=text,
                        annotations=_extract_annotations_and_labels(page),
                        image_base64=base64.b64encode(image_path.read_bytes()).decode("ascii"),
                        image_path=image_path,
                    )
                )
    except fitz.FileDataError as exc:
        raise ValueError(f"Could not open PDF: {path}") from exc

    return ParsedPdf(
        document=ParsedDocument(filename=path.name, page_count=len(pages)),
        pages=pages,
        working_dir=output_dir,
    )


def _prepare_working_dir(working_dir: str | Path | None) -> Path:
    if working_dir is None:
        return Path(tempfile.mkdtemp(prefix="compliance_pdf_pages_"))

    output_dir = Path(working_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _extract_annotations_and_labels(page: fitz.Page) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()

    for item in _extract_pdf_annotations(page):
        _append_unique(items, seen, item)

    for item in _extract_text_labels(page):
        _append_unique(items, seen, item)
        if len(items) >= MAX_LABELS_PER_PAGE:
            break

    return items


def _extract_pdf_annotations(page: fitz.Page) -> list[str]:
    annotations: list[str] = []
    for annotation in page.annots() or []:
        info = annotation.info or {}
        type_name = annotation.type[1] if annotation.type else "Annotation"
        parts = [
            _normalize_text(info.get("title", "")),
            _normalize_text(info.get("subject", "")),
            _normalize_text(info.get("content", "")),
        ]
        details = " | ".join(part for part in parts if part)
        if details:
            annotations.append(f"PDF {type_name}: {details}")
        else:
            annotations.append(f"PDF {type_name}")
    return annotations


def _extract_text_labels(page: fitz.Page) -> list[str]:
    labels: list[str] = []
    text_dict = page.get_text("dict")

    for block in text_dict.get("blocks", []):
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            text = _normalize_text(" ".join(span.get("text", "") for span in spans))
            if _looks_like_drawing_label(text):
                labels.append(text)

    return labels


def _looks_like_drawing_label(text: str) -> bool:
    if not text or len(text) > 120:
        return False

    word_count = len(text.split())
    if word_count > 12:
        return False

    has_digit = any(character.isdigit() for character in text)
    has_upper = any(character.isupper() for character in text)
    has_symbol = bool(re.search(r"[-/#().]", text))
    return has_digit or has_upper or has_symbol


def _append_unique(items: list[str], seen: set[str], item: str) -> None:
    normalized = _normalize_text(item)
    if normalized and normalized not in seen:
        items.append(normalized)
        seen.add(normalized)


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
