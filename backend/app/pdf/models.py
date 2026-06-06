from pathlib import Path

from pydantic import BaseModel, Field


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
