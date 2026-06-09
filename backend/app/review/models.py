from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, validator

from app.config import ACTIVE_AGENCY_CODES
from app.pdf.models import DrawingInventory, DrawingViewType, ParsedDocument


Severity = Literal["Critical", "Major", "Advisory"]
SubmissionType = Literal["Design", "Authority Submission"]
DrawingType = Literal[
    "Floor Plan",
    "Site Plan",
    "Section & Elevation",
    "Drainage",
    "Fire Safety",
    "Mixed Set",
]


def normalize_selected_agencies(value: list[str] | tuple[str, ...] | None = None) -> list[str]:
    active_codes = tuple(code.lower().strip() for code in ACTIVE_AGENCY_CODES)
    if value is None:
        return list(active_codes)

    normalized: list[str] = []
    invalid_codes: list[str] = []
    for code in value:
        cleaned_code = str(code).lower().strip()
        if not cleaned_code:
            continue
        if cleaned_code not in active_codes:
            invalid_codes.append(cleaned_code)
            continue
        if cleaned_code not in normalized:
            normalized.append(cleaned_code)

    if invalid_codes:
        allowed = ", ".join(active_codes)
        invalid = ", ".join(invalid_codes)
        raise ValueError(f"Unknown or inactive agency code(s): {invalid}. Allowed codes: {allowed}.")
    if not normalized:
        raise ValueError("Choose at least one agency to review.")

    return normalized


class ReviewContext(BaseModel):
    drawing_type: DrawingType = "Mixed Set"
    description: str = ""
    review_notes: str = ""
    selected_agencies: list[str] = Field(default_factory=lambda: normalize_selected_agencies())
    submission_type: SubmissionType = "Design"
    drawing_inventory: DrawingInventory | None = None

    @validator("selected_agencies", pre=True, always=True)
    def _validate_selected_agencies(cls, value: list[str] | tuple[str, ...] | None) -> list[str]:
        return normalize_selected_agencies(value)


class IssueMarkup(BaseModel):
    page_number: int = Field(ge=1)
    marker_label: str = Field(min_length=1)
    marker_x: float = Field(ge=0, le=1)
    marker_y: float = Field(ge=0, le=1)


class ComplianceIssue(BaseModel):
    title: str = Field(min_length=1)
    severity: Severity
    description: str = Field(min_length=1)
    clause_reference: str = Field(min_length=1)
    drawing_location: str = Field(min_length=1)
    drawing_page_number: int | None = Field(default=None, ge=1)
    drawing_view_type: DrawingViewType | None = None
    suggested_resolution: str = Field(min_length=1)
    markup: IssueMarkup | None = None


class AgencyReview(BaseModel):
    agency: str = Field(min_length=1)
    issues: list[ComplianceIssue] = Field(default_factory=list)


class ReviewSummary(BaseModel):
    total_issues: int
    by_agency: dict[str, int]
    by_severity: dict[str, int]


class ComplianceReport(BaseModel):
    document: ParsedDocument
    reviewed_at: str
    agencies: list[AgencyReview]
    summary: ReviewSummary
