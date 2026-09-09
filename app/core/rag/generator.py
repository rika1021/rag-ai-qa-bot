import anthropic

from app.core.config import settings
from app.core.rag.retrieval import RetrievalResult

SYSTEM_PROMPT = """你是一個專業的客服助理。

你只能根據下方【參考文件】的內容來回答使用者的問題。

規則：
1. 只使用【參考文件】中提供的資訊作答
2. 如果文件內容不足以回答問題，請明確回覆：「根據現有文件，我無法回答這個問題。」
3. 絕對不可以自行推測、補充或使用文件以外的知識
4. 回答時請引用文件內容，讓使用者知道答案的依據
"""

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    return _client


def _build_confidence(top_score: float) -> str:
    if top_score >= 0.7:
        return "high"
    if top_score >= settings.similarity_threshold:
        return "low"
    return "no_context"


def _build_context_text(chunks: list[str]) -> str:
    parts = [f"第 {i + 1} 段：{chunk}" for i, chunk in enumerate(chunks)]
    return "\n".join(parts)


def generate(query: str, retrieval: RetrievalResult) -> dict:
    """
    接收 retrieval 結果，呼叫 Claude 生成答案。
    若 retrieval.found=False 則直接回覆，不呼叫 Claude。
    """
    if not retrieval.found:
        return {
            "answer": "根據現有文件，我無法回答這個問題。",
            "sources": [],
            "confidence": "no_context",
        }

    context_text = _build_context_text(retrieval.chunks)
    user_message = f"【參考文件】\n{context_text}\n\n【使用者問題】\n{query}"

    client = _get_client()
    response = client.messages.create(
        model=settings.claude_model,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    answer = next(
        (block.text for block in response.content if block.type == "text"),
        "根據現有文件，我無法回答這個問題。",
    )

    return {
        "answer": answer,
        "sources": retrieval.sources,
        "confidence": _build_confidence(retrieval.top_score),
    }
