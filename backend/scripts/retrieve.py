from __future__ import annotations

import argparse
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import retrieval_top_k_for_agency  # noqa: E402
from app.rag.retrieval import retrieve_chunks  # noqa: E402


def main() -> None:
    args = _parse_args()
    top_k = args.top_k if args.top_k is not None else retrieval_top_k_for_agency(args.agency)
    chunks = retrieve_chunks(agency_code=args.agency, query=args.query, top_k=top_k)

    print(f"Top {len(chunks)} chunks for {args.agency.upper()}: {args.query}")
    for index, chunk in enumerate(chunks, start=1):
        title = f" — {chunk.section_title}" if chunk.section_title else ""
        print(f"\n{index}. {chunk.source_filename}, page {chunk.page_number}{title}")
        if chunk.score is not None:
            print(f"   distance: {chunk.score:.4f}")
        print(f"   {chunk.text[:500].replace(chr(10), ' ')}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sanity-check retrieval from one agency knowledge-base collection."
    )
    parser.add_argument("--agency", required=True, help="Lowercase agency code, such as bca.")
    parser.add_argument(
        "--top-k",
        type=int,
        default=None,
        help="Number of chunks to return. Defaults to the configured value for the agency.",
    )
    parser.add_argument("query", help="Search query to test against the agency collection.")
    return parser.parse_args()


if __name__ == "__main__":
    main()
