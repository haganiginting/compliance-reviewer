from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.pdf.models import ParsedDocument


Severity = Literal["Critical", "Major", "Advisory"]


class ComplianceIssue(BaseModel):
    title: str = Field(min_length=1)
    severity: Severity
    description: str = Field(min_length=1)
    clause_reference: str = Field(min_length=1)
    drawing_location: str = Field(min_length=1)
    suggested_resolution: str = Field(min_length=1)


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
