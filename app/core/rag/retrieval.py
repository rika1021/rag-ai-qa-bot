from dataclasses import dataclass, field

from app.core.config import settings
from app.core.vectorstore import embed, get_collection


@dataclass
class RetrievalResult:
    found: bool
    chunks: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    top_score: float = 0.0


def retrieve(query: str) -> RetrievalResult:
    """
    把問題轉成向量，去 ChromaDB 找相關 chunk。
    每筆個別判斷相似度，只保留 >= 閾值的 chunk。
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

    filtered_chunks: list[str] = []
    filtered_sources: list[str] = []
    top_score: float = 0.0

    for doc, meta, distance in zip(documents, metadatas, distances):
        similarity = 1 - distance
        if similarity > top_score:
            top_score = similarity
        if similarity >= settings.similarity_threshold:
            filtered_chunks.append(doc)
            filtered_sources.append(meta["source"])

    if not filtered_chunks:
        return RetrievalResult(found=False, top_score=top_score)

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
