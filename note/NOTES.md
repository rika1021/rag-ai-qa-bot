# RAG 客服機器人 學習筆記

---

## 目錄

1. [什麼是 RAG](#一什麼是-rag)
2. [核心概念：Embedding](#二核心概念embedding)
3. [專案架構總覽](#三專案架構總覽)
4. [檔案逐一說明](#四檔案逐一說明)
5. [完整流程走一遍](#五完整流程走一遍)
6. [重要設計決策筆記](#六重要設計決策筆記)
7. [啟動指南](#七啟動指南)

---

## 一、什麼是 RAG

**RAG = Retrieval-Augmented Generation（檢索增強生成）**

### 問題背景

直接問 LLM（如 Claude）時，它只能用訓練時學到的知識回答。
它不知道你公司的退貨政策、你的產品手冊、你的內部文件。

### RAG 的解法

先把你的文件存成可搜尋的向量，使用者提問時：
1. 先去文件裡找最相關的段落（Retrieval）
2. 把段落交給 LLM，讓它根據這些段落回答（Generation）

```
使用者問題
    ↓
去知識庫找相關段落
    ↓
把段落 + 問題一起送給 Claude
    ↓
Claude 根據段落回答（不能憑空捏造）
```

### 為什麼不用關鍵字搜尋就好？

| | 關鍵字搜尋 | RAG（向量搜尋）|
|--|-----------|--------------|
| "退貨" → 找含"退貨"的文件 | ✓ 找到 | ✓ 找到 |
| "我買錯了想還" → 找退貨相關 | ✗ 找不到（沒有"退貨"這個字）| ✓ 找到（語意相近）|
| "return policy" → 找中文退貨文件 | ✗ 找不到 | ✓ 多語言模型可以找到 |

向量搜尋的優勢：**理解語意，不依賴字面相符**。

---

## 二、核心概念：Embedding

### 什麼是 Embedding？

把文字轉成一串數字（向量），讓電腦能計算「兩段文字有多像」。

```
"退貨流程是什麼？"  →  [0.12, -0.34, 0.87, ...]  （384 個數字）
"如何申請退款？"    →  [0.11, -0.31, 0.85, ...]  （384 個數字）
"今天天氣很好"      →  [0.90, 0.42, -0.11, ...]  （384 個數字）
```

語意相近的句子 → 數字很像 → 向量距離近
語意無關的句子 → 數字差很多 → 向量距離遠

### 用「地圖座標」理解

想像每個句子都是地圖上的一個點：

```
        退換貨區域
        ● "退貨流程是什麼？"
        ● "如何申請退款？"
        ● "換貨需要什麼文件？"


                        天氣區域
                        ● "今天天氣很好"
                        ● "明天會下雨嗎？"
```

使用者提問時，把問題也轉成向量（座標），找**距離最近的點**，那些就是最相關的 chunk。

### 向量距離計算：餘弦相似度

```
相似度 = 1    → 完全一樣（夾角 0°）
相似度 = 0    → 完全無關（夾角 90°）
相似度 = -1   → 完全相反（夾角 180°）
```

ChromaDB 回傳的是「距離」，需要換算：
```
相似度 = 1 - 距離
```

### 關鍵原則

查詢和文件必須用**同一個 embedding 模型**，語意才能對齊。
本專案使用：`all-MiniLM-L6-v2`（本地執行，免費，384 維向量）

---

## 三、專案架構總覽

### 檔案結構

```
sideproject/
├── app/
│   ├── api/
│   │   └── routes/
│   │       ├── chat.py        # POST /api/chat
│   │       └── documents.py   # 文件上傳、列出、刪除
│   └── core/
│       ├── config.py          # 所有設定值的統一來源
│       ├── vectorstore.py     # ChromaDB + Embedding 模型的統一入口
│       └── rag/
│           ├── ingestion.py   # 文件解析 → 切塊 → embedding → 存入 ChromaDB
│           ├── retrieval.py   # 向量查詢 → 過濾 → 回傳相關 chunk
│           └── generator.py   # 組合 prompt → 呼叫 Claude → 回傳答案
├── data/documents/            # 上傳的原始文件存放處
├── chroma_db/                 # ChromaDB 向量資料存放處（自動產生）
├── main.py                    # FastAPI 入口，組裝所有路由
├── streamlit_app.py           # Streamlit 前端介面
├── requirements.txt
├── .env                       # 放 ANTHROPIC_API_KEY（不要上傳 git）
└── .env.example               # 範本
```

### 各層關係圖

```
streamlit_app.py（前端）
        │  HTTP 請求
        ▼
main.py（FastAPI 入口）
        ├── /api/documents → documents.py
        │           └── ingestion.py
        │                   └── vectorstore.py → ChromaDB
        └── /api/chat      → chat.py
                    ├── retrieval.py
                    │       └── vectorstore.py → ChromaDB
                    └── generator.py
                            └── Claude API（Anthropic）
```

---

## 四、檔案逐一說明

### `config.py`
**目的**：所有設定值的統一來源，整個專案只有這一個地方需要改參數。

關鍵設定：
- `embedding_model`：使用哪個 embedding 模型
- `claude_model`：使用哪個 Claude 模型
- `chunk_size`：每個 chunk 最大字元數（500）
- `chunk_overlap`：相鄰 chunk 重疊字元數（50）
- `retrieval_top_k`：每次搜尋取回幾個 chunk（5）
- `similarity_threshold`：相似度門檻，低於此值不回答（0.30）

---

### `vectorstore.py`
**目的**：ChromaDB 和 Embedding 模型的統一入口，採用 Singleton 模式，確保整個程式生命週期只建立一次連線。

**Singleton 模式**：全域變數初始為 `None`，第一次呼叫時才真正建立，之後重複使用同一個實例。避免每次呼叫都重新載入 80MB 的模型。

```
get_chroma_client()  → PersistentClient（資料存硬碟，重啟不消失）
get_embedding_model() → SentenceTransformer（載入一次重複使用）
get_collection()     → ChromaDB collection（類似資料表）
embed(texts)         → 把文字列表轉成向量列表
```

**ChromaDB 資料結構**：

| 欄位 | 說明 |
|------|------|
| `id` | 唯一識別碼，如 `FAQ.txt_chunk_0` |
| `document` | chunk 的原始文字 |
| `embedding` | 向量（384 個浮點數） |
| `metadata` | 附加標籤，如 `{"source": "FAQ.txt", "chunk_index": 0}` |

**metadata 的作用**：不參與相似度計算，但用來過濾查詢和顯示來源文件名稱。

---

### `ingestion.py`
**目的**：把原始文件轉換成可被搜尋的向量資料，存入 ChromaDB。

**完整流程**：
```
原始文件（PDF / TXT / MD）
    ↓ _load_document()
解析成純文字
    ↓ RecursiveCharacterTextSplitter
切成小 chunk（500字元，overlap 50字元）
    ↓ embed()
每個 chunk → 384 維向量
    ↓ collection.add()
存入 ChromaDB（含 document、embedding、metadata）
    ↓
回傳 chunk 數量
```

**Overlap（重疊）的作用**：避免一個句子被切斷在兩個 chunk 的邊界導致語意破碎。

```
Chunk 1: [...句子A  句子B  句子C]
Chunk 2:          [句子B  句子C  句子D...]
                    ↑ 這段重疊（50字元）
```

**重複上傳同名檔案**：會先刪除舊資料再重新存入，避免重複 chunk 污染搜尋結果。

---

### `retrieval.py`
**目的**：把使用者問題轉成向量，去 ChromaDB 找相關 chunk，並判斷是否達到相似度門檻。

**回傳資料結構（RetrievalResult）**：
```python
RetrievalResult(
    found=True,           # 是否找到相關內容
    chunks=["退貨需在7天內...", "換貨請攜帶收據..."],  # 達標的 chunk 原文
    sources=["FAQ.txt"],  # 來源文件（去重後）
    top_score=0.85,       # 最高相似度分數
)
```

**過濾策略（重要設計決定）**：
- **每筆個別判斷**，只保留相似度 >= 0.30 的 chunk
- 不是只看最高分當門檻，讓所有 chunk 一起進去
- 這樣能避免把不相關的 chunk 塞進 context 給 Claude

```
top-5 結果：distances = [0.15, 0.80, 0.85, 0.77, 0.95]
              similarity = [0.85, 0.20, 0.15, 0.23, 0.05]
              閾值 0.30 過濾後 → 只保留第 1 筆（0.85）
```

**為什麼 ChromaDB 一定要過濾**：ChromaDB 不管相不相關一定會回傳結果（它只是找最近的點），所以必須自己判斷相似度是否夠高。

---

### `generator.py`
**目的**：收到 retrieval 的結果，組合 prompt，呼叫 Claude 生成答案。

**System Prompt（防幻覺的核心）**：
```
你只能根據下方【參考文件】的內容來回答。
如果文件不足以回答，請說「根據現有文件，我無法回答這個問題。」
絕對不可以自行推測或使用文件以外的知識。
```

**User Prompt 結構**：
```
【參考文件】
第 1 段：退貨需在購買後 7 天內提出申請...
第 2 段：換貨請攜帶原始收據...

【使用者問題】
退貨要幾天內申請？
```

**參考文件 = retrieval 篩選後的 chunks**，Claude 看到的東西完全由 retrieval 決定，retrieval 篩掉什麼，Claude 就永遠不知道那段內容存在。

**信心度判斷**：
```
top_score >= 0.7   → "high"（高信心）
top_score >= 0.3   → "low"（低信心）
found = False      → "no_context"（無相關資料）
```

---

### `documents.py`（API 路由）
**目的**：把文件相關的操作對外開放成 HTTP 端點。

| 端點 | 作用 |
|------|------|
| `POST /api/documents/upload` | 上傳文件，呼叫 ingestion pipeline |
| `GET /api/documents/` | 列出知識庫所有文件 |
| `DELETE /api/documents/{filename}` | 刪除文件（硬碟 + ChromaDB 都刪）|

---

### `chat.py`（API 路由）
**目的**：接收使用者問題，串接 retrieval 和 generator，回傳答案。

```python
POST /api/chat/
Request:  { "message": "退貨要幾天內申請？" }
Response: { "answer": "...", "sources": ["FAQ.txt"], "confidence": "high" }
```

**`BaseModel` 的作用**：FastAPI + Pydantic 自動驗證請求格式，少傳欄位或型別錯誤會直接回 400，不需要自己寫驗證邏輯。

---

### `main.py`
**目的**：FastAPI 應用的入口，把所有路由組裝在一起。

**CORS 是什麼**：瀏覽器的安全規則，不同來源（不同 port）的網頁預設不能互相請求資料。Streamlit（8501）呼叫 FastAPI（8000）需要設定 CORS 才不會被擋。

**`include_router` + `prefix`**：幫路由加上統一前綴，`documents.py` 裡的 `/upload` 加上 prefix `/api/documents` 後變成 `/api/documents/upload`。

---

### `streamlit_app.py`
**目的**：純 Python 寫的前端介面，兩個 Tab。

**Streamlit 最重要的觀念**：每次使用者互動（點按鈕、輸入文字），整個 Python 檔案會從頭重新執行一次，所以用 `st.session_state` 保存需要跨次執行的資料（例如聊天歷史）。

---

## 五、完整流程走一遍

### 上傳文件（Ingestion Pipeline）

```
使用者在 Tab2 選擇 FAQ.txt，點「上傳至知識庫」

streamlit_app.py
    → POST /api/documents/upload（帶檔案）

documents.py
    → 檢查副檔名合法
    → 把檔案存到 data/documents/FAQ.txt

ingestion.py: ingest_document()
    → _load_document()：直接讀文字
    → RecursiveCharacterTextSplitter：切成 N 個 chunk
    → embed(chunks)：每個 chunk → 向量

vectorstore.py: embed()
    → SentenceTransformer.encode()
    → 回傳向量列表

ingestion.py
    → collection.add()：存入 ChromaDB
    → 回傳 chunk 數量

streamlit_app.py
    → 顯示「成功上傳 FAQ.txt，共切成 12 個段落」
```

### 使用者提問（Retrieval + Generation）

```
使用者在 Tab1 輸入「退貨要幾天內申請？」

streamlit_app.py
    → POST /api/chat/ { "message": "退貨要幾天內申請？" }

chat.py
    → retrieve("退貨要幾天內申請？")

retrieval.py: retrieve()
    → embed(["退貨要幾天內申請？"])：問題 → 向量
    → collection.query()：ChromaDB 相似度搜尋
    → 取回 top-5，各別計算 similarity = 1 - distance
    → 過濾掉 similarity < 0.30 的 chunk
    → 回傳 RetrievalResult(found=True, chunks=[...], sources=["FAQ.txt"], top_score=0.85)

chat.py
    → generate("退貨要幾天內申請？", retrieval)

generator.py: generate()
    → 組合 User Prompt（參考文件 + 使用者問題）
    → 呼叫 Claude API（帶嚴格 system prompt）
    → 回傳 { "answer": "退貨需在 7 天內...", "sources": ["FAQ.txt"], "confidence": "high" }

streamlit_app.py
    → 顯示答案
    → 顯示「來源：FAQ.txt　🟢 高信心」
```

---

## 六、重要設計決策筆記

### 1. 防幻覺雙重保險

```
第一道：retrieval.py
    相似度 < 0.30 → 直接回「無法回答」，不進入 Claude

第二道：generator.py system prompt
    就算進了 Claude，明確命令它「只能根據文件回答」
```

兩道加在一起，讓「不知道就說不知道」的行為更可靠。

### 2. 為什麼用個別過濾而非 top_score 門檻

**原本設計（有缺陷）**：只看最高分 >= 0.30，就把 top-5 全部傳給 Claude。
**問題**：第 2~5 名可能分數很低（0.05~0.23），塞進 context 是雜訊。

```
distances:    [0.15,  0.80,  0.85,  0.77,  0.95]
similarity:   [0.85,  0.20,  0.15,  0.23,  0.05]
```

**改進後設計**：每筆個別判斷，只保留 >= 0.30 的 chunk。
**原則**：垃圾進，垃圾出。Context 越乾淨，Claude 回答越可靠。

### 3. 字元數 vs Token 切塊

本專案用字元數（characters）切塊，不是 token。

**什麼時候字元數切塊會有問題**：
- 文件語言混合（英文一個單字 ≈ 4~5 字元但只占 1 token，中文 1 字元 ≈ 1 token），同樣 500 字元，英文 chunk 實際只有 80~100 token，資訊密度偏低
- 使用 context window 較小的模型（4K、8K），可能超出限制

**本專案影響小的原因**：主要處理中文（字元數 ≈ token 數），Claude Haiku 有 200K context 完全不怕超限。

### 4. ChromaDB metadata 的用途

metadata 是附加在每筆資料上的標籤，**不參與相似度計算**，用途是：
1. 顯示來源：搜到結果後知道「這筆資料從哪個文件來的」
2. 過濾查詢：可以限制只搜某份文件裡的內容

```
每筆資料長這樣：
├── id:        "FAQ.txt_chunk_0"
├── document:  "退貨需在購買後 7 天內提出申請..."
├── embedding: [0.12, -0.34, 0.87, ...]
└── metadata:  {"source": "FAQ.txt", "chunk_index": 0}
```

---

## 七、啟動指南

### 前置準備

```bash
# 1. 建立 .env 並填入 API Key
cp .env.example .env
# 編輯 .env，填入 ANTHROPIC_API_KEY=sk-ant-api03-...

# 2. 安裝套件
pip install -r requirements.txt
```

### 啟動服務（需要兩個終端機視窗）

**終端機 1 — FastAPI 後端：**
```bash
uvicorn main:app --reload
```

**終端機 2 — Streamlit 前端：**
```bash
streamlit run streamlit_app.py
```

### 打開瀏覽器

| 網址 | 用途 |
|------|------|
| `http://localhost:8501` | Streamlit 聊天介面 |
| `http://localhost:8000/docs` | FastAPI 自動產生的 API 測試頁面 |

### 測試流程

1. 準備一份 TXT 知識庫文件（例如假的 FAQ）
2. 在 Tab2 上傳文件
3. 在 Tab1 問一個**文件中有的問題** → 應回答正確並顯示來源
4. 在 Tab1 問一個**文件中完全沒有的問題** → 應明確說無法回答，不捏造

### 取得 Anthropic API Key

1. 前往 [console.anthropic.com](https://console.anthropic.com) 註冊
2. 進入 **API Keys** 頁面建立 Key
3. 新帳號通常有 $5 美元免費額度，學習用完全夠
4. 本專案使用 Claude Haiku 4.5，每次問答費用約 $0.001~0.002 美元
