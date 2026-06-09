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


def render_page_image_base64(pdf_path: str | Path, page_number: int, dpi: int) -> str:
    return base64.b64encode(render_page_image_png_bytes(pdf_path, page_number, dpi)).decode("ascii")


def render_page_image_png_bytes(pdf_path: str | Path, page_number: int, dpi: int = RENDER_DPI) -> bytes:
    path = Path(pdf_path).expanduser()
    if page_number < 1:
        raise ValueError("Page numbers are 1-based and must be positive.")

    with fitz.open(path) as document:
        if page_number > document.page_count:
            raise ValueError(f"Page {page_number} is outside this {document.page_count}-page PDF.")

        page = document.load_page(page_number - 1)
        pixmap = page.get_pixmap(dpi=dpi, alpha=False)
        return pixmap.tobytes("png")


def render_page_region_image_base64(
    pdf_path: str | Path,
    page_number: int,
    dpi: int,
    region: tuple[float, float, float, float],
) -> str:
    return base64.b64encode(
        render_page_region_image_png_bytes(pdf_path, page_number, dpi, region)
    ).decode("ascii")


def render_page_region_image_png_bytes(
    pdf_path: str | Path,
    page_number: int,
    dpi: int,
    region: tuple[float, float, float, float],
) -> bytes:
    path = Path(pdf_path).expanduser()
    if page_number < 1:
        raise ValueError("Page numbers are 1-based and must be positive.")

    x0, y0, x1, y1 = _normalized_region(region)
    with fitz.open(path) as document:
        if page_number > document.page_count:
            raise ValueError(f"Page {page_number} is outside this {document.page_count}-page PDF.")

        page = document.load_page(page_number - 1)
        rect = page.rect
        clip = fitz.Rect(
            rect.x0 + (rect.width * x0),
            rect.y0 + (rect.height * y0),
            rect.x0 + (rect.width * x1),
            rect.y0 + (rect.height * y1),
        )
        pixmap = page.get_pixmap(dpi=dpi, alpha=False, clip=clip)
        return pixmap.tobytes("png")


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


def _normalized_region(region: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = region
    x0 = min(max(float(x0), 0.0), 1.0)
    y0 = min(max(float(y0), 0.0), 1.0)
    x1 = min(max(float(x1), 0.0), 1.0)
    y1 = min(max(float(y1), 0.0), 1.0)
    if x1 <= x0 or y1 <= y0:
        raise ValueError("Page crop region must have positive width and height.")
    return x0, y0, x1, y1
