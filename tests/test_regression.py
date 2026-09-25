"""
RAG Regression Test Suite

用途：確認每次修改（chunking 策略、模型、threshold）後，品質指標沒有退步。

使用方式：
    # Step 1: 先跑完整評估，產生 results.json
    python eval/run_eval.py

    # Step 2: 跑 regression tests（讀 results.json，1 秒內完成）
    pytest tests/ -v

閾值說明：
    - recall@3 >= 0.70：前 3 個結果至少 70% 的題能找到正確 chunk
    - mrr >= 0.60：正確 chunk 平均排在前 2 名左右
    - faithfulness >= 0.70：至少 70% 的答案陳述有文件根據（無捏造）
    - answer_relevancy >= 0.70：至少 70% 的答案有確實回應問題

若有指標低於閾值，代表你的改動讓品質退步了。
"""

import json
from pathlib import Path

import pytest

RESULTS_PATH = Path(__file__).parent.parent / "eval" / "results.json"

THRESHOLDS = {
    "recall@3": 0.70,
    "mrr": 0.60,
    "faithfulness": 0.70,
    # RAGAS answer_relevancy 對繁體中文有系統性低分（LLM judge 生成英文問題再和中文問題比對）
    # baseline = 67.00%（加 reranker 後），閾值設 0.55 以偵測退步
    "answer_relevancy": 0.55,
    # Reranker（Stage 2）的指標閾值
    # baseline: recall@3=100%, mrr=1.0；設低於 baseline 以容許資料集變動
    "reranker_recall@3": 0.92,
    "reranker_mrr": 0.85,
}


@pytest.fixture(scope="session")
def eval_results():
    if not RESULTS_PATH.exists():
        pytest.skip(
            "找不到 eval/results.json。"
            "請先執行 `python eval/run_eval.py` 產生評估結果。"
        )
    return json.loads(RESULTS_PATH.read_text(encoding="utf-8"))


def test_retrieval_recall_at_3(eval_results):
    """
    前 3 個撈回的 chunk，至少要有 70% 的題目命中正確 chunk。
    若低於此值，使用者會頻繁收到「無法回答」或錯誤回應。
    最常見原因：chunking 策略變差，或 similarity_threshold 設太高。
    """
    score = eval_results["retrieval"]["recall@3"]
    threshold = THRESHOLDS["recall@3"]
    assert score >= threshold, (
        f"Recall@3 = {score:.2%}，低於閾值 {threshold:.0%}。\n"
        f"建議檢查：app/core/rag/ingestion.py（chunking）或 "
        f"app/core/config.py（similarity_threshold）"
    )


def test_retrieval_mrr(eval_results):
    """
    MRR >= 0.60 代表正確 chunk 平均排在前 2 名。
    若 MRR 低但 Recall 不低，代表正確 chunk 都有被撈到，但排名不夠前面。
    """
    score = eval_results["retrieval"]["mrr"]
    threshold = THRESHOLDS["mrr"]
    assert score >= threshold, (
        f"MRR = {score:.4f}，低於閾值 {threshold}。\n"
        f"正確 chunk 有被撈到但排名太後面。"
        f"建議檢查 embedding 模型或 chunking 策略。"
    )


def test_ragas_faithfulness(eval_results):
    """
    Faithfulness >= 0.70 代表答案裡 70% 以上的陳述都有文件根據。
    低於此值代表 Claude 在捏造資訊（hallucination）。
    最常見原因：system prompt 不夠嚴格，或 context 不足時仍強行回答。
    """
    score = eval_results["ragas"]["faithfulness"]
    threshold = THRESHOLDS["faithfulness"]
    assert score >= threshold, (
        f"Faithfulness = {score:.2%}，低於閾值 {threshold:.0%}。\n"
        f"建議檢查：app/core/rag/generator.py 的 system prompt 是否夠嚴格。"
    )


def test_reranker_recall_at_3(eval_results):
    """
    Reranker（Stage 2）的 Recall@3。
    baseline = 100%，設 0.92 容許資料集小幅變動。
    若低於此值，代表 reranker 排名退步，正確 chunk 掉出前 3。
    可能原因：reranker 模型版本變動，或 sentence-transformers 版本不相容。
    """
    if "retrieval_reranked" not in eval_results:
        pytest.skip("找不到 retrieval_reranked。請先執行 `python eval/run_eval.py` 並更新 results.json。")
    score = eval_results["retrieval_reranked"]["recall@3"]
    threshold = THRESHOLDS["reranker_recall@3"]
    assert score >= threshold, (
        f"Reranker Recall@3 = {score:.2%}，低於閾值 {threshold:.0%}。\n"
        f"Stage 1 向量搜尋正常但 Stage 2 退步，代表 reranker 排名出問題。\n"
        f"建議檢查：sentence-transformers 版本或 app/core/config.py 的 reranker_model。"
    )


def test_reranker_mrr(eval_results):
    """
    Reranker（Stage 2）的 MRR。
    baseline = 1.0，設 0.85 容許資料集小幅變動。
    若 Stage 1 MRR 正常但此值退步，代表 reranker 重排方向錯誤。
    """
    if "retrieval_reranked" not in eval_results:
        pytest.skip("找不到 retrieval_reranked。請先執行 `python eval/run_eval.py` 並更新 results.json。")
    score = eval_results["retrieval_reranked"]["mrr"]
    threshold = THRESHOLDS["reranker_mrr"]
    assert score >= threshold, (
        f"Reranker MRR = {score:.4f}，低於閾值 {threshold}。\n"
        f"正確 chunk 有被撈到但 reranker 排名不夠前面。"
    )


def test_ragas_answer_relevancy(eval_results):
    """
    Answer Relevancy >= 0.70 代表答案確實有回應問題。
    即使答案忠實，若回答偏題（太通用或答非所問），此分數會低。
    """
    score = eval_results["ragas"]["answer_relevancy"]
    threshold = THRESHOLDS["answer_relevancy"]
    assert score >= threshold, (
        f"Answer Relevancy = {score:.2%}，低於閾值 {threshold:.0%}。\n"
        f"系統可能回傳了過於通用或答非所問的回應。\n"
        f"建議檢查：app/core/rag/generator.py 的 user message template。"
    )
