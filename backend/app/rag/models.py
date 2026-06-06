from pydantic import BaseModel, Field


class AgencyIngestSummary(BaseModel):
    agency: str
    collection: str
    pdfs_found: int
    chunks_created: int
    embedded: int
    reset: bool = False
    warnings: list[str] = Field(default_factory=list)


class RetrievedChunk(BaseModel):
    agency: str
    source_filename: str
    page_number: int
    text: str
    score: float | None = None
    section_title: str | None = None

