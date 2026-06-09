from __future__ import annotations

import unittest
from pathlib import Path
import sys


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import DRAWING_INVENTORY_CONFIDENCE_THRESHOLD
from app.pdf.inventory import classify_page_heuristic, inventory_needs_confirmation
from app.pdf.models import DrawingInventory, ParsedPage


class DrawingInventoryHeuristicTests(unittest.TestCase):
    def test_section_label_is_not_floor_plan(self) -> None:
        page = _page(
            text="1 SECTION 1\n1ST STOREY\n2ND STOREY\n3RD STOREY\nTENDER DRAWINGS\n120.01",
            annotations=["SECTION 1", "120.01"],
        )

        item = classify_page_heuristic(page)

        self.assertEqual(item.primary_view_type, "Section")
        self.assertGreaterEqual(item.confidence, DRAWING_INVENTORY_CONFIDENCE_THRESHOLD)

    def test_elevation_label_is_detected(self) -> None:
        page = _page(text="FRONT ELEVATION\nREAR ELEVATION\nDRAWING NO. 130.01")

        item = classify_page_heuristic(page)

        self.assertEqual(item.primary_view_type, "Elevation")
        self.assertGreaterEqual(item.confidence, DRAWING_INVENTORY_CONFIDENCE_THRESHOLD)

    def test_storey_plan_is_floor_plan(self) -> None:
        page = _page(text="1ST STOREY PLAN\nBEDROOM\nLIVING\nKITCHEN\n110.01")

        item = classify_page_heuristic(page)

        self.assertEqual(item.primary_view_type, "Floor Plan")
        self.assertGreaterEqual(item.confidence, DRAWING_INVENTORY_CONFIDENCE_THRESHOLD)

    def test_title_block_only_needs_confirmation(self) -> None:
        page = _page(text="TENDER DRAWINGS\nPROJECT TITLE\nDRAWING NO.\nREV DATE")

        item = classify_page_heuristic(page)
        inventory = DrawingInventory(pages=[item])

        self.assertEqual(item.primary_view_type, "Unknown")
        self.assertTrue(inventory_needs_confirmation(inventory))


def _page(text: str, annotations: list[str] | None = None) -> ParsedPage:
    return ParsedPage(
        page_number=1,
        text=text,
        annotations=annotations or [],
        image_base64="",
        image_path=Path("/tmp/nonexistent.png"),
    )


if __name__ == "__main__":
    unittest.main()
