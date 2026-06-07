from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from anthropic import AsyncAnthropic
from pydantic import ValidationError

from app.config import AGENCIES, ACTIVE_AGENCY_CODES, CLAUDE_MODEL
from app.pdf.models import ParsedPage, ParsedPdf
from app.pdf.parser import parse_pdf
from app.rag.models import RetrievedChunk
from app.rag.retrieval import retrieve_chunks
from app.review.models import AgencyReview, ComplianceReport, ReviewSummary


PROMPT_PATH = Path(__file__).with_name("system_prompt.md")
RETRIEVAL_TOP_K = 5
MAX_IMAGE_BASE64_CHARS = 18_000_000
MAX_PAGE_TEXT_CHARS = 4_000
MAX_LABELS_PER_PAGE = 60
MAX_CHUNK_CHARS = 2_500
MAX_QUERY_CHARS = 6_000
logger = logging.getLogger(__name__)
_CHROMA_RETRIEVAL_LOCK = threading.Lock()


class ReviewEngineError(RuntimeError):
    pass


async def review_pdf(pdf_path: str | Path) -> ComplianceReport:
    api_key = _load_api_key()
    parsed_pdf = parse_pdf(pdf_path)
    _ensure_payload_size(parsed_pdf)

    client = AsyncAnthropic(api_key=api_key)
    system_prompt = PROMPT_PATH.read_text(encoding="utf-8")

    # Each agency review performs its own retrieval and Claude request. Running
    # them concurrently overlaps local retrieval and network wait time, so the
    # CLI returns roughly as fast as the slowest active agency rather than the
    # sum of each agency's review time.
    logger.info("Starting concurrent reviews for: %s", ", ".join(code.upper() for code in ACTIVE_AGENCY_CODES))
    agency_tasks = [
        _review_agency(
            agency_code=agency_code,
            parsed_pdf=parsed_pdf,
            client=client,
            system_prompt=system_prompt,
        )
        for agency_code in ACTIVE_AGENCY_CODES
    ]
    agency_reviews = await asyncio.gather(*agency_tasks)

    return ComplianceReport(
        document=parsed_pdf.document,
        reviewed_at=datetime.now(timezone.utc).isoformat(),
        agencies=agency_reviews,
        summary=_build_summary(agency_reviews),
    )


async def _review_agency(
    agency_code: str,
    parsed_pdf: ParsedPdf,
    client: AsyncAnthropic,
    system_prompt: str,
) -> AgencyReview:
    started_at = time.perf_counter()
    agency = AGENCIES[agency_code]
    query = _build_retrieval_query(parsed_pdf, agency.name)
    logger.info("%s: retrieving clauses", agency.name)
    chunks = await asyncio.to_thread(_retrieve_chunks_threadsafe, agency_code, query)
    if not chunks:
        raise ReviewEngineError(
            f"No retrieved clauses found for {agency.name}. Run ingestion for {agency_code} before reviewing."
        )

    logger.info("%s: calling Claude with %s retrieved clauses", agency.name, len(chunks))
    user_content = _build_user_content(
        agency_name=agency.name,
        parsed_pdf=parsed_pdf,
        chunks=chunks,
    )
    response_text = await _call_claude(
        client=client,
        system_prompt=system_prompt,
        user_content=user_content,
    )

    try:
        review = _validate_agency_review(response_text, expected_agency=agency.name)
    except (ValidationError, ValueError, json.JSONDecodeError) as first_error:
        logger.info("%s: retrying Claude response after validation error", agency.name)
        corrective_content = list(user_content)
        corrective_content.append(
            {
                "type": "text",
                "text": (
                    "Your previous response was not valid for the required schema. "
                    f"Validation error: {first_error}. Return JSON only in this exact shape: "
                    '{"agency":"'
                    + agency.name
                    + '","issues":[{"title":"...","severity":"Critical|Major|Advisory",'
                    '"description":"...","clause_reference":"...","drawing_location":"...",'
                    '"suggested_resolution":"..."}]}. Use an empty issues list only if no '
                    "issue is supported by the retrieved clauses."
                ),
            }
        )
        retry_text = await _call_claude(
            client=client,
            system_prompt=system_prompt,
            user_content=corrective_content,
        )
        review = _validate_agency_review(retry_text, expected_agency=agency.name)

    elapsed = time.perf_counter() - started_at
    logger.info("%s: finished in %.1fs with %s issues", agency.name, elapsed, len(review.issues))
    return review


def _retrieve_chunks_threadsafe(agency_code: str, query: str) -> list[RetrievedChunk]:
    # ChromaDB's local PersistentClient can fail during tenant setup when
    # multiple clients are initialized at the same time. Serialize retrieval
    # setup here, then keep the slower Claude review calls concurrent.
    with _CHROMA_RETRIEVAL_LOCK:
        try:
            return retrieve_chunks(
                agency_code=agency_code,
                query=query,
                top_k=RETRIEVAL_TOP_K,
            )
        except Exception as exc:
            raise ReviewEngineError(
                f"Could not retrieve clauses for {agency_code.upper()} from the local Chroma database. "
                "Confirm ingestion completed for every active agency in app/config.py, then rerun the review."
            ) from exc


async def _call_claude(
    client: AsyncAnthropic,
    system_prompt: str,
    user_content: list[dict[str, Any]],
) -> str:
    response = await client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4_000,
        temperature=0,
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}],
    )
    text_parts: list[str] = []
    for block in response.content:
        text = getattr(block, "text", None)
        if text:
            text_parts.append(text)
    return "\n".join(text_parts).strip()


def _build_user_content(
    agency_name: str,
    parsed_pdf: ParsedPdf,
    chunks: list[RetrievedChunk],
) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                f"Review this drawing PDF for {agency_name} compliance only.\n\n"
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
                '      "suggested_resolution": "practical next action"\n'
                "    }\n"
                "  ]\n"
                "}\n\n"
                "Retrieved clauses:\n"
                f"{_format_retrieved_chunks(chunks)}\n\n"
                "Drawing page text and labels:\n"
                f"{_format_pages_for_text(parsed_pdf.pages)}"
            ),
        }
    ]

    for page in parsed_pdf.pages:
        content.append({"type": "text", "text": f"Drawing page {page.page_number} PNG:"})
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": page.image_base64,
                },
            }
        )

    return content


def _build_retrieval_query(parsed_pdf: ParsedPdf, agency_name: str) -> str:
    parts = [f"{agency_name} compliance review for architectural drawing."]
    for page in parsed_pdf.pages:
        labels = " ".join(page.annotations[:MAX_LABELS_PER_PAGE])
        page_text = page.text[:MAX_PAGE_TEXT_CHARS]
        parts.append(f"Page {page.page_number}: {page_text}\nLabels: {labels}")
    return "\n\n".join(parts)[:MAX_QUERY_CHARS]


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


def _validate_agency_review(response_text: str, expected_agency: str) -> AgencyReview:
    json_text = _extract_json_object(response_text)
    if hasattr(AgencyReview, "model_validate_json"):
        review = AgencyReview.model_validate_json(json_text)
    else:
        review = AgencyReview.parse_raw(json_text)

    if review.agency != expected_agency:
        raise ValueError(f"Expected agency '{expected_agency}', got '{review.agency}'.")
    return review


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


def _ensure_payload_size(parsed_pdf: ParsedPdf) -> None:
    total_image_chars = sum(len(page.image_base64) for page in parsed_pdf.pages)
    if total_image_chars > MAX_IMAGE_BASE64_CHARS:
        approx_mb = total_image_chars * 3 / 4 / 1_000_000
        raise ReviewEngineError(
            "The rendered drawing images are too large for a single Claude review request "
            f"({approx_mb:.1f} MB of PNG data). Try a smaller PDF or split the drawing into fewer pages."
        )


def _load_api_key() -> str:
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key or api_key == "your_key_here":
        raise ReviewEngineError(
            "ANTHROPIC_API_KEY is missing. Copy .env.example to .env and paste your Anthropic API key "
            "before running the review engine. The key will stay local and git-ignored."
        )
    return api_key
