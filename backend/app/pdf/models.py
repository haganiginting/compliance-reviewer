from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


DrawingViewType = Literal[
    "Floor Plan",
    "Site Plan",
    "Section",
    "Elevation",
    "Section & Elevation",
    "Detail",
    "Schedule/General",
    "Unknown",
]


class ParsedDocument(BaseModel):
    filename: str
    page_count: int


class ParsedPage(BaseModel):
    page_number: int
    text: str
    annotations: list[str]
    image_base64: str
    image_path: Path = Field(exclude=True)


class ParsedPdf(BaseModel):
    document: ParsedDocument
    pages: list[ParsedPage]
    working_dir: Path = Field(exclude=True)


class DrawingInventoryItem(BaseModel):
    page_number: int = Field(ge=1)
    sheet_title: str = ""
    drawing_number: str = ""
    primary_view_type: DrawingViewType = "Unknown"
    detected_view_types: list[DrawingViewType] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    evidence_labels: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DrawingInventory(BaseModel):
    pages: list[DrawingInventoryItem] = Field(default_factory=list)
