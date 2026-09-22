# RAG Evaluation 學習筆記

> 建立日期：2026-09-14
> 對應實作：`eval/`、`tests/`

---

## 一、為什麼需要評估？

RAG 系統建起來之後，你面對的問題是：**「它有多好？」**

沒有評估，你只能用感覺判斷。換了 chunking 策略，是變好還是變差？換了模型，recall 提升了嗎？這些問題沒有量化就無法回答。

評估的核心價值有兩個：
- **量化品質**：把「感覺不錯」變成「Recall@3 = 91.67%」
- **偵測退步**：改了任何東西，能立刻知道有沒有讓系統變差

---

## 二、RAG 的兩種失敗模式

```
使用者問問題
     ↓
  [Retrieval]  ← 失敗模式 1：撈的 chunk 根本不對
     ↓
  [Generation] ← 失敗模式 2：chunk 對了，但 Claude 捏造或答偏
     ↓
  答案給使用者
```

這兩種失敗的成因完全不同：
- 失敗模式 1 → 改 chunking、embedding model、threshold
- 失敗模式 2 → 改 system prompt、context 組裝方式

所以評估也分兩層，各自對應不同的指標。

---

## 三、Retrieval 評估指標

### 前置條件：Ground Truth Dataset

必須先有「已知正確答案的考題」，格式如下：

```json
{
  "question": "超商取貨運費是多少？",
  "ground_truth_answer": "NT$60/件，滿 NT$490 免運",
  "relevant_chunk_keywords": ["超商取貨", "NT$60", "NT$490"]
}
```

`relevant_chunk_keywords` 的作用：因為沒有 chunk ID，用「這個 chunk 應該包含哪些詞」來判斷撈回的 chunk 算不算「正確」。

---

### Recall@k

**定義**：前 k 個結果裡，有幾題命中了正確 chunk（比例）。

```
Recall@3 = 命中的題數 / 全部題數

例：12 題裡 11 題在前 3 名找到正確 chunk
Recall@3 = 11/12 = 91.67%
```

**用途**：判斷 top-k 的覆蓋率夠不夠。若 Recall@3 低，使用者通常拿不到好答案。

---

### MRR（Mean Reciprocal Rank）

**定義**：正確 chunk 排在第幾名的倒數，對所有題目取平均。

```
排第 1 名 → 1/1 = 1.0
排第 2 名 → 1/2 = 0.5
排第 3 名 → 1/3 = 0.33
找不到   → 0

MRR = 所有題目 reciprocal rank 的平均值
```

**和 Recall@k 的差別**：
- Recall@k 是二元的（有找到 or 沒找到）
- MRR 獎勵「找到而且排前面」，排第 1 比排第 5 得分高

本專案 MRR = 0.81，代表正確 chunk 平均排在第 1.2 名，非常好。

---

### 為什麼 Retrieval 評估要繞過 threshold？

Production 的 `retrieve()` 有 `similarity_threshold=0.30`，低於此值的 chunk 會被過濾掉。

如果直接用 `retrieve()` 做評估，正確 chunk 可能被過濾，就看不到它「原本排在第幾名」了。

解法：`retrieve_unfiltered()` 直接查 ChromaDB，不套 threshold，拿原始排名。

```python
# 評估用（看原始排名）
results = collection.query(query_embeddings=[...], n_results=k, include=["documents"])

# Production 用（有 threshold 過濾）
retrieval_result = retrieve(query)
```

---

## 四、Answer 評估指標（RAGAS）

RAGAS（Retrieval Augmented Generation Assessment）是一個評估框架，用 LLM 當裁判自動打分。

### Faithfulness（忠實度）

**問題**：答案有沒有捏造文件以外的資訊？

**計算方式**：
1. Claude 看答案，列出所有陳述（factual claims）
2. 對每個陳述問：「這件事能從 context（撈回的 chunk）裡找到根據嗎？」
3. `faithfulness = 有根據的陳述數 / 全部陳述數`

**例子**：
```
答案：「退貨期限為 7 天，且可以換貨」
Context 裡有：「7 個日曆天內可退貨」
Context 裡沒有：「可以換貨」（本商城不提供換貨）

faithfulness = 1/2 = 0.50  ← 有一半是捏造的
```

本專案 Faithfulness = 84.29%，代表系統的嚴格 system prompt 有效果。

---

### Answer Relevancy（答案相關性）

**問題**：答案有沒有真的回應問題？

**計算方式**：
1. Claude 看答案，反推「這個答案適合回應什麼問題？」（生成 3 個問題）
2. 把反推的問題和原問題做 embedding cosine similarity
3. `answer_relevancy = 平均相似度`

**用途**：抓出「答案是忠實的，但根本沒有回應問題」的情況（例如 Claude 給了很長的通用說明，但沒有直接回答）。

---

### 繁體中文的 Answer Relevancy 問題

RAGAS 設計時主要針對英文。`answer_relevancy` 的計算涉及「Claude 生成問題 → 和原問題做 embedding 比對」。

Claude 傾向用英文生成那 3 個反推問題，但原問題是繁體中文。跨語言 embedding 比對即使用多語言模型，也有系統性的分數壓低。

**結果**：本專案 Answer Relevancy = 58.33%，明顯低於 Faithfulness。
**處置**：這不代表系統差，而是評估工具對非英文的限制。閾值調為 0.50，專注在偵測退步。

---

## 五、RAGAS 與 Anthropic 整合方式

RAGAS 透過 LangChain 的抽象層接 LLM，不綁定 OpenAI。

```python
from langchain_anthropic import ChatAnthropic
from langchain_community.embeddings import FastEmbedEmbeddings

# LLM judge：用 Claude 當裁判
llm = ChatAnthropic(model="claude-haiku-4-5-20251001", ...)

# Embeddings：用同一個 ONNX 模型，不需要 PyTorch
embeddings = FastEmbedEmbeddings(
    model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)

result = evaluate(dataset, metrics=[faithfulness, answer_relevancy],
                  llm=llm, embeddings=embeddings)
```

**LLM-as-judge 是合理的嗎？**

是的。RAGAS 問的問題是結構化且客觀的，例如「這個陳述能從 context 找到根據嗎？」這類問題 LLM 能可靠地回答，和「用 Claude 評 Claude」的感覺上的循環沒有實際關係。業界普遍接受此做法。

---

## 六、Regression Test 設計原則

**為什麼不把評估直接寫進 pytest？**

完整評估需要 ~50 次 API call，花 2-5 分鐘、費用 $0.10-0.15。不適合每次 `pytest` 都跑。

**解法：兩段式設計**

```
python eval/run_eval.py   → 昂貴，手動跑，產生 results.json
pytest tests/ -v          → 便宜，讀 JSON，1 秒完成
```

**閾值的意義**

閾值不是在追求「高分」，而是在定義「什麼程度算退步」。

```python
THRESHOLDS = {
    "recall@3": 0.70,       # 低於此值：retrieval 顯著退步
    "mrr": 0.60,            # 低於此值：排名品質退步
    "faithfulness": 0.70,   # 低於此值：hallucination 增加
    "answer_relevancy": 0.50,  # 針對中文系統調整
}
```

---

## 七、本專案 Baseline 分數（2026-09-14）

| Metric           | Score  | 說明 |
|------------------|--------|------|
| Recall@3         | 91.67% | 12 題裡 11 題在前 3 名命中 |
| Recall@5         | 100%   | 所有題目都有撈到正確 chunk |
| MRR              | 0.8083 | 正確 chunk 平均排在第 1.2 名 |
| Faithfulness     | 84.29% | 嚴格 system prompt 有效 |
| Answer Relevancy | 58.33% | 受中文限制，閾值調為 0.50 |

---

## 八、常見問題

**Q：一題只命中部分 keywords 算不算正確？**

A：`chunk_matches()` 用「命中超過半數 keywords」作為標準。例如 4 個 keywords 命中 2 個就算。太嚴格（全部命中）會因為 keywords 分散在多個 chunk 而誤判；太寬鬆（命中 1 個）又容易誤判通用詞。

**Q：ChromaDB 出現一堆 "Failed to send telemetry event" 是什麼？**

A：ChromaDB 嘗試發送匿名使用統計失敗（因為我們設了 `ANONYMIZED_TELEMETRY=False`，但舊版的 telemetry 實作有 bug）。這是無害的噪音，不影響任何功能。

**Q：`ragas==0.1.21` 為什麼要 pin 版本？**

A：RAGAS 0.2.x 完全重寫了 API，import 路徑、Dataset 格式都不同。不 pin 版本，`pip install ragas` 會裝到 0.2.x，程式碼會靜默壞掉。
