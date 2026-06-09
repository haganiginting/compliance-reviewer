from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from app.review.engine import ReviewEngineError, review_pdf
from app.review.models import ReviewContext


def main() -> None:
    args = _parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        context = ReviewContext(
            selected_agencies=args.agency,
            submission_type=args.submission_type,
        )
        report = asyncio.run(review_pdf(args.pdf_path, context=context))
    except ReviewEngineError as exc:
        print(f"Review failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    output_path = _resolve_output_path(args.pdf_path, args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if hasattr(report, "model_dump"):
        report_data = report.model_dump()
    else:
        report_data = report.dict()

    json_text = json.dumps(report_data, indent=2)
    output_path.write_text(json_text + "\n", encoding="utf-8")
    print(json_text)
    print(f"\nSaved report to: {output_path}", file=sys.stderr)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run an active-agency compliance review for one drawing PDF."
    )
    parser.add_argument("pdf_path", type=Path, help="Path to the drawing PDF to review.")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional output JSON path. Defaults to a timestamped file beside the PDF.",
    )
    parser.add_argument(
        "--agency",
        action="append",
        default=None,
        help="Agency code to review, such as bca or ura. Repeat for multiple agencies. Defaults to all active agencies.",
    )
    parser.add_argument(
        "--submission-type",
        choices=["Design", "Authority Submission"],
        default="Design",
        help="Drawing submission type. Design mode ignores authority-submission format-only checks.",
    )
    return parser.parse_args()


def _resolve_output_path(pdf_path: Path, output_path: Path | None) -> Path:
    if output_path is not None:
        return output_path.expanduser()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    pdf = pdf_path.expanduser()
    default_name = f"{pdf.stem}_compliance_report_{timestamp}.json"

    try:
        parent = pdf.resolve().parent
        if parent.exists():
            return parent / default_name
    except OSError:
        pass

    return Path.cwd() / default_name


if __name__ == "__main__":
    main()
