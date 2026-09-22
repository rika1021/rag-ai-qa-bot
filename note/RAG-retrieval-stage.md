# RAG 架構學習筆記 — Retrieval 與 Generation 階段

> 記錄時間：2026-09-11
> 範圍：使用者提問後的查詢流程、生成回答，以及 LLM 參數調整

---

## Retrieval 流程總覽

```
使用者問題
   ↓ embed()（與 Ingestion 同一個模型）
查詢向量
   ↓ collection.query()（HNSW 圖走訪，不是全比對）
取前 5 個最近鄰 + 它們的距離
   ↓ similarity = 1 - distance，過濾 < 0.3 的
剩下的 chunk（0~5 個）
   ↓
組合 prompt 給 Claude 生成回答
```

---

## 常見誤解糾正：「取出相似度 > 0.3 的前 5 個」

這個描述的順序是錯的，實際是**兩步**，順序很重要：

1. **先** 從資料庫取出前 5 個最相似的（不管分數高低）
2. **再** 用 0.3 門檻過濾，分數不夠的丟掉

所以最終結果可能是 5 個、3 個、1 個，甚至 0 個。  
0 個時直接回覆「根據現有文件，我無法回答這個問題。」，不呼叫 Claude。

對應程式碼（`retrieval.py`）：
```python
results = collection.query(
    query_embeddings=[query_embedding],
    n_results=settings.retrieval_top_k,   # 先取 top 5（第 29 行）
    include=["documents", "metadatas", "distances"],
)
# ...
if similarity >= settings.similarity_threshold:  # 再過濾 >= 0.3（第 45 行）
    filtered_chunks.append(doc)
```

---

## Q1：Retrieval 階段的 Embedding 模型是什麼

**和 Ingestion 階段用的是完全同一個模型：**

```
sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
```

對應程式碼 `retrieval.py:25`：
```python
query_embedding = embed([query])[0]
```

這個 `embed()` 從 `vectorstore.py` 引入，是同一個函式、同一個模型。

### 為什麼必須用同一個模型

存進去和查詢時必須用相同模型，因為：

> 不同模型產生的向量，座標系統不同，比出來的距離毫無意義。

就像地圖座標系統，台灣用 TWD97，歐洲用 WGS84，直接比數字不能代表真實距離。

---

## Q2：怎麼跟 ChromaDB 做相似度比對？要全部比對一次嗎？

**不需要全部比對**，這就是 HNSW 索引存在的原因。

### 沒有索引的暴力做法（Brute Force）

```
查詢向量 → 跟第1筆比 → 跟第2筆比 → ... → 跟第N筆比 → 取最小距離
```

N 筆資料就要算 N 次，資料越多越慢，複雜度為 **O(N)**。

### HNSW 的做法

HNSW 在 `add()` 資料時，就預先把所有向量建成一個**多層圖結構**：

```
第 3 層（最稀疏）：只有少數節點，彼此有長程連線
第 2 層：節點變多
第 1 層（最密集）：所有節點，彼此有短程連線
```

查詢時的策略：
1. **從稀疏層進入**，用少量比較快速定位到大概的區域
2. **逐層下降**，每層只比較少量鄰居，逐步縮小範圍
3. **在最密集層做精細搜尋**，在小範圍內找最近鄰

類比：在台灣找人不會逐戶敲門，而是先縮到縣市 → 區 → 街 → 再逐戶找。

複雜度從 O(N) 降到接近 **O(log N)**，資料量十倍，搜尋時間只多一點點。

程式碼設定（`vectorstore.py`）：
```python
client.get_or_create_collection(
    name=COLLECTION_NAME,
    metadata={"hnsw:space": "cosine"},  # 使用 cosine 距離
)
```

### 注意：HNSW 是「近似」最近鄰

HNSW 找到的是**近似**（Approximate Nearest Neighbor），理論上可能不是數學意義上最近的那幾個。但實務上準確率很高（通常 > 95%），且：

> 語意搜尋本身就不需要「數學上絕對最近」，「夠近、夠相關」就夠了。

### 距離轉相似度的換算

ChromaDB 回傳的是**距離（distance）**，程式碼在 `retrieval.py:42` 轉換：

```python
similarity = 1 - distance
```

cosine distance 範圍是 0~2，所以 similarity 範圍是 -1~1：
- similarity 接近 1 → 非常相似
- similarity 接近 0 → 不相關
- similarity 為負 → 語意相反

---

## Q3：Temperature 與 Top_p 參數

### 你的專案目前的狀況

`generator.py:56` 呼叫 Claude 時沒有設定 temperature 或 top_p，使用 **Claude 預設值（temperature=1）**：

```python
response = client.messages.create(
    model=settings.claude_model,
    max_tokens=1024,
    system=SYSTEM_PROMPT,
    messages=[{"role": "user", "content": user_message}],
    # 沒有 temperature，預設 = 1
)
```

### Temperature 是什麼

控制模型「有多隨機」。模型在生成每個字之前，會對所有可能的下一個字算出機率分佈，temperature 決定這個分佈有多「平」：

| Temperature | 效果 |
|---|---|
| 接近 0 | 幾乎每次都選機率最高的字，輸出非常穩定、可預測 |
| 1（預設） | 按照原始機率選，有適度的多樣性 |
| 接近 2 | 機率分佈被拉平，低機率的字也有機會被選，更隨機、更有創意，但也更容易亂 |

### Top_p（Nucleus Sampling）是什麼

另一種控制隨機的方式，不是調機率分佈，而是**限制候選字的範圍**：

> 「只從累積機率達到 p 的那些字裡面選，其他直接排除。」

例如 top_p=0.9，代表只考慮「機率加總達到 90%」的那幾個最可能的字。

**重要：temperature 和 top_p 通常只調其中一個**，同時調兩個容易讓效果難以預測。

### 不同場景的建議設定

| 使用場景 | 建議設定 | 原因 |
|---|---|---|
| **客服 QA（本專案）** | temperature=0~0.1 | 答案要準確、一致，不能每次問同一問題得到不同回答 |
| **文件摘要** | temperature=0~0.3 | 忠實於原文，不需創意 |
| **程式碼生成** | temperature=0~0.2 | 語法必須正確，容錯率低 |
| **行銷文案、廣告標語** | temperature=0.7~1 | 需要多樣性和創意 |
| **故事創作、腦力激盪** | temperature=1~1.5 | 越天馬行空越好 |
| **一般聊天機器人** | temperature=0.7 左右 | 要有點個性，但不能亂 |

### 本專案應該調整

客服機器人有嚴格的 system prompt（只能依文件回答），但 temperature=1 仍有隨機性，可能導致：
- 同一個問題問兩次，措辭差異很大
- 偶爾「發揮創意」補充了文件沒有的內容

**建議修改 `generator.py`：**

```python
response = client.messages.create(
    model=settings.claude_model,
    max_tokens=1024,
    temperature=0.1,   # 加這行
    system=SYSTEM_PROMPT,
    messages=[{"role": "user", "content": user_message}],
)
```

top_p 不需要動，temperature 調低就夠了。

---

## Generation 流程補充

`generator.py` 在 Retrieval 完成後組合 prompt 的方式（第 53 行）：

```python
user_message = f"【參考文件】\n{context_text}\n\n【使用者問題】\n{query}"
```

結構是：
```
system prompt（規則：只能依文件回答）
  +
【參考文件】
第 1 段：...chunk 原文...
第 2 段：...chunk 原文...
...

【使用者問題】
使用者輸入的問題
```

整包餵給 Claude 生成答案。

---

## Confidence 機制

`generator.py` 額外回傳一個 `confidence` 欄位，依最高相似度分數分三級：

| 條件 | confidence 值 | 意義 |
|---|---|---|
| top_score >= 0.7 | `"high"` | 找到高度相關的文件 |
| top_score >= 0.3 | `"low"` | 找到勉強相關的文件 |
| top_score < 0.3 | `"no_context"` | 沒找到相關文件，不呼叫 Claude |

---

*上一階段：[RAG-ingestion-stage.md](RAG-ingestion-stage.md)*
