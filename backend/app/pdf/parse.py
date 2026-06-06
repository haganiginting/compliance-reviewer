from __future__ import annotations

import argparse
from pathlib import Path

from app.pdf.parser import parse_pdf


def main() -> None:
    args = _parse_args()
    result = parse_pdf(args.pdf_path, working_dir=args.workdir)

    print(f"PDF: {result.document.filename}")
    print(f"Pages: {result.document.page_count}")
    print(f"Rendered PNG folder: {result.working_dir}")

    for page in result.pages:
        image_status = "yes" if page.image_path.exists() and page.image_base64 else "no"
        text_note = ""
        if len(page.text) == 0:
            text_note = " (no embedded text found; likely an image-only scan, PNG is available for vision)"

        print(
            f"Page {page.page_number}: "
            f"{len(page.text)} text characters{text_note}, "
            f"{len(page.annotations)} annotations/labels, "
            f"image rendered: {image_status} ({page.image_path.name})"
        )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Parse a drawing PDF and print a compact per-page summary."
    )
    parser.add_argument("pdf_path", type=Path, help="Path to the PDF drawing to parse.")
    parser.add_argument(
        "--workdir",
        type=Path,
        default=None,
        help="Optional folder for rendered page PNGs. Defaults to a temporary folder.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    main()
