from __future__ import annotations

import argparse
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import CORE_AGENCIES  # noqa: E402
from app.rag.ingestion import ingest_agencies  # noqa: E402


def main() -> None:
    args = _parse_args()
    agency_codes = [args.agency] if args.agency else list(CORE_AGENCIES)
    summaries = ingest_agencies(agency_codes=agency_codes, reset=args.reset)

    for summary in summaries:
        print(f"Agency: {summary.agency.upper()} ({summary.collection})")
        print(f"  PDFs found: {summary.pdfs_found}")
        print(f"  Chunks created: {summary.chunks_created}")
        print(f"  Embedded: {summary.embedded}")
        print(f"  Reset first: {'yes' if summary.reset else 'no'}")
        for warning in summary.warnings:
            print(f"  Warning: {warning}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the local Chroma knowledge base from agency PDFs."
    )
    parser.add_argument(
        "--agency",
        default=None,
        help="Lowercase agency code to ingest one folder, such as bca, scdf, or ura. Defaults to BCA/SCDF/URA.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Clear each selected agency collection before ingesting it again.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    main()

