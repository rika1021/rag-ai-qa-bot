import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from datasets import Dataset
from langchain_anthropic import ChatAnthropic
from langchain_community.embeddings import FastEmbedEmbeddings
from ragas import evaluate
from ragas.metrics import answer_relevancy, faithfulness


def build_ragas_components(api_key: str, model: str):
    """
    建立 RAGAS 需要的兩個元件：

    1. LLM（ChatAnthropic）：RAGAS 用它當「裁判」，問「這個答案忠實嗎？」
       - Faithfulness：Claude 列出答案的所有陳述，逐一問「context 裡有根據嗎？」
       - Answer Relevancy：Claude 反推「這個答案適合回答什麼問題？」再和原問題比對

    2. Embeddings（FastEmbedEmbeddings）：用於 answer_relevancy 的相似度比較。
       使用和 production 相同的 ONNX 模型，不需要 PyTorch。
    """
    llm = ChatAnthropic(
        model=model,
        anthropic_api_key=api_key,
        max_tokens=1024,
    )
    embeddings = FastEmbedEmbeddings(
        model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    )
    return llm, embeddings


def eval_answers(samples: list[dict], api_key: str, model: str) -> dict:
    """
    用 RAGAS 評估 RAG 系統的答案品質。

    Args:
        samples: 每筆包含：
            - question: str（使用者的問題）
            - answer: str（RAG 系統生成的答案）
            - contexts: list[str]（撈到的 chunk 列表）
            - ground_truth: str（正確答案，來自 test_data.json）
        api_key: Anthropic API key
        model: Claude 模型 ID

    Returns:
        {
          "faithfulness": float,       # 0~1，越高越好，代表答案沒有捏造內容
          "answer_relevancy": float,   # 0~1，越高越好，代表答案有回應問題
        }

    注意：raise_exceptions=False 表示單題失敗不會讓整個評估崩潰，
    但會回傳 NaN，所以下面有 isnan 防護。
    """
    llm, embeddings = build_ragas_components(api_key, model)

    data = {
        "question": [s["question"] for s in samples],
        "answer": [s["answer"] for s in samples],
        "contexts": [s["contexts"] for s in samples],
        "ground_truth": [s["ground_truth"] for s in samples],
    }
    dataset = Dataset.from_dict(data)

    result = evaluate(
        dataset,
        metrics=[faithfulness, answer_relevancy],
        llm=llm,
        embeddings=embeddings,
        raise_exceptions=False,
    )

    faith_score = float(result["faithfulness"])
    rel_score = float(result["answer_relevancy"])

    return {
        "faithfulness": round(faith_score if not math.isnan(faith_score) else 0.0, 4),
        "answer_relevancy": round(rel_score if not math.isnan(rel_score) else 0.0, 4),
    }
