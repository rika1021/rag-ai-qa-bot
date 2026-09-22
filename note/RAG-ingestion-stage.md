# RAG 架構學習筆記 — 文件 Ingestion 階段

> 記錄時間：2026-09-11
> 範圍：文件上傳後的處理流程，包含 chunking、embedding、寫入向量資料庫

---

## 大框架：正確的流程順序

```
文件上傳 → Chunking → Embedding → 寫入向量資料庫（資料庫自動建索引）
```

**常見誤解：** 「索引」不是獨立步驟，是 ChromaDB 在你呼叫 `collection.add()` 時**自動在內部建立**的，不需要手動觸發。

---

## Q1：語意切割（Semantic Chunking）的做法與原理

### 程式碼位置
`app/core/rag/ingestion.py`，函式 `_semantic_chunk()`（第 18 行）

### 兩段式切割邏輯

**第一段：按段落邊界切（真正的語意部分）**

```python
raw_paragraphs = text.split("\n\n")  # 用空行切段落
```

原理：文件本身的段落分隔（空行 `\n\n`）代表原作者認為「這裡換了一個主題」，所以尊重這個邊界就等於尊重語意結構。

和傳統字數切割的差異：
- 字數切割：不管內容，切到字數上限就截斷，可能把一句話切成兩半
- 語意切割：以原文段落為主要依據，字數只是兜底

**第二段：處理邊緣情況**

| 情況 | 處理方式 |
|---|---|
| 段落 < 80 字（太短） | 合併到下一個段落，避免資訊量太少的 chunk |
| 段落 > 500 字（太長） | 交給 `RecursiveCharacterTextSplitter` 做細切 |
| 段落在 80~500 字之間 | 直接保留，不再處理 |

---

## Q1 延伸：RecursiveCharacterTextSplitter 確切在做什麼

### 核心概念

「Recursive（遞迴）」是關鍵字。它有一個**優先順序分隔符號清單**，依序嘗試：

```
["\n\n", "\n", "。", "！", "？", " ", ""]
```

### 運作邏輯

> 「我要把這段文字切成不超過 500 字的塊。我先試試能不能在 `\n\n`（空行）這裡切？可以就切。不行，退而求其次在 `\n`（換行）切。還是不行，在句號切。最後實在沒辦法，才硬切字元。」

這個 Splitter 只會在段落**超過 500 字**時才啟動，把超長段落繼續往下切，但盡量切在自然邊界。

### chunk_overlap 的作用

程式碼設定 `chunk_overlap=50`，意思是每個 chunk 的結尾與下一個 chunk 的開頭**重疊 50 個字**。

原因：避免跨 chunk 邊界的語意被硬切斷，讓內容在邊界處有一定連貫性。

---

## Q2：Embedding 模型

### 模型名稱
`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`

### 淺白說明

這個模型的工作是「**把文字翻譯成座標**」。

想像一個 384 維的空間，每一段文字都對應這個空間裡的一個點：
- 「退貨要怎麼辦？」和「我想申請退款」→ 兩個點距離很近
- 「如何退貨」和「今天天氣如何」→ 兩個點距離很遠

查詢時，使用者的問題也被轉成向量，系統就用數學（cosine 相似度）找出距離最近的幾個 chunk，這些 chunk 就是「最相關的」。

### 模型名稱拆解

| 部分 | 意思 |
|---|---|
| `sentence-transformers` | 專門把句子轉成向量的框架 |
| `paraphrase` | 訓練時用「同義改寫句對」學習，讓相同意思但不同說法的句子向量靠近 |
| `multilingual` | 支援 50+ 語言，同一個意思用中文或英文說，向量也會很接近 |
| `MiniLM` | Microsoft 開發的輕量架構，把大模型「蒸餾」成小模型，速度快但效果接近 |
| `L12` | 有 12 層神經網路 |
| `v2` | 第二版 |

### 與其他模型的比較

| 比較對象 | 差異 |
|---|---|
| OpenAI `text-embedding-3-small` | 需付費打 API、需要網路；這個模型完全本地跑，免費 |
| `all-MiniLM-L6-v2`（英文版） | 那個只擅長英文；這個支援中文 |
| 更大的模型（L24、L32） | 向量品質稍高但速度慢、佔記憶體多；文件量小的專案 L12 足夠 |

### 選擇這個模型的原因
**本地跑、免費、支援中文、速度夠快**，適合 side project。

---

## Q3：ChromaDB 是什麼樣的儲存空間，為什麼選它

### 普通資料庫 vs 向量資料庫的根本差異

| | 普通資料庫（如 MySQL） | 向量資料庫（如 ChromaDB） |
|---|---|---|
| 搜尋問題 | 「哪筆資料的欄位**等於**某個值？」 | 「哪幾筆向量和查詢向量**最接近**？」 |
| 搜尋方式 | 精確比對 | 近似最近鄰搜尋（ANN） |
| 適合場景 | 結構化資料查詢 | 語意相似度查詋 |

MySQL 做不到向量近似搜尋，因為沒有辦法有效率地在幾千個 384 維向量裡找「最接近的」。

### ChromaDB 的索引結構：HNSW

程式碼裡的 `"hnsw:space": "cosine"` 就是設定這個：

- **HNSW（Hierarchical Navigable Small World）**：一種圖結構索引，讓「找最近鄰」的速度非常快
- 不需要每次查詢都跟全部資料一一比對
- `cosine`：使用 cosine 相似度計算距離（適合文字向量）

### ChromaDB 在本專案的儲存方式

```python
# vectorstore.py:17
chromadb.PersistentClient(path=str(settings.chroma_dir))
```

- `PersistentClient`：資料直接存成**本機的資料夾和檔案**（SQLite + 二進位檔）
- `collection.add()`：直接寫檔，不走網路
- `collection.query()`：直接讀檔，不走網路
- **完全本地，零網路依賴**

ChromaDB 有提供雲端/Server 模式，但本專案使用最簡單的本地模式。

### 為什麼選 ChromaDB 而不選其他向量資料庫

| 選項 | 適合場景 |
|---|---|
| **ChromaDB（本專案）** | 本地開發、side project、快速上手，零設定 |
| Pinecone | 雲端、大規模生產環境，需付費 |
| Weaviate / Qdrant | 需要 Docker 或 Server，設定複雜，適合團隊協作 |
| pgvector（PostgreSQL 插件） | 已有 PostgreSQL 系統想順便加向量搜尋 |

本專案的選擇理由：**side project、本地跑、不需裝 Docker，ChromaDB 是最低門檻的選擇**。

---

## 寫入向量資料庫的資料結構

每一筆資料由四個欄位組成（對應 `ingestion.py:73`）：

| 欄位 | 型態 | 內容範例 |
|---|---|---|
| `ids` | string | `"付款方式說明.pdf_chunk_0"` |
| `documents` | string | chunk 的原始文字 |
| `embeddings` | `list[float]` | `[0.023, -0.15, ...]` 共 384 個數字 |
| `metadatas` | dict | `{"source": "付款方式說明.pdf", "chunk_index": 0}` |

重點：**原文和向量都存進去**，查詢時用向量找，找到後把原文傳給 LLM 生成答案。

---

*下一階段：查詢（Retrieval）流程*
