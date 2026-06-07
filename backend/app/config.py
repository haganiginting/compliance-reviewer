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

load_dotenv(ENV_PATH)

CLAUDE_MODEL = "claude-haiku-4-5-20251001"
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"


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
