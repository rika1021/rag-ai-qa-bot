from __future__ import annotations

import chromadb
from chromadb.config import Settings as ChromaSettings
from fastembed import TextEmbedding

from app.core.config import settings

_chroma_client = None
_embed_model = None
COLLECTION_NAME = "knowledge_base"


def get_chroma_client():
    global _chroma_client
    if _chroma_client is None:
        _chroma_client = chromadb.PersistentClient(
            path=str(settings.chroma_dir),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
    return _chroma_client


def get_embed_model():
    global _embed_model
    if _embed_model is None:
        _embed_model = TextEmbedding(
            model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        )
    return _embed_model


def get_collection():
    client = get_chroma_client()
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def embed(texts: list[str]) -> list[list[float]]:
    model = get_embed_model()
    return [v.tolist() for v in model.embed(texts)]
