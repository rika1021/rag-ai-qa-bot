"""
RAG Evaluation Pipeline 主程式。

使用方式：
    python eval/run_eval.py

執行流程：
    1. 讀取 eval/test_data.json（12 題 ground truth Q&A）
    2. Phase 1：Retrieval 評估（純向量搜尋，不打 Claude API）
       → 計算 Recall@3、Recall@5、MRR
    3. Phase 2：對每題跑 retrieve() + generate()，收集 RAG 輸出
    4. Phase 3：RAGAS 評估（Claude 當裁判，會打 API）
       → 計算 faithfulness、answer_relevancy
    5. 儲存完整報告至 eval/results.json

執行後再跑 pytest tests/ -v 確認分數有沒有退步。
每次跑約花 2-5 分鐘，API 費用約 $0.10-0.15。
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ["ANONYMIZED_TELEMETRY"] = "False"

from dotenv import load_dotenv

load_dotenv()

from app.core.config import settings
from app.core.rag.generator import generate
from app.core.rag.retrieval import retrieve
from eval.answer_eval import eval_answers
from eval.retrieval_eval import eval_retrieval, eval_retrieval_with_reranker

EVAL_DIR = Path(__file__).parent
TEST_DATA_PATH = EVAL_DIR / "test_data.json"
RESULTS_PATH = EVAL_DIR / "results.json"


def main():
    print("=" * 50)
    print("RAG Evaluation Pipeline")
    print("=" * 50)

    print("\n[1/4] 讀取測試資料...")
    test_cases = json.loads(TEST_DATA_PATH.read_text(encoding="utf-8"))
    print(f"  共 {len(test_cases)} 題")

    # Phase 1: Retrieval 評估（不打 API，純向量搜尋）
    print("\n[2/4] Retrieval 評估中（純向量搜尋，無 API 費用）...")
    retrieval_scores = eval_retrieval(test_cases, k=5)
    print(f"  Stage 1（向量搜尋） Recall@3 : {retrieval_scores['recall@3']:.2%}")
    print(f"  Stage 1（向量搜尋） Recall@5 : {retrieval_scores['recall@5']:.2%}")
    print(f"  Stage 1（向量搜尋） MRR      : {retrieval_scores['mrr']:.4f}")

    print("\n  Reranker 評估中（走完整 retrieve()）...")
    reranker_scores = eval_retrieval_with_reranker(test_cases)
    print(f"  Stage 2（reranker） Recall@3 : {reranker_scores['recall@3']:.2%}")
    print(f"  Stage 2（reranker） MRR      : {reranker_scores['mrr']:.4f}")

    # Phase 2: 對每題生成答案（打 Claude API）
    print("\n[3/4] 生成答案中（呼叫 Claude API）...")
    ragas_samples = []
    for i, case in enumerate(test_cases):
        print(f"  [{i+1:02d}/{len(test_cases)}] {case['id']}")
        retrieval_result = retrieve(case["question"])
        gen_result = generate(case["question"], retrieval_result)
        ragas_samples.append({
            "question": case["question"],
            "answer": gen_result["answer"],
            "contexts": retrieval_result.chunks if retrieval_result.found else [],
            "ground_truth": case["ground_truth_answer"],
        })

    # Phase 3: RAGAS 評估（Claude 當裁判，打 API）
    print("\n[4/4] RAGAS 評估中（Claude 當裁判，需要一段時間）...")
    ragas_scores = eval_answers(
        ragas_samples,
        api_key=settings.anthropic_api_key,
        model=settings.claude_model,
    )
    print(f"  Faithfulness     : {ragas_scores['faithfulness']:.2%}")
    print(f"  Answer Relevancy : {ragas_scores['answer_relevancy']:.2%}")

    # 儲存報告
    report = {
        "timestamp": datetime.now().isoformat(),
        "test_cases_count": len(test_cases),
        "retrieval": retrieval_scores,
        "retrieval_reranked": reranker_scores,
        "ragas": ragas_scores,
        "ragas_samples": ragas_samples,
    }
    RESULTS_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\n" + "=" * 50)
    print("評估完成！結果摘要：")
    print(f"  Recall@3         : {retrieval_scores['recall@3']:.2%}")
    print(f"  MRR              : {retrieval_scores['mrr']:.4f}")
    print(f"  Faithfulness     : {ragas_scores['faithfulness']:.2%}")
    print(f"  Answer Relevancy : {ragas_scores['answer_relevancy']:.2%}")
    print(f"\n完整報告已存至 {RESULTS_PATH}")
    print("接著可執行 pytest tests/ -v 確認分數有沒有退步")
    print("=" * 50)


if __name__ == "__main__":
    main()
