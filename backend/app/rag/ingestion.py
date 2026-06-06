from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import chromadb
from chromadb.errors import NotFoundError
import fitz
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import Document, MetadataMode
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.vector_stores.chroma import ChromaVectorStore

from app.config import AGENCIES, CHROMA_DIR, CORE_AGENCIES, EMBEDDING_MODEL, SOURCE_PDFS_DIR
from app.rag.models import AgencyIngestSummary


CHUNK_SIZE = 900
CHUNK_OVERLAP = 120


@dataclass(frozen=True)
class SectionText:
    title: str
    text: str


def ingest_agencies(
    agency_codes: list[str] | None = None,
    reset: bool = False,
    source_root: Path = SOURCE_PDFS_DIR,
    chroma_dir: Path = CHROMA_DIR,
) -> list[AgencyIngestSummary]:
    agencies = agency_codes or list(CORE_AGENCIES)
    return [
        ingest_agency(
            agency_code=agency,
            reset=reset,
            source_root=source_root,
            chroma_dir=chroma_dir,
        )
        for agency in agencies
    ]


def ingest_agency(
    agency_code: str,
    reset: bool = False,
    source_root: Path = SOURCE_PDFS_DIR,
    chroma_dir: Path = CHROMA_DIR,
) -> AgencyIngestSummary:
    agency = _normalize_agency_code(agency_code)
    collection_name = collection_name_for_agency(agency)
    agency_dir = source_root / agency
    warnings: list[str] = []

    if not agency_dir.exists():
        agency_dir.mkdir(parents=True, exist_ok=True)
        warnings.append(f"Created missing source folder: {agency_dir}")

    pdf_paths = sorted(agency_dir.glob("*.pdf"))
    chroma_dir.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(chroma_dir))

    if reset:
        _delete_collection_if_exists(client, collection_name)

    collection = client.get_or_create_collection(collection_name)
    vector_store: ChromaVectorStore | None = None
    embed_model: HuggingFaceEmbedding | None = None
    splitter = build_sentence_splitter()

    chunks_created = 0
    embedded = 0

    for pdf_path in pdf_paths:
        nodes = _nodes_from_pdf(pdf_path, agency, splitter, warnings)
        chunks_created += len(nodes)

        # Treat each PDF as an upsert unit: remove old chunks for this filename,
        # then add the freshly parsed chunks with stable IDs.
        _delete_source_chunks(collection, pdf_path.name)

        if not nodes:
            continue

        if embed_model is None:
            embed_model = build_embedding_model()
            vector_store = ChromaVectorStore(chroma_collection=collection)

        embeddings = embed_model.get_text_embedding_batch(
            [node.get_content(metadata_mode=MetadataMode.NONE) for node in nodes],
            show_progress=False,
        )
        for node, embedding in zip(nodes, embeddings, strict=True):
            node.embedding = embedding

        if vector_store is None:
            raise RuntimeError("Vector store did not initialize before adding chunks.")
        vector_store.add(nodes)
        embedded += len(nodes)

    return AgencyIngestSummary(
        agency=agency,
        collection=collection_name,
        pdfs_found=len(pdf_paths),
        chunks_created=chunks_created,
        embedded=embedded,
        reset=reset,
        warnings=warnings,
    )


def build_embedding_model() -> HuggingFaceEmbedding:
    # Local HuggingFace embeddings keep ingestion free. The first run downloads
    # the model once; later runs use the cached copy and can work offline.
    return HuggingFaceEmbedding(model_name=EMBEDDING_MODEL, embed_batch_size=16)


def build_sentence_splitter() -> SentenceSplitter:
    # 900 tokens preserves enough clause context for code requirements, while
    # 120 tokens of overlap keeps cross-boundary definitions and exceptions.
    return SentenceSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)


def collection_name_for_agency(agency_code: str) -> str:
    return f"sg_{_normalize_agency_code(agency_code)}"


def _nodes_from_pdf(
    pdf_path: Path,
    agency: str,
    splitter: SentenceSplitter,
    warnings: list[str],
) -> list:
    documents: list[Document] = []

    try:
        with fitz.open(pdf_path) as pdf:
            if pdf.is_encrypted and not pdf.authenticate(""):
                warnings.append(f"Skipped password-protected PDF: {pdf_path.name}")
                return []

            for page_index in range(pdf.page_count):
                page_number = page_index + 1
                text = _normalize_text(pdf.load_page(page_index).get_text("text"))
                if not text:
                    warnings.append(
                        f"{pdf_path.name} page {page_number} has no embedded text; "
                        "scanned/image-only pages cannot be indexed yet."
                    )
                    continue

                for section_index, section in enumerate(_split_into_logical_sections(text), start=1):
                    documents.append(
                        Document(
                            text=section.text,
                            id_=f"{agency}:{pdf_path.name}:p{page_number}:s{section_index}",
                            metadata={
                                "agency": agency,
                                "source_filename": pdf_path.name,
                                "page_number": page_number,
                                "section_title": section.title,
                            },
                        )
                    )
    except fitz.FileDataError:
        warnings.append(f"Skipped unreadable PDF: {pdf_path.name}")
        return []

    nodes = splitter.get_nodes_from_documents(documents)
    for index, node in enumerate(nodes, start=1):
        source = node.metadata.get("source_filename", pdf_path.name)
        page = node.metadata.get("page_number", "")
        section = node.metadata.get("section_title", "")
        digest = hashlib.sha1(node.get_content(metadata_mode=MetadataMode.NONE).encode("utf-8")).hexdigest()[:12]
        node.node_id = f"{agency}:{source}:p{page}:{section}:c{index}:{digest}"
    return nodes


def _split_into_logical_sections(page_text: str) -> list[SectionText]:
    lines = [line.strip() for line in page_text.splitlines() if line.strip()]
    if not lines:
        return []

    sections: list[SectionText] = []
    current_title = "Page text"
    current_lines: list[str] = []

    for line in lines:
        if _looks_like_section_heading(line) and current_lines:
            sections.append(SectionText(title=current_title, text="\n".join(current_lines)))
            current_title = line[:160]
            current_lines = [line]
        else:
            if _looks_like_section_heading(line):
                current_title = line[:160]
            current_lines.append(line)

    if current_lines:
        sections.append(SectionText(title=current_title, text="\n".join(current_lines)))

    return sections


def _looks_like_section_heading(line: str) -> bool:
    if len(line) > 160:
        return False
    if re.match(r"^(\d+(\.\d+)*|[A-Z]\d*(\.\d+)*)\s+[\w(/-]", line):
        return True
    if re.match(r"^(part|section|chapter|appendix)\s+[A-Z0-9]", line, re.IGNORECASE):
        return True
    words = line.split()
    return 2 <= len(words) <= 12 and line.upper() == line and any(char.isalpha() for char in line)


def _delete_collection_if_exists(client: chromadb.PersistentClient, collection_name: str) -> None:
    try:
        client.delete_collection(collection_name)
    except (ValueError, NotFoundError):
        pass


def _delete_source_chunks(collection, source_filename: str) -> None:
    try:
        collection.delete(where={"source_filename": source_filename})
    except ValueError:
        pass


def _normalize_agency_code(agency_code: str) -> str:
    agency = agency_code.lower().strip()
    if agency not in AGENCIES:
        valid = ", ".join(sorted(AGENCIES))
        raise ValueError(f"Unknown agency '{agency_code}'. Valid agencies: {valid}")
    return agency


def _normalize_text(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text).strip()
