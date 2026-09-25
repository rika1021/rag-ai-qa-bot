from dataclasses import dataclass, field
from functools import lru_cache

from sentence_transformers import CrossEncoder

from app.core.config import settings
from app.core.vectorstore import embed, get_collection


@dataclass
class RetrievalResult:
    found: bool
    chunks: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    top_score: float = 0.0


@lru_cache(maxsize=1)
def _get_reranker() -> CrossEncoder:
    return CrossEncoder(settings.reranker_model)


def retrieve(query: str) -> RetrievalResult:
    """
    Two-stage retrieval:
    Stage 1 — ChromaDB 向量搜尋取 top_k 候選（召回率優先）
    Stage 2 — Cross-encoder reranker 重新評分，取 reranker_top_k（精準度優先）
    """
    collection = get_collection()

    if collection.count() == 0:
        return RetrievalResult(found=False)

    query_embedding = embed([query])[0]

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=settings.retrieval_top_k,
        include=["documents", "metadatas", "distances"],
    )

    documents = results["documents"][0]
    metadatas = results["metadatas"][0]
    distances = results["distances"][0]

    # Stage 1 過濾：移除相似度太低的 chunk
    candidates: list[tuple[str, str, float]] = []
    for doc, meta, distance in zip(documents, metadatas, distances):
        similarity = 1 - distance
        if similarity >= settings.similarity_threshold:
            candidates.append((doc, meta["source"], similarity))

    if not candidates:
        top_score = max((1 - d for d in distances), default=0.0)
        return RetrievalResult(found=False, top_score=top_score)

    # Stage 2 rerank：cross-encoder 對每個候選重新評分
    reranker = _get_reranker()
    pairs = [[query, doc] for doc, _, _ in candidates]
    rerank_scores = reranker.predict(pairs)

    ranked = sorted(
        zip(rerank_scores, candidates),
        key=lambda x: x[0],
        reverse=True,
    )

    top_chunks = ranked[: settings.reranker_top_k]
    top_score = float(ranked[0][1][2])  # 原始向量相似度中最高的

    filtered_chunks = [doc for _, (doc, _, _) in top_chunks]
    filtered_sources = [src for _, (_, src, _) in top_chunks]

    # 去除重複來源，但保持順序
    seen: set[str] = set()
    unique_sources: list[str] = []
    for s in filtered_sources:
        if s not in seen:
            seen.add(s)
            unique_sources.append(s)

    return RetrievalResult(
        found=True,
        chunks=filtered_chunks,
        sources=unique_sources,
        top_score=top_score,
    )
