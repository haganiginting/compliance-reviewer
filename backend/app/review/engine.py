from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import ssl
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import certifi
import httpx
from anthropic import APIConnectionError, AsyncAnthropic, RateLimitError
from pydantic import ValidationError

try:
    import truststore
except ImportError:
    truststore = None

from app.config import (
    AGENCIES,
    CLAUDE_RATE_LIMIT_RETRY_SECONDS,
    CLAUDE_MODEL,
    FALLBACK_IMAGE_DPI,
    MAX_IMAGE_BASE64_CHARS_PER_REQUEST,
    MAX_IMAGES_PER_REVIEW_BATCH,
    MAX_RETRIEVED_CHUNKS_PER_CLAUDE_REQUEST,
    RAG_CHUNK_OVERLAP,
    RAG_CHUNK_SIZE,
    RETRIEVAL_LOG_DIR,
    retrieval_top_k_for_agency,
)
from app.pdf.inventory import build_heuristic_drawing_inventory
from app.pdf.models import DrawingInventory, ParsedPage, ParsedPdf
from app.pdf.parser import parse_pdf, render_page_image_base64
from app.rag.models import RetrievedChunk
from app.rag.retrieval import retrieve_chunks
from app.review.models import AgencyReview, ComplianceIssue, ComplianceReport, ReviewContext, ReviewSummary


PROMPTS_DIR = Path(__file__).with_name("prompts")
BASE_PROMPT_PATH = PROMPTS_DIR / "base_system_prompt.md"
MAX_PAGE_TEXT_CHARS = 1_500
MAX_LABELS_PER_PAGE = 30
MAX_CHUNK_CHARS = 1_200
MAX_QUERY_CHARS = 4_000
MAX_TRACE_QUERY_CHARS = 1_200
MAX_TRACE_CHUNK_CHARS = 1_000
MAX_INVENTORY_TEXT_CHARS = 250
MAX_INVENTORY_LABELS = 10
logger = logging.getLogger(__name__)
_CHROMA_RETRIEVAL_LOCK = threading.Lock()
_RETRIEVAL_TRACE_LOCK = threading.Lock()


class ReviewEngineError(RuntimeError):
    pass


ProgressCallback = Callable[[str], None]


@dataclass(frozen=True)
class PageInventoryItem:
    page_number: int
    text_excerpt: str
    labels: list[str]


@dataclass(frozen=True)
class PageReviewBatch:
    batch_number: int
    total_batches: int
    pages: list[ParsedPage]


AGENCY_PAGE_HINTS = {
    "bca": ("stair", "ramp", "barrier", "balustrade", "headroom", "access", "window", "structure"),
    "scdf": ("fire", "escape", "exit", "hose", "hydrant", "sprinkler", "compartment", "accessway"),
    "ura": ("setback", "boundary", "site", "gfa", "coverage", "height", "storey", "envelope"),
    "lta": ("road", "parking", "driveway", "vehicle", "access", "traffic", "car", "ramp"),
    "nparks": ("tree", "green", "landscape", "planting", "verge", "root", "canopy", "nparks"),
    "nea": ("bin", "refuse", "sanitary", "exhaust", "pollution", "noise", "toilet", "waste"),
    "pub": ("drain", "sewer", "water", "platform", "mrl", "mpl", "detention", "rain"),
}
DRAWING_TYPE_PAGE_HINTS = {
    "Floor Plan": ("plan", "room", "stair", "corridor", "door", "ramp"),
    "Site Plan": ("site", "boundary", "setback", "road", "tree", "drain"),
    "Section & Elevation": ("section", "elevation", "height", "level", "roof", "facade"),
    "Drainage": ("drain", "sewer", "water", "platform", "mrl", "mpl"),
    "Fire Safety": ("fire", "escape", "exit", "hydrant", "sprinkler", "hose"),
    "Mixed Set": (),
}
AGENCY_RETRIEVAL_TOPIC_HINTS = {
    "bca": (
        "barrier-free accessibility, accessible route, door clear width, ramp gradient, stair width, "
        "tread, riser, landing, handrail, guarding, headroom, lift or home lift, sanitary provision, "
        "light, ventilation, structural design notes, loading, and protection from falling"
    ),
    "scdf": (
        "means of escape, exit access, travel distance, exit width, fire compartmentation, fire engine "
        "accessway, dry or wet riser, hose reel, hydrant, sprinkler, fire lift, fire command centre, "
        "smoke control, refuge, and fire safety room/layout provisions"
    ),
    "ura": (
        "site boundary, setback, building height, storey count, envelope control, plot ratio, GFA, site "
        "coverage, road buffer, use planning, parking planning, attic, mezzanine, and development-control "
        "parameters"
    ),
    "lta": (
        "vehicle parking provision, driveway width, access point, road reserve, car park layout, ramp, "
        "turning radius, loading bay, bicycle parking, motorcycle parking, pedestrian/vehicle conflict, "
        "and traffic access provisions"
    ),
    "nparks": (
        "tree conservation, retained tree, tree protection zone, planting strip, greenery provision, "
        "green buffer, landscape area, skyrise greenery, roadside planting, root protection, and canopy "
        "or replacement planting"
    ),
    "nea": (
        "refuse storage, bin centre, refuse chute, sanitary provision, toilets, exhaust discharge, "
        "pollution control, noise, trade effluent, ventilation, public health, waste handling, and "
        "environmental health provisions"
    ),
    "pub": (
        "minimum platform level, flood protection level, crest level, drainage reserve, surface water "
        "drainage, detention or retention, sewer setback, sanitary drainage, water service, discharge "
        "point, invert level, and rainwater drainage provisions"
    ),
}


async def review_pdf(
    pdf_path: str | Path,
    trace_id: str | None = None,
    context: ReviewContext | None = None,
    progress_callback: ProgressCallback | None = None,
) -> ComplianceReport:
    api_key = _load_api_key()
    path = Path(pdf_path)
    review_context = context or ReviewContext()

    _report_progress("Parsing PDF", progress_callback)
    parsed_pdf = parse_pdf(path)
    _report_progress("Building page inventory", progress_callback)
    page_inventory = _build_page_inventory(parsed_pdf)
    if review_context.drawing_inventory is None:
        review_context = _context_with_inventory(
            review_context,
            build_heuristic_drawing_inventory(parsed_pdf),
        )

    http_client = httpx.AsyncClient(verify=_build_ssl_context())
    client = AsyncAnthropic(api_key=api_key, http_client=http_client)
    trace_path = _trace_path_for(trace_id)

    try:
        agency_reviews: list[AgencyReview] = []
        selected_agencies = tuple(review_context.selected_agencies)
        selected_agency_names = ", ".join(AGENCIES[code].name for code in selected_agencies)
        logger.info("Starting rate-limited reviews for: %s", selected_agency_names)
        _report_progress(f"Reviewing selected agencies: {selected_agency_names}", progress_callback)
        for agency_code in selected_agencies:
            agency_reviews.append(
                await _review_agency(
                    agency_code=agency_code,
                    pdf_path=path,
                    parsed_pdf=parsed_pdf,
                    page_inventory=page_inventory,
                    context=review_context,
                    client=client,
                    trace_path=trace_path,
                    progress_callback=progress_callback,
                )
            )
    finally:
        await http_client.aclose()
    _report_progress("Combining findings", progress_callback)

    return ComplianceReport(
        document=parsed_pdf.document,
        reviewed_at=datetime.now(timezone.utc).isoformat(),
        agencies=agency_reviews,
        summary=_build_summary(agency_reviews),
    )


async def _review_agency(
    agency_code: str,
    pdf_path: Path,
    parsed_pdf: ParsedPdf,
    page_inventory: list[PageInventoryItem],
    context: ReviewContext,
    client: AsyncAnthropic,
    trace_path: Path,
    progress_callback: ProgressCallback | None,
) -> AgencyReview:
    started_at = time.perf_counter()
    agency = AGENCIES[agency_code]
    top_k = retrieval_top_k_for_agency(agency_code)
    system_prompt = _load_system_prompt(agency_code)
    page_batches = _build_page_batches(
        agency_code=agency_code,
        pages=parsed_pdf.pages,
        inventory=page_inventory,
        context=context,
    )
    batch_reviews: list[AgencyReview] = []

    for batch in page_batches:
        selected_images = _select_batch_images(pdf_path, batch.pages)
        page_label = _format_batch_page_numbers([page.page_number for page in batch.pages])
        _report_progress(
            f"Reviewing {agency.name} batch {batch.batch_number}/{batch.total_batches}: pages {page_label}",
            progress_callback,
        )
        query = _build_retrieval_query(
            parsed_pdf=parsed_pdf,
            agency_code=agency_code,
            agency_name=agency.name,
            context=context,
            page_inventory=page_inventory,
            batch=batch,
        )
        logger.info(
            "%s: retrieving %s clauses for batch %s/%s pages %s",
            agency.name,
            top_k,
            batch.batch_number,
            batch.total_batches,
            page_label,
        )
        chunks = await asyncio.to_thread(_retrieve_chunks_threadsafe, agency_code, query, top_k)
        if not chunks:
            raise ReviewEngineError(
                f"No retrieved clauses found for {agency.name} batch pages {page_label}. "
                f"Run ingestion for {agency_code} before reviewing."
            )

        _write_retrieval_trace(
            trace_path=trace_path,
            agency_code=agency_code,
            context=context,
            top_k=top_k,
            query=query,
            chunks=chunks,
            batch=batch,
            selected_image_pages=sorted(selected_images),
        )

        logger.info(
            "%s: calling Claude for batch %s/%s with %s retrieved clauses and %s image(s)",
            agency.name,
            batch.batch_number,
            batch.total_batches,
            len(chunks),
            len(selected_images),
        )
        user_content = _build_user_content(
            agency_name=agency.name,
            pages=batch.pages,
            page_inventory=page_inventory,
            context=context,
            chunks=chunks,
            batch=batch,
            selected_images=selected_images,
        )
        batch_reviews.append(
            await _call_and_validate_agency_review(
                agency_name=agency.name,
                client=client,
                drawing_inventory=context.drawing_inventory,
                system_prompt=system_prompt,
                user_content=user_content,
                progress_callback=progress_callback,
            )
        )

    review = AgencyReview(
        agency=agency.name,
        issues=_deduplicate_issues(
            issue
            for batch_review in batch_reviews
            for issue in batch_review.issues
        ),
    )

    elapsed = time.perf_counter() - started_at
    logger.info("%s: finished in %.1fs with %s issues", agency.name, elapsed, len(review.issues))
    return review


async def _call_and_validate_agency_review(
    agency_name: str,
    client: AsyncAnthropic,
    drawing_inventory: DrawingInventory | None,
    system_prompt: str,
    user_content: list[dict[str, Any]],
    progress_callback: ProgressCallback | None,
) -> AgencyReview:
    response_text = await _call_claude(
        client=client,
        system_prompt=system_prompt,
        user_content=user_content,
        progress_callback=progress_callback,
    )

    try:
        review = _validate_agency_review(response_text, expected_agency=agency_name)
        _raise_for_drawing_view_conflicts(review, drawing_inventory)
        return review
    except (ValidationError, ValueError, json.JSONDecodeError) as first_error:
        logger.info("%s: retrying Claude response after validation error", agency_name)
        corrective_content = list(user_content)
        corrective_content.append(
            {
                "type": "text",
                "text": (
                    "Your previous response was not valid for the required schema. "
                    f"Validation error: {first_error}. Return JSON only in this exact shape: "
                    '{"agency":"'
                    + agency_name
                    + '","issues":[{"title":"...","severity":"Critical|Major|Advisory",'
                    '"description":"...","clause_reference":"...","drawing_location":"...",'
                    '"drawing_page_number":1,"drawing_view_type":"Section",'
                    '"suggested_resolution":"..."}]}. '
                    "Use null for drawing_page_number if the page cannot be identified. "
                    "Use the confirmed drawing inventory view type exactly for drawing_view_type. "
                    "Do not call a confirmed Section page a Floor Plan. "
                    "Use an empty issues list only if no "
                    "issue is supported by the retrieved clauses."
                ),
            }
        )
        retry_text = await _call_claude(
            client=client,
            system_prompt=system_prompt,
            user_content=corrective_content,
            progress_callback=progress_callback,
        )
        retry_review = _validate_agency_review(retry_text, expected_agency=agency_name)
        return _without_drawing_view_conflicts(retry_review, drawing_inventory)


def _retrieve_chunks_threadsafe(agency_code: str, query: str, top_k: int) -> list[RetrievedChunk]:
    # ChromaDB's local PersistentClient can fail during tenant setup when
    # multiple clients are initialized at the same time. Serialize retrieval
    # setup here, then keep the slower Claude review calls concurrent.
    with _CHROMA_RETRIEVAL_LOCK:
        try:
            return retrieve_chunks(
                agency_code=agency_code,
                query=query,
                top_k=top_k,
            )
        except Exception as exc:
            raise ReviewEngineError(
                f"Could not retrieve clauses for {agency_code.upper()} from the local Chroma database. "
                "Confirm ingestion completed for every active agency in app/config.py, then rerun the review."
            ) from exc


def _load_system_prompt(agency_code: str) -> str:
    prompt_parts = [BASE_PROMPT_PATH.read_text(encoding="utf-8").strip()]
    override_path = PROMPTS_DIR / f"{agency_code.lower()}_system_prompt.md"
    if override_path.exists():
        prompt_parts.append(override_path.read_text(encoding="utf-8").strip())
    return "\n\n".join(part for part in prompt_parts if part)


def _trace_path_for(trace_id: str | None) -> Path:
    if trace_id is None:
        trace_id = f"cli_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"
    safe_trace_id = re.sub(r"[^A-Za-z0-9._-]+", "_", trace_id).strip("._") or "review"
    RETRIEVAL_LOG_DIR.mkdir(parents=True, exist_ok=True)
    return RETRIEVAL_LOG_DIR / f"{safe_trace_id}.jsonl"


def _write_retrieval_trace(
    trace_path: Path,
    agency_code: str,
    context: ReviewContext,
    top_k: int,
    query: str,
    chunks: list[RetrievedChunk],
    batch: PageReviewBatch,
    selected_image_pages: list[int],
) -> None:
    trace_entry = {
        "logged_at": datetime.now(timezone.utc).isoformat(),
        "agency": agency_code.lower(),
        "selected_agencies": context.selected_agencies,
        "submission_type": context.submission_type,
        "drawing_type": context.drawing_type,
        "batch_number": batch.batch_number,
        "total_batches": batch.total_batches,
        "page_numbers": [page.page_number for page in batch.pages],
        "page_label": _format_batch_page_numbers([page.page_number for page in batch.pages]),
        "selected_image_pages": selected_image_pages,
        "top_k": top_k,
        "rag_chunk_size": RAG_CHUNK_SIZE,
        "rag_chunk_overlap": RAG_CHUNK_OVERLAP,
        "query_excerpt": query[:MAX_TRACE_QUERY_CHARS],
        "retrieved_chunks": [
            {
                "source_filename": chunk.source_filename,
                "page_number": chunk.page_number,
                "section_title": chunk.section_title,
                "score": chunk.score,
                "text_excerpt": chunk.text[:MAX_TRACE_CHUNK_CHARS],
            }
            for chunk in chunks
        ],
        "drawing_inventory": _drawing_inventory_trace(context.drawing_inventory),
    }
    with _RETRIEVAL_TRACE_LOCK:
        with trace_path.open("a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(trace_entry, ensure_ascii=False) + "\n")


def _drawing_inventory_trace(drawing_inventory: DrawingInventory | None) -> list[dict[str, Any]]:
    if drawing_inventory is None:
        return []
    return [
        {
            "page_number": item.page_number,
            "primary_view_type": item.primary_view_type,
            "detected_view_types": item.detected_view_types,
            "confidence": item.confidence,
            "sheet_title": item.sheet_title,
            "drawing_number": item.drawing_number,
            "warnings": item.warnings,
        }
        for item in drawing_inventory.pages
    ]


async def _call_claude(
    client: AsyncAnthropic,
    system_prompt: str,
    user_content: list[dict[str, Any]],
    progress_callback: ProgressCallback | None,
) -> str:
    try:
        response = await client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=3_000,
            temperature=0,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
        )
    except APIConnectionError as exc:
        raise ReviewEngineError(_anthropic_connection_error_message(exc)) from exc
    except RateLimitError as exc:
        _report_progress(
            f"Anthropic rate limit reached. Waiting {CLAUDE_RATE_LIMIT_RETRY_SECONDS} seconds, then retrying once.",
            progress_callback,
        )
        await asyncio.sleep(CLAUDE_RATE_LIMIT_RETRY_SECONDS)
        try:
            response = await client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=3_000,
                temperature=0,
                system=system_prompt,
                messages=[{"role": "user", "content": user_content}],
            )
        except RateLimitError as retry_exc:
            raise ReviewEngineError(_anthropic_rate_limit_error_message(retry_exc)) from retry_exc
    text_parts: list[str] = []
    for block in response.content:
        text = getattr(block, "text", None)
        if text:
            text_parts.append(text)
    return "\n".join(text_parts).strip()


def _anthropic_connection_error_message(exc: APIConnectionError) -> str:
    error_text = str(exc)
    cause = exc.__cause__
    while cause is not None:
        error_text = f"{error_text} {cause}"
        cause = cause.__cause__

    if "CERTIFICATE_VERIFY_FAILED" in error_text or "certificate verify failed" in error_text.lower():
        return (
            "Could not securely connect to Anthropic because Python could not verify the HTTPS certificate. "
            "Run `pip install -r requirements.txt` inside the backend virtual environment so Python can use "
            "the Mac certificate store through truststore, then restart the backend and try again."
        )

    return (
        "Could not connect to Anthropic. Check that your internet connection is working, then try the review again."
    )


def _anthropic_rate_limit_error_message(exc: RateLimitError) -> str:
    return (
        "Anthropic rate-limited this review because the drawing set is still too large for the current "
        "token-per-minute limit after one retry. Wait a few minutes, then try again. If it repeats, "
        "temporarily review fewer active agencies in app/config.py or use a smaller PDF subset."
    )


def _build_ssl_context() -> ssl.SSLContext:
    if truststore is not None:
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

    return ssl.create_default_context(cafile=certifi.where())


def _build_user_content(
    agency_name: str,
    pages: list[ParsedPage],
    page_inventory: list[PageInventoryItem],
    context: ReviewContext,
    chunks: list[RetrievedChunk],
    batch: PageReviewBatch,
    selected_images: dict[int, str],
) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                f"Review this drawing PDF for {agency_name} compliance only.\n\n"
                "This is a batched review for a larger drawing set. Review only the detailed pages "
                "and images in this batch, but use the full page inventory and user context to orient "
                "your page selection. Do not invent issues from pages or clauses that are not shown.\n\n"
                "Hard drawing-scope rule: base every finding on uploaded drawing evidence only. "
                "The evidence is limited to the uploaded pages, labels, text, and images shown for this review, "
                "plus the selected agencies, drawing type, submission type, user description, and review notes. "
                "Do not comment on missing specifications, forms, schedules, reports, calculations, material "
                "specifications, title blocks, signatures, complete drawing sets, or authority-submission "
                "documentation unless those materials were actually uploaded and the submission type makes "
                "that check in scope. Treat drawing type and submission type as hard scope controls.\n\n"
                "Return this JSON shape exactly:\n"
                "{\n"
                f'  "agency": "{agency_name}",\n'
                '  "issues": [\n'
                "    {\n"
                '      "title": "short issue title",\n'
                '      "severity": "Critical|Major|Advisory",\n'
                '      "description": "what appears non-compliant and why",\n'
                '      "clause_reference": "source filename, page, and clause/section wording",\n'
                '      "drawing_location": "drawing page and visible location/label",\n'
                '      "drawing_page_number": 1,\n'
                '      "drawing_view_type": "Floor Plan|Site Plan|Section|Elevation|Section & Elevation|Detail|Schedule/General|Unknown",\n'
                '      "suggested_resolution": "practical next action"\n'
                "    }\n"
                "  ]\n"
                "}\n\n"
                "Set drawing_page_number to the 1-based PDF page number when the drawing location identifies "
                "a page. Use null only when the page cannot be identified. Set drawing_view_type to the "
                "confirmed view type for that page from the drawing inventory. If page 9 is confirmed as "
                "Section, do not call it a Floor Plan in the title, description, location, or drawing_view_type.\n\n"
                "User upload context:\n"
                f"{_format_review_context(context)}\n\n"
                "Confirmed drawing inventory:\n"
                f"{_format_confirmed_drawing_inventory(context.drawing_inventory)}\n\n"
                "Retrieved clauses:\n"
                f"{_format_retrieved_chunks(chunks[:MAX_RETRIEVED_CHUNKS_PER_CLAUDE_REQUEST])}\n\n"
                "Full page inventory:\n"
                f"{_format_page_inventory(page_inventory)}\n\n"
                f"Current batch: {batch.batch_number}/{batch.total_batches}, pages "
                f"{_format_batch_page_numbers([page.page_number for page in pages])}\n\n"
                "Drawing page text and labels:\n"
                f"{_format_pages_for_text(pages)}"
            ),
        }
    ]

    for page in pages:
        image_base64 = selected_images.get(page.page_number)
        if not _has_image_payload(image_base64):
            continue
        content.append({"type": "text", "text": f"Drawing page {page.page_number} PNG:"})
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": image_base64,
                },
            }
        )

    return content


def _build_retrieval_query(
    parsed_pdf: ParsedPdf,
    agency_code: str,
    agency_name: str,
    context: ReviewContext,
    page_inventory: list[PageInventoryItem],
    batch: PageReviewBatch | None = None,
) -> str:
    parts = [
        f"{agency_name} compliance review for architectural drawing.",
        f"Drawing type: {context.drawing_type}",
        f"Submission type: {context.submission_type}",
        f"Selected agencies for this review: {_format_selected_agency_names(context)}",
        f"User description: {context.description or '[Not provided]'}",
        f"Review notes: {context.review_notes or '[Not provided]'}",
        f"Document: {parsed_pdf.document.filename}, {parsed_pdf.document.page_count} pages.",
    ]

    topic_hint = AGENCY_RETRIEVAL_TOPIC_HINTS.get(agency_code)
    if topic_hint:
        parts.append(
            f"{agency_name} drawing-assessable topics to retrieve when visible on the current pages: "
            f"{topic_hint}."
        )

    if batch is not None:
        parts.append(
            f"Current review batch pages: {_format_batch_page_numbers([page.page_number for page in batch.pages])}. "
            "Prioritize clauses relevant to these current pages."
        )
        for page in batch.pages:
            labels = " ".join(page.annotations[:MAX_LABELS_PER_PAGE])
            parts.append(
                f"Current page {page.page_number} text:\n{page.text[:MAX_PAGE_TEXT_CHARS]}\n"
                f"Current page {page.page_number} labels:\n{labels}"
            )

    parts.append("Full drawing page inventory for orientation:")
    for item in page_inventory:
        labels = " ".join(item.labels[:MAX_LABELS_PER_PAGE])
        parts.append(f"Page {item.page_number}: {item.text_excerpt}\nLabels: {labels}")
    return "\n\n".join(parts)[:MAX_QUERY_CHARS]


def _build_page_inventory(parsed_pdf: ParsedPdf) -> list[PageInventoryItem]:
    inventory: list[PageInventoryItem] = []
    for page in parsed_pdf.pages:
        inventory.append(
            PageInventoryItem(
                page_number=page.page_number,
                text_excerpt=page.text[:MAX_INVENTORY_TEXT_CHARS],
                labels=page.annotations[:MAX_INVENTORY_LABELS],
            )
        )
    return inventory


def _build_page_batches(
    agency_code: str,
    pages: list[ParsedPage],
    inventory: list[PageInventoryItem],
    context: ReviewContext,
) -> list[PageReviewBatch]:
    page_by_number = {page.page_number: page for page in pages}
    ranked_page_numbers = _rank_page_numbers_for_agency(agency_code, inventory, context)
    ranked_pages = [page_by_number[page_number] for page_number in ranked_page_numbers if page_number in page_by_number]
    if not ranked_pages:
        ranked_pages = pages

    chunk_size = max(1, MAX_IMAGES_PER_REVIEW_BATCH)
    page_groups = [
        ranked_pages[index : index + chunk_size]
        for index in range(0, len(ranked_pages), chunk_size)
    ]
    total_batches = len(page_groups)
    return [
        PageReviewBatch(
            batch_number=index,
            total_batches=total_batches,
            pages=page_group,
        )
        for index, page_group in enumerate(page_groups, start=1)
    ]


def _rank_page_numbers_for_agency(
    agency_code: str,
    inventory: list[PageInventoryItem],
    context: ReviewContext,
) -> list[int]:
    context_text = f"{context.drawing_type} {context.description} {context.review_notes}".lower()
    agency_hints = AGENCY_PAGE_HINTS.get(agency_code, ())
    drawing_hints = DRAWING_TYPE_PAGE_HINTS.get(context.drawing_type, ())
    scored_pages: list[tuple[int, int]] = []

    for item in inventory:
        page_text = f"{item.text_excerpt} {' '.join(item.labels)}".lower()
        score = 0
        score += sum(3 for hint in agency_hints if hint in page_text)
        score += sum(2 for hint in drawing_hints if hint in page_text)
        score += sum(1 for hint in agency_hints if hint in context_text)
        scored_pages.append((score, item.page_number))

    return [
        page_number
        for score, page_number in sorted(scored_pages, key=lambda scored: (-scored[0], scored[1]))
    ]


def _select_batch_images(pdf_path: Path, pages: list[ParsedPage]) -> dict[int, str]:
    selected_images: dict[int, str] = {}
    total_chars = 0

    for page in pages[:MAX_IMAGES_PER_REVIEW_BATCH]:
        image_base64 = _validated_page_image_base64(pdf_path, page)
        if not _has_image_payload(image_base64):
            logger.info("Skipping page %s image because rendering produced an empty image payload.", page.page_number)
            continue

        if len(image_base64) > MAX_IMAGE_BASE64_CHARS_PER_REQUEST:
            image_base64 = _render_fallback_page_image_base64(pdf_path, page.page_number)
            if not _has_image_payload(image_base64):
                logger.info(
                    "Skipping page %s image because fallback rendering produced an empty image payload.",
                    page.page_number,
                )
                continue

        if total_chars + len(image_base64) > MAX_IMAGE_BASE64_CHARS_PER_REQUEST:
            fallback_base64 = _render_fallback_page_image_base64(pdf_path, page.page_number)
            if not _has_image_payload(fallback_base64):
                logger.info(
                    "Skipping page %s image because fallback rendering produced an empty image payload.",
                    page.page_number,
                )
                continue
            if total_chars + len(fallback_base64) > MAX_IMAGE_BASE64_CHARS_PER_REQUEST:
                logger.info(
                    "Skipping page %s image because it still exceeds the request image budget at %s DPI.",
                    page.page_number,
                    FALLBACK_IMAGE_DPI,
                )
                continue
            image_base64 = fallback_base64

        selected_images[page.page_number] = image_base64
        total_chars += len(image_base64)

    return selected_images


def _validated_page_image_base64(pdf_path: Path, page: ParsedPage) -> str:
    if _has_image_payload(page.image_base64):
        return page.image_base64.strip()

    fallback_image_base64 = _render_fallback_page_image_base64(pdf_path, page.page_number)
    if _has_image_payload(fallback_image_base64):
        logger.info("Using fallback image payload for page %s because parsed rendering was empty.", page.page_number)
        return fallback_image_base64

    logger.info("Page %s has an empty parsed image payload and empty fallback render.", page.page_number)
    return ""


def _render_fallback_page_image_base64(pdf_path: Path, page_number: int) -> str:
    try:
        return render_page_image_base64(pdf_path, page_number, FALLBACK_IMAGE_DPI).strip()
    except Exception:
        logger.exception("Could not render fallback image for page %s.", page_number)
        return ""


def _has_image_payload(image_base64: str | None) -> bool:
    return bool(image_base64 and image_base64.strip())


def _format_retrieved_chunks(chunks: list[RetrievedChunk]) -> str:
    formatted: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        section = f", section: {chunk.section_title}" if chunk.section_title else ""
        formatted.append(
            f"[{index}] Agency: {chunk.agency.upper()}, source: {chunk.source_filename}, "
            f"page: {chunk.page_number}{section}\n"
            f"{chunk.text[:MAX_CHUNK_CHARS]}"
        )
    return "\n\n".join(formatted)


def _format_review_context(context: ReviewContext) -> str:
    return (
        f"Drawing type: {context.drawing_type}\n"
        f"Submission type: {context.submission_type}\n"
        f"Selected agencies: {_format_selected_agency_names(context)}\n"
        f"Description: {context.description or '[Not provided]'}\n"
        f"Review notes: {context.review_notes or '[Not provided]'}\n"
        f"Submission guidance: {_submission_guidance(context)}"
    )


def _format_selected_agency_names(context: ReviewContext) -> str:
    return ", ".join(AGENCIES[code].name for code in context.selected_agencies)


def _submission_guidance(context: ReviewContext) -> str:
    if context.submission_type == "Authority Submission":
        return (
            "Authority Submission mode is active. You may flag authority-submission drawing-format, "
            "documentation, title-block, scale, north-arrow, and submission-completeness issues only "
            "when they are directly supported by the retrieved clauses and uploaded drawing evidence."
        )

    return (
        "Design mode is active. Perform design-compliance checks, but do not flag authority-submission "
        "drawing-format or documentation-only issues such as missing north arrow, missing scale bar, "
        "title-block completeness, signatures, submission forms, or administrative drawing-set "
        "completeness unless the issue is also a clause-supported design-compliance problem visible in "
        "the uploaded drawing evidence."
    )


def _format_page_inventory(page_inventory: list[PageInventoryItem]) -> str:
    formatted: list[str] = []
    for item in page_inventory:
        labels = "; ".join(item.labels[:MAX_INVENTORY_LABELS])
        formatted.append(
            f"Page {item.page_number}: {item.text_excerpt or '[No embedded text found]'}\n"
            f"Labels: {labels or '[No labels or annotations found]'}"
        )
    return "\n\n".join(formatted)


def _format_confirmed_drawing_inventory(drawing_inventory: DrawingInventory | None) -> str:
    if drawing_inventory is None or not drawing_inventory.pages:
        return "[No confirmed drawing inventory available.]"

    formatted: list[str] = []
    for item in drawing_inventory.pages:
        detected = ", ".join(item.detected_view_types) if item.detected_view_types else item.primary_view_type
        evidence = "; ".join(item.evidence_labels[:MAX_INVENTORY_LABELS]) or "[No evidence labels]"
        warnings = "; ".join(item.warnings) or "None"
        title = item.sheet_title or "[No sheet title]"
        drawing_number = item.drawing_number or "[No drawing number]"
        formatted.append(
            f"Page {item.page_number}: confirmed view type: {item.primary_view_type}; "
            f"detected view types: {detected}; confidence: {item.confidence:.2f}; "
            f"sheet title: {title}; drawing number: {drawing_number}; "
            f"evidence: {evidence}; warnings: {warnings}"
        )
    return "\n".join(formatted)


def _format_pages_for_text(pages: list[ParsedPage]) -> str:
    formatted: list[str] = []
    for page in pages:
        labels = "\n".join(f"- {label}" for label in page.annotations[:MAX_LABELS_PER_PAGE])
        formatted.append(
            f"Page {page.page_number}\n"
            f"Text:\n{page.text[:MAX_PAGE_TEXT_CHARS] or '[No embedded text found]'}\n"
            f"Labels/annotations:\n{labels or '[No labels or annotations found]'}"
        )
    return "\n\n".join(formatted)


def _format_batch_page_numbers(page_numbers: list[int]) -> str:
    if not page_numbers:
        return "none"

    sorted_pages = sorted(page_numbers)
    ranges: list[str] = []
    range_start = sorted_pages[0]
    previous = sorted_pages[0]

    for page_number in sorted_pages[1:]:
        if page_number == previous + 1:
            previous = page_number
            continue
        ranges.append(_format_page_range(range_start, previous))
        range_start = page_number
        previous = page_number

    ranges.append(_format_page_range(range_start, previous))
    return ", ".join(ranges)


def _format_page_range(start: int, end: int) -> str:
    if start == end:
        return str(start)
    return f"{start}-{end}"


def _validate_agency_review(response_text: str, expected_agency: str) -> AgencyReview:
    json_text = _extract_json_object(response_text)
    if hasattr(AgencyReview, "model_validate_json"):
        review = AgencyReview.model_validate_json(json_text)
    else:
        review = AgencyReview.parse_raw(json_text)

    if review.agency != expected_agency:
        raise ValueError(f"Expected agency '{expected_agency}', got '{review.agency}'.")
    return review


def _raise_for_drawing_view_conflicts(
    review: AgencyReview,
    drawing_inventory: DrawingInventory | None,
) -> None:
    conflicts = _drawing_view_conflicts(review, drawing_inventory)
    if conflicts:
        raise ValueError("Drawing inventory conflicts: " + " ".join(conflicts))


def _without_drawing_view_conflicts(
    review: AgencyReview,
    drawing_inventory: DrawingInventory | None,
) -> AgencyReview:
    if drawing_inventory is None or not drawing_inventory.pages:
        return review

    valid_issues: list[ComplianceIssue] = []
    for issue in review.issues:
        conflicts = _issue_drawing_view_conflicts(issue, drawing_inventory)
        if conflicts:
            logger.info(
                "Discarding issue after drawing-view consistency retry: %s (%s)",
                issue.title,
                "; ".join(conflicts),
            )
            continue
        valid_issues.append(issue)

    return AgencyReview(agency=review.agency, issues=valid_issues)


def _drawing_view_conflicts(
    review: AgencyReview,
    drawing_inventory: DrawingInventory | None,
) -> list[str]:
    if drawing_inventory is None or not drawing_inventory.pages:
        return []

    conflicts: list[str] = []
    for issue in review.issues:
        conflicts.extend(_issue_drawing_view_conflicts(issue, drawing_inventory))
    return conflicts


def _issue_drawing_view_conflicts(
    issue: ComplianceIssue,
    drawing_inventory: DrawingInventory,
) -> list[str]:
    page_number = issue.drawing_page_number or _page_number_from_location(issue.drawing_location)
    if page_number is None:
        return []

    confirmed_view = _confirmed_view_type_for_page(drawing_inventory, page_number)
    if confirmed_view is None or confirmed_view == "Unknown":
        return []

    conflicts: list[str] = []
    if issue.drawing_view_type is None:
        conflicts.append(
            f"'{issue.title}' is missing drawing_view_type for page {page_number}, confirmed as {confirmed_view}."
        )
    elif not _view_types_compatible(issue.drawing_view_type, confirmed_view):
        conflicts.append(
            f"'{issue.title}' uses drawing_view_type {issue.drawing_view_type} for page {page_number}, "
            f"but inventory confirms {confirmed_view}."
        )

    location_text = f"{issue.title} {issue.drawing_location}".lower()
    if confirmed_view != "Floor Plan" and re.search(r"\bfloor\s+plans?\b", location_text):
        conflicts.append(
            f"'{issue.title}' calls page {page_number} a floor plan, but inventory confirms {confirmed_view}."
        )

    return conflicts


def _confirmed_view_type_for_page(
    drawing_inventory: DrawingInventory,
    page_number: int,
) -> str | None:
    for item in drawing_inventory.pages:
        if item.page_number == page_number:
            return item.primary_view_type
    return None


def _view_types_compatible(issue_view_type: str, confirmed_view_type: str) -> bool:
    if issue_view_type == confirmed_view_type:
        return True
    compatible_sets = [
        {"Section", "Elevation", "Section & Elevation"},
    ]
    return any(issue_view_type in group and confirmed_view_type in group for group in compatible_sets)


def _page_number_from_location(location: str) -> int | None:
    match = re.search(r"\b(?:page|pg\.?|p\.)\s*#?\s*(\d+)\b", str(location), flags=re.IGNORECASE)
    if match is None:
        return None
    page_number = int(match.group(1))
    if page_number < 1:
        return None
    return page_number


def _extract_json_object(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        raise ValueError("Claude returned an empty response.")

    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("Claude response did not contain a JSON object.")
    return stripped[start : end + 1]


def _build_summary(agency_reviews: list[AgencyReview]) -> ReviewSummary:
    by_agency = {review.agency: len(review.issues) for review in agency_reviews}
    by_severity = {"Critical": 0, "Major": 0, "Advisory": 0}

    for review in agency_reviews:
        for issue in review.issues:
            by_severity[issue.severity] += 1

    return ReviewSummary(
        total_issues=sum(by_agency.values()),
        by_agency=by_agency,
        by_severity=by_severity,
    )


def _deduplicate_issues(issues: Iterable[ComplianceIssue]) -> list[ComplianceIssue]:
    unique_issues: list[ComplianceIssue] = []
    seen_keys: set[str] = set()

    for issue in issues:
        key = _issue_exact_key(issue)
        if key in seen_keys:
            continue
        if any(_issues_are_near_duplicates(issue, existing) for existing in unique_issues):
            continue
        unique_issues.append(issue)
        seen_keys.add(key)

    return unique_issues


def _issue_exact_key(issue: ComplianceIssue) -> str:
    return "|".join(
        [
            issue.severity,
            _normalize_for_compare(issue.clause_reference),
            _normalize_for_compare(issue.drawing_location),
            _normalize_for_compare(issue.title),
        ]
    )


def _issues_are_near_duplicates(first: ComplianceIssue, second: ComplianceIssue) -> bool:
    if first.severity != second.severity:
        return False

    same_clause = _normalize_for_compare(first.clause_reference) == _normalize_for_compare(second.clause_reference)
    same_location = _normalize_for_compare(first.drawing_location) == _normalize_for_compare(second.drawing_location)
    title_overlap = _token_overlap(first.title, second.title)
    description_overlap = _token_overlap(first.description, second.description)

    return (same_clause and title_overlap >= 0.55) or (same_location and description_overlap >= 0.65)


def _token_overlap(first: str, second: str) -> float:
    first_tokens = _token_set(first)
    second_tokens = _token_set(second)
    if not first_tokens or not second_tokens:
        return 0
    return len(first_tokens & second_tokens) / min(len(first_tokens), len(second_tokens))


def _token_set(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value.lower())
        if len(token) > 2
    }


def _normalize_for_compare(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def _report_progress(message: str, progress_callback: ProgressCallback | None) -> None:
    logger.info(message)
    if progress_callback is None:
        return
    try:
        progress_callback(message)
    except Exception:
        logger.exception("Review progress callback failed.")


def _context_with_inventory(context: ReviewContext, drawing_inventory: DrawingInventory) -> ReviewContext:
    if hasattr(context, "model_copy"):
        return context.model_copy(update={"drawing_inventory": drawing_inventory})
    return context.copy(update={"drawing_inventory": drawing_inventory})


def _load_api_key() -> str:
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key or api_key == "your_key_here":
        raise ReviewEngineError(
            "ANTHROPIC_API_KEY is missing. Copy .env.example to .env and paste your Anthropic API key "
            "before running the review engine. The key will stay local and git-ignored."
        )
    return api_key
