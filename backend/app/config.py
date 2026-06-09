from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel


ROOT_DIR = Path(__file__).resolve().parents[2]
ENV_PATH = ROOT_DIR / ".env"
DATA_DIR = ROOT_DIR / "backend" / "data"
SOURCE_PDFS_DIR = DATA_DIR / "source_pdfs"
CHROMA_DIR = DATA_DIR / "chroma"
UPLOADS_DIR = DATA_DIR / "uploads"
DATABASE_PATH = DATA_DIR / "app.db"
RETRIEVAL_LOG_DIR = DATA_DIR / "retrieval_logs"
EVALS_DIR = DATA_DIR / "evals"

load_dotenv(ENV_PATH)

CLAUDE_MODEL = "claude-haiku-4-5-20251001"
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"

# Retrieval tuning knobs. If RAG_CHUNK_SIZE or RAG_CHUNK_OVERLAP changes,
# re-run ingestion with --reset so Chroma contains chunks built the new way.
RAG_CHUNK_SIZE = 900
RAG_CHUNK_OVERLAP = 120
RETRIEVAL_TOP_K_BY_AGENCY = {
    "default": 5,
    "ura": 7,
    "pub": 7,
}

# Large drawing set controls. The engine batches page images so realistic
# multi-page sets do not exceed Claude's per-request payload limits.
MAX_IMAGE_BASE64_CHARS_PER_REQUEST = 1_500_000
MAX_IMAGES_PER_REVIEW_BATCH = 1
FALLBACK_IMAGE_DPI = 75
MAX_RETRIEVED_CHUNKS_PER_CLAUDE_REQUEST = 3
CLAUDE_RATE_LIMIT_RETRY_SECONDS = 70

# Drawing-understanding gate controls. The inventory pass uses the normal
# 150 DPI page render first, then higher-detail crops only for uncertain pages.
DRAWING_INVENTORY_CONFIDENCE_THRESHOLD = 0.76
DRAWING_INVENTORY_IMAGE_DPI = 150
DRAWING_INVENTORY_CROP_DPI = 200


class Agency(BaseModel):
    code: str
    name: str
    description: str
    core: bool


AGENCIES: dict[str, Agency] = {
    "bca": Agency(
        code="bca",
        name="BCA",
        description="Building and Construction Authority requirements for building control and accessibility.",
        core=True,
    ),
    "scdf": Agency(
        code="scdf",
        name="SCDF",
        description="Singapore Civil Defence Force fire safety and emergency access requirements.",
        core=True,
    ),
    "ura": Agency(
        code="ura",
        name="URA",
        description="Urban Redevelopment Authority planning and development control requirements.",
        core=True,
    ),
    "lta": Agency(
        code="lta",
        name="LTA",
        description="Land Transport Authority road, transport, and vehicle access requirements.",
        core=False,
    ),
    "nparks": Agency(
        code="nparks",
        name="NParks",
        description="National Parks Board requirements for greenery, landscaping, and tree protection.",
        core=False,
    ),
    "nea": Agency(
        code="nea",
        name="NEA",
        description="National Environment Agency environmental health, sanitation, and pollution control requirements.",
        core=False,
    ),
    "pub": Agency(
        code="pub",
        name="PUB",
        description="Public Utilities Board drainage, sewerage, and water service requirements.",
        core=False,
    ),
    "ica": Agency(
        code="ica",
        name="ICA",
        description="Immigration and Checkpoints Authority requirements for checkpoint and border facilities.",
        core=False,
    ),
}


CORE_AGENCIES = tuple(code for code, agency in AGENCIES.items() if agency.core)
ACTIVE_AGENCY_CODES = ("bca", "scdf", "ura", "lta", "nparks", "nea", "pub")


def retrieval_top_k_for_agency(agency_code: str) -> int:
    return RETRIEVAL_TOP_K_BY_AGENCY.get(
        agency_code.lower().strip(),
        RETRIEVAL_TOP_K_BY_AGENCY["default"],
    )
