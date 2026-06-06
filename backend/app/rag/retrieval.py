from __future__ import annotations

from pathlib import Path

import chromadb

from app.config import CHROMA_DIR
from app.rag.ingestion import build_embedding_model, collection_name_for_agency
from app.rag.models import RetrievedChunk


def retrieve_chunks(
    agency_code: str,
    query: str,
    top_k: int = 3,
    chroma_dir: Path = CHROMA_DIR,
) -> list[RetrievedChunk]:
    collection_name = collection_name_for_agency(agency_code)
    client = chromadb.PersistentClient(path=str(chroma_dir))
    collection = client.get_collection(collection_name)

    embed_model = build_embedding_model()
    query_embedding = embed_model.get_query_embedding(query)
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )

    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    chunks: list[RetrievedChunk] = []
    for text, metadata, distance in zip(documents, metadatas, distances, strict=False):
        chunks.append(
            RetrievedChunk(
                agency=str(metadata.get("agency", agency_code)).lower(),
                source_filename=str(metadata.get("source_filename", "unknown")),
                page_number=int(metadata.get("page_number", 0)),
                section_title=metadata.get("section_title") or None,
                text=text,
                score=float(distance) if distance is not None else None,
            )
        )
    return chunks

