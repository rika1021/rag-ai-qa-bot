import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

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


def eval_retrieval(test_cases: list[dict], k: int = 5) -> dict:
    """
    計算所有題目的 Recall@3、Recall@5、MRR。

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
    recall_at_3_hits = 0
    recall_at_5_hits = 0
    reciprocal_ranks = []
    per_case = []

    for case in test_cases:
        keywords = case["relevant_chunk_keywords"]
        chunks = retrieve_unfiltered(case["question"], k=k)

        first_match_rank = None
        for rank, chunk in enumerate(chunks, start=1):
            if chunk_matches(chunk, keywords):
                first_match_rank = rank
                break

        if first_match_rank is not None and first_match_rank <= 3:
            recall_at_3_hits += 1
        if first_match_rank is not None and first_match_rank <= 5:
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
        "recall@5": round(recall_at_5_hits / n, 4),
        "mrr": round(sum(reciprocal_ranks) / n, 4),
        "per_case": per_case,
    }
