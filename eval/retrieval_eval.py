import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.rag.retrieval import retrieve
from app.core.vectorstore import embed, get_collection


def retrieve_unfiltered(query: str, k: int = 5) -> list[str]:
    """
    直接查 ChromaDB，不套 similarity threshold，回傳原始排名的 chunk 列表。

    為什麼不用 retrieve()？
    production 的 retrieve() 會過濾掉 similarity < 0.30 的結果。
    評估時如果正確 chunk 剛好被過濾，就看不到它排在第幾名了。
    我們需要看原始排名，才能算 MRR 和 Recall。
    """
    collection = get_collection()
    query_embedding = embed([query])[0]
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=k,
        include=["documents"],
    )
    return results["documents"][0]


def retrieve_with_reranker(query: str) -> list[str]:
    """
    走 production 的完整 retrieve()，包含 reranker 重排。
    回傳 reranker 排序後的 chunk 列表（最多 reranker_top_k 個）。

    用於量測 reranker 對排名的實際影響。
    若 retrieve() 回傳 found=False（無 chunk 通過 threshold），回傳空列表。
    """
    result = retrieve(query)
    return result.chunks if result.found else []


def chunk_matches(chunk: str, keywords: list[str]) -> bool:
    """
    判斷一個 chunk 是否是「正確 chunk」。
    條件：命中超過半數的 keywords。

    為什麼用半數而不是全部？
    某些關鍵字（如「免運」）可能出現在多個 chunk，要求全部命中太嚴格。
    要求至少一個又太寬鬆。半數是合理的中間值。
    """
    matched = sum(1 for kw in keywords if kw in chunk)
    return matched >= max(1, len(keywords) // 2)


def _eval_chunks(test_cases: list[dict], chunks_fn, max_recall_k: int = 5) -> dict:
    recall_at_3_hits = 0
    recall_at_5_hits = 0
    reciprocal_ranks = []
    per_case = []

    for case in test_cases:
        keywords = case["relevant_chunk_keywords"]
        chunks = chunks_fn(case["question"])

        first_match_rank = None
        for rank, chunk in enumerate(chunks, start=1):
            if chunk_matches(chunk, keywords):
                first_match_rank = rank
                break

        if first_match_rank is not None and first_match_rank <= 3:
            recall_at_3_hits += 1
        if first_match_rank is not None and first_match_rank <= max_recall_k:
            recall_at_5_hits += 1

        rr = (1.0 / first_match_rank) if first_match_rank else 0.0
        reciprocal_ranks.append(rr)

        per_case.append({
            "id": case["id"],
            "question": case["question"],
            "found_at_rank": first_match_rank,
            "reciprocal_rank": round(rr, 4),
        })

    n = len(test_cases)
    return {
        "recall@3": round(recall_at_3_hits / n, 4),
        f"recall@{max_recall_k}": round(recall_at_5_hits / n, 4),
        "mrr": round(sum(reciprocal_ranks) / n, 4),
        "per_case": per_case,
    }


def eval_retrieval(test_cases: list[dict], k: int = 5) -> dict:
    """
    Stage 1 評估（向量相似度排名，不含 reranker）。

    Recall@k：前 k 個結果裡，有多少題找到了正確 chunk（比例）。
    MRR（Mean Reciprocal Rank）：正確 chunk 排在第幾名的倒數，平均值。
      - 排第 1：1/1 = 1.0
      - 排第 3：1/3 = 0.33
      - 找不到：0

    Returns:
        {
          "recall@3": float,
          "recall@5": float,
          "mrr": float,
          "per_case": [{"id", "question", "found_at_rank", "reciprocal_rank"}, ...]
        }
    """
    return _eval_chunks(
        test_cases,
        chunks_fn=lambda q: retrieve_unfiltered(q, k=k),
        max_recall_k=k,
    )


def eval_retrieval_with_reranker(test_cases: list[dict]) -> dict:
    """
    Stage 2 評估（reranker 重排後的排名）。

    走 production 的完整 retrieve()，量測 reranker 對排名的實際改善。
    recall@k 最多計算到 reranker_top_k（通常是 3），所以這裡只有 recall@3。

    與 eval_retrieval() 的差異：
      eval_retrieval()          → 向量相似度排名（Stage 1）
      eval_retrieval_with_reranker() → reranker 重排後（Stage 2）
    比較兩者可以看出 reranker 是否真的改善了排名。
    """
    return _eval_chunks(
        test_cases,
        chunks_fn=retrieve_with_reranker,
        max_recall_k=3,
    )
