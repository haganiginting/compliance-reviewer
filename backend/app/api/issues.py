from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.storage import update_issue_note


router = APIRouter(prefix="/api/issues", tags=["issues"])


class UpdateIssueNoteRequest(BaseModel):
    note: str = Field(max_length=4000)


class IssueNoteResponse(BaseModel):
    id: str
    note: str


@router.patch("/{issue_id}/note", response_model=IssueNoteResponse)
def update_issue_note_endpoint(
    issue_id: str,
    request: UpdateIssueNoteRequest,
) -> dict[str, str]:
    updated_issue = update_issue_note(issue_id=issue_id, note=request.note)
    if updated_issue is None:
        raise HTTPException(status_code=404, detail="Issue not found.")
    return updated_issue
