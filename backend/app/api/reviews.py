from __future__ import annotations

import logging
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Response, UploadFile
from pydantic import BaseModel

from app.config import UPLOADS_DIR
from app.export import render_review_pdf
from app.review.engine import ReviewEngineError, review_pdf
from app.storage import create_review, get_review, list_reviews, mark_review_done, mark_review_error


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/reviews", tags=["reviews"])


class CreateReviewResponse(BaseModel):
    review_id: str


class ReviewListItem(BaseModel):
    id: str
    filename: str
    created_at: str
    total_issues: int
    status: str


class ReviewDetailResponse(BaseModel):
    id: str
    filename: str
    created_at: str
    updated_at: str
    status: str
    total_issues: int
    report: dict[str, Any] | None = None
    error_message: str | None = None


@router.post("", response_model=CreateReviewResponse)
async def create_review_endpoint(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
) -> CreateReviewResponse:
    original_filename = _validate_pdf_upload(file)
    review_id = str(uuid.uuid4())
    upload_path = _upload_path_for(review_id, original_filename)
    _save_upload(file, upload_path)
    create_review(review_id=review_id, filename=original_filename)

    background_tasks.add_task(_run_review_background, review_id, upload_path)
    return CreateReviewResponse(review_id=review_id)


@router.get("", response_model=list[ReviewListItem])
def list_reviews_endpoint() -> list[dict[str, Any]]:
    return list_reviews()


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


@router.get("/{review_id}", response_model=ReviewDetailResponse)
def get_review_endpoint(review_id: str) -> dict[str, Any]:
    review = get_review(review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found.")
    return review


async def _run_review_background(review_id: str, upload_path: Path) -> None:
    try:
        report = await review_pdf(upload_path)
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


def _validate_pdf_upload(file: UploadFile) -> str:
    filename = Path(file.filename or "").name.strip()
    if not filename:
        raise HTTPException(status_code=400, detail="Upload a PDF file with a filename.")
    if Path(filename).suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail="Only PDF uploads are supported.")
    return filename


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
