# RAG 架構學習筆記 — Generator 階段

> 記錄時間：2026-09-11
> 範圍：從 Retrieval 結果到生成最終回答的完整流程

---

## Generator 在整體架構中的位置

```
[Retrieval 階段]
找出相關 chunk，回傳 RetrievalResult 物件
   ↓
[Generator 階段]  ← 本篇範圍
組合 prompt → 呼叫 Claude API → 回傳答案
```

Retrieval 只負責「找出哪些 chunk 相關」，**組合 prompt 是在 Generator 階段**，不是 Retrieval。

---

## Generator 完整流程

```
RetrievalResult 進來
   ↓
found=False？
  → 直接回傳固定拒答字串（完全不呼叫 Claude）
   ↓
found=True：
  chunk 原文 → _build_context_text() → 加編號、串成一段文字
  + 使用者問題 → 拼接成 user_message（純字串）
  + SYSTEM_PROMPT → 作為 system 欄位
   ↓
呼叫 Claude Haiku 4.5 API
   ↓
取出回應文字
   ↓
回傳 { answer, sources, confidence }
```

---

## Q1：Prompt 是怎麼組合的

### 答案：就是字串拼接，組成新的字串變數

對應 `generator.py:52-53`：

```python
context_text = _build_context_text(retrieval.chunks)
user_message = f"【參考文件】\n{context_text}\n\n【使用者問題】\n{query}"
```

`_build_context_text()` 把多個 chunk 加上編號後串在一起：

```python
parts = [f"第 {i + 1} 段：{chunk}" for i, chunk in enumerate(chunks)]
return "\n".join(parts)
```

### 最終 user_message 的實際內容（純文字字串）

```
【參考文件】
第 1 段：退貨須在購買後 7 天內提出申請...
第 2 段：退款將於確認後 5~7 個工作天內...

【使用者問題】
我買錯了，可以退貨嗎？
```

### 傳給 Claude API 的完整結構

```python
client.messages.create(
    model=settings.claude_model,
    max_tokens=1024,
    system=SYSTEM_PROMPT,       # 規則說明，獨立的 system 欄位
    messages=[
        {"role": "user", "content": user_message}  # 參考文件 + 問題
    ],
)
```

`system` 和 `user_message` 是分開的兩個欄位，不是一起拼在同一個字串裡。

### System Prompt 內容

```
你是一個專業的客服助理。

你只能根據下方【參考文件】的內容來回答使用者的問題。

規則：
1. 只使用【參考文件】中提供的資訊作答
2. 如果文件內容不足以回答問題，請明確回覆：「根據現有文件，我無法回答這個問題。」
3. 絕對不可以自行推測、補充或使用文件以外的知識
4. 回答時請引用文件內容，讓使用者知道答案的依據
```

---

## Q2：餵給什麼模型

`config.py:13`：

```python
claude_model: str = "claude-haiku-4-5-20251001"
```

使用 **Claude Haiku 4.5**，Anthropic 最輕量的模型系列。

### 為什麼選 Haiku 而不是 Sonnet 或 Opus

| 模型 | 速度 | 費用 | 適合場景 |
|---|---|---|---|
| Haiku | 最快 | 最低 | 大量呼叫、問答、分類、簡單推理 |
| Sonnet | 中等 | 中等 | 複雜分析、程式碼生成、長文摘要 |
| Opus | 最慢 | 最高 | 需要最強推理能力的複雜任務 |

客服問答不需要創意或複雜推理，只需要忠實依照文件回答，Haiku 的速度和成本優勢讓它最適合這個場景。

---

## 漏掉的步驟一：found=False 的提前返回

`generator.py:45-50`：

```python
if not retrieval.found:
    return {
        "answer": "根據現有文件，我無法回答這個問題。",
        "sources": [],
        "confidence": "no_context",
    }
```

當 Retrieval 找不到任何超過 0.3 門檻的 chunk 時，**直接回傳固定字串，完全不呼叫 Claude API**。

### 這個設計的兩個重要原因

**省錢：** 沒有上下文的情況下叫 Claude 回答，只會得到幻覺（hallucination），不如直接不呼叫。

**準確：** 固定拒答字串比 Claude 在沒有依據時亂猜，對使用者更誠實、更可靠。

---

## 漏掉的步驟二：Confidence 分級機制

Generator 除了回傳 `answer`，還回傳 `confidence` 欄位，讓前端可以決定要不要顯示警示。

`generator.py:27-32`：

```python
def _build_confidence(top_score: float) -> str:
    if top_score >= 0.7:
        return "high"
    if top_score >= settings.similarity_threshold:  # 0.3
        return "low"
    return "no_context"
```

| confidence | top_score 範圍 | 意義 |
|---|---|---|
| `high` | >= 0.7 | 找到高度相關文件，答案可信度高 |
| `low` | 0.3 ~ 0.7 | 找到的文件勉強相關，答案僅供參考 |
| `no_context` | < 0.3 | 沒找到相關文件，直接拒答，不呼叫 Claude |

---

## 回傳結構

```python
return {
    "answer": answer,           # Claude 生成的回答文字
    "sources": retrieval.sources,  # 來源檔案名稱清單（去重後）
    "confidence": _build_confidence(retrieval.top_score),  # 信心等級
}
```

---

## 補充：Temperature 參數問題

本專案呼叫 Claude 時沒有設定 temperature，使用預設值（temperature=1），這對客服 QA 場景並不理想。

### 建議修改

```python
response = client.messages.create(
    model=settings.claude_model,
    max_tokens=1024,
    temperature=0.1,   # 加這行，讓回答更穩定一致
    system=SYSTEM_PROMPT,
    messages=[{"role": "user", "content": user_message}],
)
```

### Temperature 與 Top_p 說明

| 參數 | 作用 | 本專案建議 |
|---|---|---|
| temperature | 控制輸出隨機程度，0=最穩定，2=最隨機 | 設為 0.1，客服需要一致性 |
| top_p | 限制候選字的機率累積範圍 | 不需調整，調 temperature 就夠了 |

兩個參數通常只調其中一個，同時調會讓效果難以預測。

---

*上一階段：[RAG-retrieval-stage.md](RAG-retrieval-stage.md)*  
*上上階段：[RAG-ingestion-stage.md](RAG-ingestion-stage.md)*
