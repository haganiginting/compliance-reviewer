from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import EVALS_DIR
from app.evals.models import EvalConfig, ExpectedFinding
from app.review.engine import review_pdf
from app.review.models import ComplianceIssue, ComplianceReport, ReviewContext


def run_eval(config_path: Path, output_dir: Path | None = None) -> dict[str, Any]:
    config = _load_eval_config(config_path)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    results: list[dict[str, Any]] = []

    for sample in config.samples:
        pdf_path = _resolve_sample_pdf_path(sample.pdf_path, config_path.parent)
        trace_id = f"eval_{_safe_id(sample.name)}_{run_id}"
        context = ReviewContext(
            selected_agencies=sample.selected_agencies,
            submission_type=sample.submission_type,
        )
        try:
            report = asyncio.run(review_pdf(pdf_path, trace_id=trace_id, context=context))
        except Exception as exc:
            results.append(
                {
                    "sample": sample.name,
                    "pdf_path": str(pdf_path),
                    "status": "error",
                    "error": str(exc),
                    "selected_agencies": context.selected_agencies,
                    "submission_type": context.submission_type,
                    "caught": [],
                    "missed": [_expected_to_dict(finding) for finding in sample.expected_findings],
                    "unexpected_issues": [],
                    "wording_violations": [],
                }
            )
            continue

        results.append(
            _score_sample(
                sample.name,
                pdf_path,
                sample.expected_findings,
                sample.forbidden_issue_phrases,
                report,
                context,
            )
        )

    output = _build_output(config_path, run_id, results)
    results_dir = output_dir or (EVALS_DIR / "results")
    results_dir.mkdir(parents=True, exist_ok=True)
    output_path = results_dir / f"eval_results_{run_id}.json"
    output["output_path"] = str(output_path)
    output_path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    return output


def _load_eval_config(config_path: Path) -> EvalConfig:
    data = json.loads(config_path.read_text(encoding="utf-8"))
    if hasattr(EvalConfig, "model_validate"):
        return EvalConfig.model_validate(data)
    return EvalConfig.parse_obj(data)


def _resolve_sample_pdf_path(pdf_path: str, config_dir: Path) -> Path:
    path = Path(pdf_path).expanduser()
    if path.is_absolute():
        return path
    return (config_dir / path).resolve()


def _score_sample(
    sample_name: str,
    pdf_path: Path,
    expected_findings: list[ExpectedFinding],
    forbidden_issue_phrases: list[str],
    report: ComplianceReport,
    context: ReviewContext,
) -> dict[str, Any]:
    issues = _flatten_issues(report)
    matched_issue_indexes: set[int] = set()
    caught: list[dict[str, Any]] = []
    missed: list[dict[str, Any]] = []

    for expected in expected_findings:
        match_index = _find_matching_issue(expected, issues, matched_issue_indexes)
        if match_index is None:
            missed.append(_expected_to_dict(expected))
            continue

        matched_issue_indexes.add(match_index)
        caught.append(
            {
                "expected": _expected_to_dict(expected),
                "matched_issue": _issue_to_dict(issues[match_index]),
            }
        )

    unexpected = [
        _issue_to_dict(issue)
        for index, issue in enumerate(issues)
        if index not in matched_issue_indexes
    ]
    wording_violations = _find_wording_violations(forbidden_issue_phrases, issues)

    return {
        "sample": sample_name,
        "pdf_path": str(pdf_path),
        "status": "done",
        "selected_agencies": context.selected_agencies,
        "submission_type": context.submission_type,
        "caught": caught,
        "missed": missed,
        "unexpected_issues": unexpected,
        "wording_violations": wording_violations,
    }


def _flatten_issues(report: ComplianceReport) -> list[tuple[str, ComplianceIssue]]:
    flattened: list[tuple[str, ComplianceIssue]] = []
    for agency_review in report.agencies:
        for issue in agency_review.issues:
            flattened.append((agency_review.agency, issue))
    return flattened


def _find_matching_issue(
    expected: ExpectedFinding,
    issues: list[tuple[str, ComplianceIssue]],
    already_matched: set[int],
) -> int | None:
    expected_agency = _normalize_agency(expected.agency)
    expected_keywords = [_normalize_text(keyword) for keyword in expected.keywords]

    for index, (agency, issue) in enumerate(issues):
        if index in already_matched:
            continue
        if _normalize_agency(agency) != expected_agency:
            continue
        if expected.severity is not None and issue.severity != expected.severity:
            continue
        issue_text = _normalize_text(
            " ".join(
                [
                    issue.title,
                    issue.description,
                    issue.clause_reference,
                    issue.drawing_location,
                    issue.suggested_resolution,
                ]
            )
        )
        if all(keyword in issue_text for keyword in expected_keywords):
            return index
    return None


def _build_output(config_path: Path, run_id: str, results: list[dict[str, Any]]) -> dict[str, Any]:
    total_caught = sum(len(result["caught"]) for result in results)
    total_missed = sum(len(result["missed"]) for result in results)
    total_unexpected = sum(len(result["unexpected_issues"]) for result in results)
    total_wording_violations = sum(len(result["wording_violations"]) for result in results)
    return {
        "run_id": run_id,
        "config_path": str(config_path),
        "totals": {
            "samples": len(results),
            "caught": total_caught,
            "missed": total_missed,
            "unexpected_issues": total_unexpected,
            "wording_violations": total_wording_violations,
        },
        "samples": results,
    }


def _expected_to_dict(expected: ExpectedFinding) -> dict[str, Any]:
    data = {
        "agency": expected.agency,
        "keywords": expected.keywords,
    }
    if expected.title:
        data["title"] = expected.title
    if expected.severity:
        data["severity"] = expected.severity
    return data


def _issue_to_dict(issue_data: tuple[str, ComplianceIssue]) -> dict[str, str]:
    agency, issue = issue_data
    return {
        "agency": agency,
        "title": issue.title,
        "severity": issue.severity,
        "clause_reference": issue.clause_reference,
        "drawing_location": issue.drawing_location,
        "drawing_view_type": issue.drawing_view_type or "",
    }


def _find_wording_violations(
    forbidden_issue_phrases: list[str],
    issues: list[tuple[str, ComplianceIssue]],
) -> list[dict[str, str]]:
    normalized_phrases = [
        _normalize_text(phrase)
        for phrase in forbidden_issue_phrases
        if _normalize_text(phrase)
    ]
    if not normalized_phrases:
        return []

    violations: list[dict[str, str]] = []
    for agency, issue in issues:
        issue_text = _normalize_text(
            " ".join(
                [
                    issue.title,
                    issue.description,
                    issue.drawing_location,
                    issue.drawing_view_type or "",
                ]
            )
        )
        for phrase in normalized_phrases:
            if phrase in issue_text:
                violations.append(
                    {
                        "agency": agency,
                        "title": issue.title,
                        "forbidden_phrase": phrase,
                    }
                )
    return violations


def _normalize_agency(agency: str) -> str:
    return agency.lower().strip()


def _normalize_text(text: str) -> str:
    return " ".join(text.lower().split())


def _safe_id(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in "._-" else "_" for char in value)
    return cleaned.strip("._") or "sample"
