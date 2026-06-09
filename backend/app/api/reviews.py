from __future__ import annotations

import logging
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

import httpx
from anthropic import AsyncAnthropic
from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ValidationError

from app.config import UPLOADS_DIR
from app.export import render_review_pdf
from app.pdf.inventory import build_drawing_inventory, inventory_needs_confirmation
from app.pdf.models import DrawingInventory
from app.pdf.parser import parse_pdf, render_page_image_png_bytes
from app.review.engine import ReviewEngineError, _build_ssl_context, _load_api_key, review_pdf
from app.review.models import ReviewContext
from app.storage import (
    create_review,
    get_review_inventory,
    get_review,
    list_reviews,
    mark_review_done,
    mark_review_error,
    mark_review_progress,
    resolve_review_upload_path,
    update_review_inventory,
)


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/reviews", tags=["reviews"])


class CreateReviewResponse(BaseModel):
    review_id: str


class ReviewListItem(BaseModel):
    id: str
    filename: str
    created_at: str
    drawing_type: str
    description: str
    review_notes: str
    selected_agencies: list[str]
    submission_type: str
    status_message: str
    inventory_status: str
    total_issues: int
    status: str


class ReviewDetailResponse(BaseModel):
    id: str
    filename: str
    created_at: str
    updated_at: str
    status: str
    drawing_type: str
    description: str
    review_notes: str
    selected_agencies: list[str]
    submission_type: str
    status_message: str
    inventory_status: str
    drawing_inventory: dict[str, Any] | None = None
    inventory_confirmed_at: str | None = None
    inventory_confirmed_by: str | None = None
    total_issues: int
    report: dict[str, Any] | None = None
    error_message: str | None = None


class ReviewInventoryResponse(BaseModel):
    review_id: str
    inventory_status: str
    drawing_inventory: dict[str, Any] | None = None
    inventory_confirmed_at: str | None = None
    inventory_confirmed_by: str | None = None


@router.post("", response_model=CreateReviewResponse)
async def create_review_endpoint(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    drawing_type: str = Form("Mixed Set"),
    description: str = Form(""),
    review_notes: str = Form(""),
    agency_codes: list[str] | None = Form(None),
    submission_type: str = Form(...),
) -> CreateReviewResponse:
    original_filename = _validate_pdf_upload(file)
    context = _validate_review_context(
        drawing_type=drawing_type,
        description=description,
        review_notes=review_notes,
        agency_codes=agency_codes,
        submission_type=submission_type,
    )
    review_id = str(uuid.uuid4())
    upload_path = _upload_path_for(review_id, original_filename)
    _save_upload(file, upload_path)
    create_review(
        review_id=review_id,
        filename=original_filename,
        drawing_type=context.drawing_type,
        description=context.description,
        review_notes=context.review_notes,
        selected_agencies=context.selected_agencies,
        submission_type=context.submission_type,
        upload_filename=upload_path.name,
    )

    background_tasks.add_task(_run_inventory_background, review_id, upload_path, context)
    return CreateReviewResponse(review_id=review_id)


@router.get("", response_model=list[ReviewListItem])
def list_reviews_endpoint() -> list[dict[str, Any]]:
    return list_reviews()


@router.get("/{review_id}/inventory", response_model=ReviewInventoryResponse)
def get_review_inventory_endpoint(review_id: str) -> dict[str, Any]:
    inventory = get_review_inventory(review_id)
    if inventory is None:
        raise HTTPException(status_code=404, detail="Review not found.")
    return inventory


@router.patch("/{review_id}/inventory", response_model=ReviewInventoryResponse)
async def confirm_review_inventory_endpoint(
    review_id: str,
    inventory: DrawingInventory,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    review = get_review(review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found.")
    if review["status"] == "done":
        raise HTTPException(status_code=409, detail="This review is already complete.")
    if review["status"] == "error":
        raise HTTPException(status_code=409, detail="This review failed and cannot be confirmed.")

    upload_path = resolve_review_upload_path(review_id)
    if upload_path is None:
        raise HTTPException(status_code=404, detail="Original uploaded PDF was not found.")

    updated = update_review_inventory(
        review_id=review_id,
        inventory=inventory,
        inventory_status="confirmed",
        confirmed_by="human",
        status_message="Drawing check confirmed. Starting compliance review.",
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Review not found.")

    context = _context_from_stored_review(review, inventory)
    background_tasks.add_task(_run_review_background, review_id, upload_path, context)
    return updated


@router.get("/{review_id}/export.pdf")
def export_review_pdf_endpoint(review_id: str) -> Response:
    review = get_review(review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found.")
    if review["status"] != "done" or review["report"] is None:
        raise HTTPException(
            status_code=409,
            detail="Only completed reviews can be exported as PDF.",
        )

    pdf_bytes = render_review_pdf(review)
    filename = _export_filename(review["filename"])
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{review_id}/file")
def get_review_file_endpoint(review_id: str) -> FileResponse:
    review = get_review(review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found.")

    upload_path = resolve_review_upload_path(review_id)
    if upload_path is None:
        raise HTTPException(status_code=404, detail="Original uploaded PDF was not found.")

    return FileResponse(
        path=upload_path,
        media_type="application/pdf",
        filename=review["filename"],
        content_disposition_type="inline",
    )


@router.get("/{review_id}/pages/{page_number}.png")
def get_review_page_image_endpoint(review_id: str, page_number: int) -> Response:
    review = get_review(review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found.")
    if page_number < 1:
        raise HTTPException(status_code=400, detail="Page numbers start at 1.")

    page_count = _page_count_for_review(review)
    if page_count and page_number > page_count:
        raise HTTPException(status_code=404, detail=f"Page {page_number} is outside this PDF.")

    upload_path = resolve_review_upload_path(review_id)
    if upload_path is None:
        raise HTTPException(status_code=404, detail="Original uploaded PDF was not found.")

    try:
        image_bytes = render_page_image_png_bytes(upload_path, page_number)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return Response(
        content=image_bytes,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.get("/{review_id}", response_model=ReviewDetailResponse)
def get_review_endpoint(review_id: str) -> dict[str, Any]:
    review = get_review(review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found.")
    return review


async def _run_review_background(review_id: str, upload_path: Path, context: ReviewContext) -> None:
    try:
        report = await review_pdf(
            upload_path,
            trace_id=review_id,
            context=context,
            progress_callback=lambda message: mark_review_progress(review_id, message),
        )
    except ReviewEngineError as exc:
        logger.exception("Review %s failed with a review-engine error.", review_id)
        mark_review_error(review_id, str(exc))
    except Exception as exc:
        logger.exception("Review %s failed unexpectedly.", review_id)
        mark_review_error(
            review_id,
            "The review failed unexpectedly. Check the backend terminal logs for details, then try again.",
        )
    else:
        mark_review_done(review_id, report)


async def _run_inventory_background(review_id: str, upload_path: Path, context: ReviewContext) -> None:
    http_client: httpx.AsyncClient | None = None
    try:
        mark_review_progress(review_id, "Understanding drawing sheets")
        parsed_pdf = parse_pdf(upload_path)
        http_client = httpx.AsyncClient(verify=_build_ssl_context())
        client = AsyncAnthropic(api_key=_load_api_key(), http_client=http_client)
        inventory = await build_drawing_inventory(
            upload_path,
            parsed_pdf,
            client=client,
            progress_callback=lambda message: mark_review_progress(review_id, message),
        )

        if inventory_needs_confirmation(inventory):
            update_review_inventory(
                review_id=review_id,
                inventory=inventory,
                inventory_status="needs_confirmation",
                status_message="Drawing check needs confirmation before compliance review.",
            )
            return

        update_review_inventory(
            review_id=review_id,
            inventory=inventory,
            inventory_status="confirmed",
            confirmed_by="auto",
            status_message="Drawing check confirmed automatically. Starting compliance review.",
        )
        await _run_review_background(
            review_id,
            upload_path,
            _context_with_inventory(context, inventory),
        )
    except ReviewEngineError as exc:
        logger.exception("Review %s failed during drawing inventory.", review_id)
        mark_review_error(review_id, str(exc))
    except Exception:
        logger.exception("Review %s failed unexpectedly during drawing inventory.", review_id)
        mark_review_error(
            review_id,
            "The drawing-understanding step failed unexpectedly. Check the backend terminal logs, then try again.",
        )
    finally:
        if http_client is not None:
            await http_client.aclose()


def _validate_pdf_upload(file: UploadFile) -> str:
    filename = Path(file.filename or "").name.strip()
    if not filename:
        raise HTTPException(status_code=400, detail="Upload a PDF file with a filename.")
    if Path(filename).suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail="Only PDF uploads are supported.")
    return filename


def _validate_review_context(
    drawing_type: str,
    description: str,
    review_notes: str,
    agency_codes: list[str] | None,
    submission_type: str,
) -> ReviewContext:
    try:
        return ReviewContext(
            drawing_type=drawing_type.strip() or "Mixed Set",
            description=description.strip(),
            review_notes=review_notes.strip(),
            selected_agencies=agency_codes,
            submission_type=submission_type.strip(),
        )
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=_validation_detail(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _context_from_stored_review(review: dict[str, Any], inventory: DrawingInventory) -> ReviewContext:
    return ReviewContext(
        drawing_type=review.get("drawing_type") or "Mixed Set",
        description=review.get("description") or "",
        review_notes=review.get("review_notes") or "",
        selected_agencies=review.get("selected_agencies") or None,
        submission_type=review.get("submission_type") or "Design",
        drawing_inventory=inventory,
    )


def _context_with_inventory(context: ReviewContext, inventory: DrawingInventory) -> ReviewContext:
    if hasattr(context, "model_copy"):
        return context.model_copy(update={"drawing_inventory": inventory})
    return context.copy(update={"drawing_inventory": inventory})


def _page_count_for_review(review: dict[str, Any]) -> int:
    report_page_count = int((review.get("report") or {}).get("document", {}).get("page_count") or 0)
    if report_page_count:
        return report_page_count

    inventory = review.get("drawing_inventory") or {}
    pages = inventory.get("pages") if isinstance(inventory, dict) else None
    if isinstance(pages, list):
        return len(pages)
    return 0


def _upload_path_for(review_id: str, filename: str) -> Path:
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    safe_filename = _safe_filename(filename)
    return UPLOADS_DIR / f"{review_id}_{safe_filename}"


def _save_upload(file: UploadFile, destination: Path) -> None:
    with destination.open("wb") as output_file:
        file.file.seek(0)
        shutil.copyfileobj(file.file, output_file)


def _safe_filename(filename: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("._")
    return sanitized or "uploaded.pdf"


def _export_filename(filename: str) -> str:
    stem = Path(filename).stem or "review"
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._") or "review"
    return f"{safe_stem}-compliance-report.pdf"


def _validation_detail(exc: ValidationError) -> str:
    messages = []
    for error in exc.errors():
        messages.append(str(error.get("msg", "Invalid drawing context fields.")))
    return " ".join(messages) or "Invalid drawing context fields."
