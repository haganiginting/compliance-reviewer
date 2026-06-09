from __future__ import annotations

from pydantic import BaseModel, Field

from app.review.models import Severity, SubmissionType


class ExpectedFinding(BaseModel):
    agency: str = Field(min_length=1)
    keywords: list[str] = Field(min_length=1)
    title: str | None = None
    severity: Severity | None = None


class EvalSample(BaseModel):
    name: str = Field(min_length=1)
    pdf_path: str = Field(min_length=1)
    selected_agencies: list[str] | None = None
    submission_type: SubmissionType = "Design"
    expected_findings: list[ExpectedFinding] = Field(default_factory=list)
    forbidden_issue_phrases: list[str] = Field(default_factory=list)


class EvalConfig(BaseModel):
    samples: list[EvalSample] = Field(default_factory=list)
