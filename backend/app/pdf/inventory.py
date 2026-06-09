from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from anthropic import AsyncAnthropic
from pydantic import BaseModel, Field, ValidationError

from app.config import (
    CLAUDE_MODEL,
    DRAWING_INVENTORY_CONFIDENCE_THRESHOLD,
    DRAWING_INVENTORY_CROP_DPI,
    DRAWING_INVENTORY_IMAGE_DPI,
    MAX_IMAGE_BASE64_CHARS_PER_REQUEST,
)
from app.pdf.models import DrawingInventory, DrawingInventoryItem, DrawingViewType, ParsedPage, ParsedPdf
from app.pdf.parser import render_page_image_base64, render_page_region_image_base64


logger = logging.getLogger(__name__)
ProgressCallback = Callable[[str], None]
MAX_EVIDENCE_LABELS = 8
MAX_CLASSIFIER_TEXT_CHARS = 1_600
MAX_CLASSIFIER_LABELS = 30

VIEW_TYPES: tuple[DrawingViewType, ...] = (
    "Floor Plan",
    "Site Plan",
    "Section",
    "Elevation",
    "Section & Elevation",
    "Detail",
    "Schedule/General",
    "Unknown",
)
VIEW_TYPE_PATTERN_GROUPS: dict[DrawingViewType, tuple[tuple[str, int], ...]] = {
    "Section": (
        (r"\bsection\s*(?:[0-9A-Z]+|[A-Z]-[A-Z])?\b", 5),
        (r"\bsec\.?\s*(?:[0-9A-Z]+|[A-Z]-[A-Z])\b", 4),
        (r"\bcut\s+section\b", 4),
        (r"\bsection\s+line\b", 2),
    ),
    "Elevation": (
        (r"\belevation\s*(?:[0-9A-Z]+|[A-Z]-[A-Z])?\b", 5),
        (r"\bfront\s+elevation\b", 5),
        (r"\brear\s+elevation\b", 5),
        (r"\bside\s+elevation\b", 5),
    ),
    "Site Plan": (
        (r"\bsite\s+plan\b", 6),
        (r"\blocation\s+plan\b", 4),
        (r"\bboundary\s+plan\b", 3),
        (r"\bkey\s+plan\b", 2),
    ),
    "Floor Plan": (
        (r"\bfloor\s+plan\b", 6),
        (r"\b(?:basement|attic|roof|storey|story|level)\s+plan\b", 5),
        (r"\b(?:1st|2nd|3rd|4th|first|second|third|fourth)\s+(?:storey|story)\s+plan\b", 6),
        (r"\bplan\s+view\b", 3),
    ),
    "Detail": (
        (r"\bdetail(?:s)?\b", 4),
        (r"\btypical\s+detail\b", 5),
        (r"\benlarged\s+detail\b", 5),
        (r"\bblow[- ]?up\b", 3),
    ),
    "Schedule/General": (
        (r"\bschedule\b", 5),
        (r"\bgeneral\s+notes\b", 5),
        (r"\bcover\s+sheet\b", 4),
        (r"\blegend\b", 3),
        (r"\bdrawing\s+list\b", 4),
    ),
}

CROP_REGIONS: tuple[tuple[str, tuple[float, float, float, float]], ...] = (
    ("title block crop", (0.52, 0.72, 1.0, 1.0)),
    ("view title crop", (0.0, 0.68, 0.58, 1.0)),
    ("main drawing crop", (0.05, 0.05, 0.95, 0.78)),
)


class ClaudeInventoryPage(BaseModel):
    primary_view_type: DrawingViewType
    detected_view_types: list[DrawingViewType] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    sheet_title: str = ""
    drawing_number: str = ""
    evidence_labels: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


async def build_drawing_inventory(
    pdf_path: str | Path,
    parsed_pdf: ParsedPdf,
    client: AsyncAnthropic | None = None,
    progress_callback: ProgressCallback | None = None,
) -> DrawingInventory:
    path = Path(pdf_path)
    items = [classify_page_heuristic(page) for page in parsed_pdf.pages]

    low_confidence_indexes = [
        index
        for index, item in enumerate(items)
        if _needs_confirmation(item)
    ]
    if client is None or not low_confidence_indexes:
        return DrawingInventory(pages=items)

    for index in low_confidence_indexes:
        page = parsed_pdf.pages[index]
        _report_progress(f"Understanding drawing page {page.page_number}", progress_callback)
        try:
            refined = await _classify_page_with_claude(path, page, items[index], client)
        except Exception:
            logger.exception("Could not refine drawing inventory for page %s.", page.page_number)
            items[index].warnings.append("Claude view-type refinement failed; please confirm this page manually.")
            continue

        items[index] = _choose_stronger_inventory_item(items[index], refined)

    return DrawingInventory(pages=items)


def build_heuristic_drawing_inventory(parsed_pdf: ParsedPdf) -> DrawingInventory:
    return DrawingInventory(
        pages=[classify_page_heuristic(page) for page in parsed_pdf.pages]
    )


def inventory_needs_confirmation(inventory: DrawingInventory) -> bool:
    return any(_needs_confirmation(item) for item in inventory.pages)


def classify_page_heuristic(page: ParsedPage) -> DrawingInventoryItem:
    text_lines = _clean_lines(page.text)
    label_lines = _clean_lines("\n".join(page.annotations))
    combined_text = _normalize_for_match("\n".join(text_lines + label_lines))
    evidence: list[str] = []
    scores = {view_type: 0 for view_type in VIEW_TYPE_PATTERN_GROUPS}

    for view_type, patterns in VIEW_TYPE_PATTERN_GROUPS.items():
        for pattern, weight in patterns:
            matches = re.findall(pattern, combined_text, flags=re.IGNORECASE)
            if not matches:
                continue
            scores[view_type] += weight * len(matches)
            evidence.append(_evidence_for_pattern(pattern, text_lines + label_lines))

    section_score = scores["Section"]
    elevation_score = scores["Elevation"]
    if section_score >= 4 and elevation_score >= 4:
        primary_view_type: DrawingViewType = "Section & Elevation"
        detected_view_types: list[DrawingViewType] = ["Section", "Elevation", "Section & Elevation"]
        confidence = _confidence_for_score(section_score + elevation_score, combined=True)
    else:
        primary_view_type, top_score = _top_scored_view(scores)
        detected_view_types = _detected_view_types(scores)
        confidence = _confidence_for_score(top_score)

    warnings: list[str] = []
    if primary_view_type == "Unknown":
        warnings.append("No clear drawing view title was detected.")
    elif _has_close_second_choice(scores, primary_view_type):
        confidence = min(confidence, 0.72)
        warnings.append("Multiple drawing view types look plausible from the embedded text.")

    sheet_title = _detect_sheet_title(text_lines + label_lines, primary_view_type)
    drawing_number = _detect_drawing_number(text_lines + label_lines)
    evidence_labels = _dedupe([item for item in evidence if item])[:MAX_EVIDENCE_LABELS]
    if sheet_title and sheet_title not in evidence_labels:
        evidence_labels.insert(0, sheet_title)

    if _needs_confirmation_score(primary_view_type, confidence):
        warnings.append("Please confirm this drawing view type before compliance review.")

    return DrawingInventoryItem(
        page_number=page.page_number,
        sheet_title=sheet_title,
        drawing_number=drawing_number,
        primary_view_type=primary_view_type,
        detected_view_types=detected_view_types or ([primary_view_type] if primary_view_type != "Unknown" else []),
        confidence=confidence,
        evidence_labels=evidence_labels,
        warnings=_dedupe(warnings),
    )


async def _classify_page_with_claude(
    pdf_path: Path,
    page: ParsedPage,
    heuristic_item: DrawingInventoryItem,
    client: AsyncAnthropic,
) -> DrawingInventoryItem:
    content = _classifier_content(pdf_path, page, heuristic_item)
    response = await client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=900,
        temperature=0,
        system=(
            "You classify architectural PDF drawing pages for a local compliance reviewer. "
            "Use only visible drawing evidence. Distinguish floor plans from sections and elevations carefully. "
            "Return JSON only."
        ),
        messages=[{"role": "user", "content": content}],
    )
    text_parts: list[str] = []
    for block in response.content:
        text = getattr(block, "text", None)
        if text:
            text_parts.append(text)

    refined = _parse_claude_inventory_response("\n".join(text_parts))
    return DrawingInventoryItem(
        page_number=page.page_number,
        sheet_title=refined.sheet_title.strip() or heuristic_item.sheet_title,
        drawing_number=refined.drawing_number.strip() or heuristic_item.drawing_number,
        primary_view_type=refined.primary_view_type,
        detected_view_types=_valid_detected_views(refined.detected_view_types, refined.primary_view_type),
        confidence=max(0.0, min(1.0, refined.confidence)),
        evidence_labels=_dedupe(refined.evidence_labels + heuristic_item.evidence_labels)[:MAX_EVIDENCE_LABELS],
        warnings=_dedupe(refined.warnings),
    )


def _classifier_content(
    pdf_path: Path,
    page: ParsedPage,
    heuristic_item: DrawingInventoryItem,
) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                f"Classify drawing page {page.page_number}. Allowed primary_view_type values: "
                f"{', '.join(VIEW_TYPES)}.\n\n"
                "Return this JSON shape exactly:\n"
                '{"primary_view_type":"Section","detected_view_types":["Section"],"confidence":0.92,'
                '"sheet_title":"SECTION 1","drawing_number":"120.01",'
                '"evidence_labels":["SECTION 1"],"warnings":[]}\n\n'
                "Rules:\n"
                "- If a drawing shows vertical storey levels, cut lines, elevations, or a sectional slice, classify it as Section or Section & Elevation, not Floor Plan.\n"
                "- Only use Floor Plan when the page is a horizontal plan/layout view.\n"
                "- Use Unknown with low confidence when the page is too unclear.\n\n"
                "Heuristic guess:\n"
                f"{_item_summary(heuristic_item)}\n\n"
                "Embedded page text and labels:\n"
                f"{page.text[:MAX_CLASSIFIER_TEXT_CHARS] or '[No embedded text found]'}\n\n"
                "Labels:\n"
                f"{'; '.join(page.annotations[:MAX_CLASSIFIER_LABELS]) or '[No labels found]'}"
            ),
        }
    ]

    full_image = _safe_render_page_image(pdf_path, page.page_number)
    if full_image:
        content.append({"type": "text", "text": f"Page {page.page_number} full 150 DPI image:"})
        content.append(_image_block(full_image))

    for label, region in CROP_REGIONS:
        crop_image = _safe_render_page_crop(pdf_path, page.page_number, region)
        if not crop_image:
            continue
        content.append({"type": "text", "text": f"Page {page.page_number} {label} at higher detail:"})
        content.append(_image_block(crop_image))

    return content


def _safe_render_page_image(pdf_path: Path, page_number: int) -> str:
    try:
        image_base64 = render_page_image_base64(pdf_path, page_number, DRAWING_INVENTORY_IMAGE_DPI).strip()
    except Exception:
        logger.exception("Could not render inventory full image for page %s.", page_number)
        return ""

    if len(image_base64) > MAX_IMAGE_BASE64_CHARS_PER_REQUEST:
        logger.info("Skipping inventory full image for page %s because it exceeds image budget.", page_number)
        return ""
    return image_base64


def _safe_render_page_crop(
    pdf_path: Path,
    page_number: int,
    region: tuple[float, float, float, float],
) -> str:
    try:
        image_base64 = render_page_region_image_base64(
            pdf_path,
            page_number,
            DRAWING_INVENTORY_CROP_DPI,
            region,
        ).strip()
    except Exception:
        logger.exception("Could not render inventory crop for page %s.", page_number)
        return ""

    if len(image_base64) > MAX_IMAGE_BASE64_CHARS_PER_REQUEST:
        logger.info("Skipping inventory crop for page %s because it exceeds image budget.", page_number)
        return ""
    return image_base64


def _image_block(image_base64: str) -> dict[str, Any]:
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": image_base64,
        },
    }


def _parse_claude_inventory_response(response_text: str) -> ClaudeInventoryPage:
    json_text = _extract_json_object(response_text)
    try:
        if hasattr(ClaudeInventoryPage, "model_validate_json"):
            return ClaudeInventoryPage.model_validate_json(json_text)
        return ClaudeInventoryPage.parse_raw(json_text)
    except ValidationError:
        logger.exception("Claude drawing inventory response failed validation.")
        raise


def _extract_json_object(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("Claude inventory response did not contain a JSON object.")
    return stripped[start : end + 1]


def _choose_stronger_inventory_item(
    heuristic_item: DrawingInventoryItem,
    refined_item: DrawingInventoryItem,
) -> DrawingInventoryItem:
    if refined_item.primary_view_type == "Unknown" and heuristic_item.primary_view_type != "Unknown":
        return heuristic_item
    if refined_item.confidence >= heuristic_item.confidence:
        return refined_item
    if heuristic_item.confidence >= DRAWING_INVENTORY_CONFIDENCE_THRESHOLD:
        return heuristic_item
    return refined_item


def _needs_confirmation(item: DrawingInventoryItem) -> bool:
    return _needs_confirmation_score(item.primary_view_type, item.confidence)


def _needs_confirmation_score(view_type: DrawingViewType, confidence: float) -> bool:
    return view_type == "Unknown" or confidence < DRAWING_INVENTORY_CONFIDENCE_THRESHOLD


def _confidence_for_score(score: int, combined: bool = False) -> float:
    if score >= 9:
        return 0.95 if combined else 0.93
    if score >= 6:
        return 0.88
    if score >= 4:
        return 0.8
    if score >= 2:
        return 0.64
    return 0.42


def _top_scored_view(scores: dict[DrawingViewType, int]) -> tuple[DrawingViewType, int]:
    scored = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    view_type, score = scored[0]
    if score <= 0:
        return "Unknown", 0
    return view_type, score


def _detected_view_types(scores: dict[DrawingViewType, int]) -> list[DrawingViewType]:
    return [
        view_type
        for view_type, score in sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        if score > 0
    ][:3]


def _has_close_second_choice(scores: dict[DrawingViewType, int], primary_view_type: DrawingViewType) -> bool:
    if primary_view_type == "Section & Elevation":
        return False
    top_score = scores.get(primary_view_type, 0)
    if top_score <= 0:
        return False
    for view_type, score in scores.items():
        if view_type != primary_view_type and score > 0 and top_score - score <= 1:
            return True
    return False


def _evidence_for_pattern(pattern: str, lines: list[str]) -> str:
    for line in lines:
        if re.search(pattern, _normalize_for_match(line), flags=re.IGNORECASE):
            return line[:120]
    return ""


def _detect_sheet_title(lines: list[str], primary_view_type: DrawingViewType) -> str:
    for line in lines:
        normalized = _normalize_for_match(line)
        if len(line) <= 140 and _line_mentions_view_type(normalized, primary_view_type):
            return line
    for line in lines:
        if 8 <= len(line) <= 120 and any(keyword in line.upper() for keyword in ("PLAN", "SECTION", "ELEVATION", "DETAIL")):
            return line
    return ""


def _detect_drawing_number(lines: list[str]) -> str:
    joined = "\n".join(lines)
    explicit = re.search(
        r"\b(?:drawing|dwg)\s*(?:no\.?|number)?\s*[:#]?\s*([A-Z0-9_.-]{2,20})\b",
        joined,
        flags=re.IGNORECASE,
    )
    if explicit:
        return explicit.group(1)

    for line in lines:
        match = re.search(r"\b[A-Z]?\d{2,4}\.\d{1,3}[A-Z]?\b", line)
        if match:
            return match.group(0)
    return ""


def _line_mentions_view_type(normalized_line: str, view_type: DrawingViewType) -> bool:
    if view_type == "Unknown":
        return False
    if view_type == "Section & Elevation":
        return "section" in normalized_line or "elevation" in normalized_line
    return view_type.lower().replace("/general", "").lower() in normalized_line


def _valid_detected_views(
    detected_view_types: list[DrawingViewType],
    primary_view_type: DrawingViewType,
) -> list[DrawingViewType]:
    valid = [view_type for view_type in detected_view_types if view_type in VIEW_TYPES]
    if primary_view_type != "Unknown" and primary_view_type not in valid:
        valid.insert(0, primary_view_type)
    return _dedupe(valid)[:3]


def _item_summary(item: DrawingInventoryItem) -> str:
    return json.dumps(
        {
            "primary_view_type": item.primary_view_type,
            "detected_view_types": item.detected_view_types,
            "confidence": item.confidence,
            "sheet_title": item.sheet_title,
            "drawing_number": item.drawing_number,
            "evidence_labels": item.evidence_labels,
            "warnings": item.warnings,
        },
        ensure_ascii=True,
    )


def _clean_lines(text: str) -> list[str]:
    return [
        re.sub(r"\s+", " ", line).strip()
        for line in text.splitlines()
        if re.sub(r"\s+", " ", line).strip()
    ]


def _normalize_for_match(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("_", " ")).strip().lower()


def _dedupe(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = re.sub(r"\s+", " ", str(value)).strip()
        if not normalized or normalized in seen:
            continue
        deduped.append(normalized)
        seen.add(normalized)
    return deduped


def _report_progress(message: str, progress_callback: ProgressCallback | None) -> None:
    logger.info(message)
    if progress_callback is None:
        return
    try:
        progress_callback(message)
    except Exception:
        logger.exception("Inventory progress callback failed.")
