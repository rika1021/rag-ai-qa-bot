# RAG 架構學習筆記 — 前後端 API 溝通

> 記錄時間：2026-09-11
> 範圍：前端（Streamlit）與後端（FastAPI）之間的 API 設計與溝通方式

---

## 整體架構：兩個獨立進程

```
┌─────────────────────┐         HTTP         ┌─────────────────────┐
│   Streamlit 前端     │  ←──────────────→   │   FastAPI 後端       │
│   port 8501          │                      │   port 8000          │
└─────────────────────┘                      └─────────────────────┘
```

前端和後端是**兩個獨立的 Python 進程**，各自跑在不同 port，透過 **HTTP 請求**溝通。

前端完全不知道 ChromaDB 或 Claude 的存在，它只知道有幾個 HTTP endpoint 可以打。  
ChromaDB 和 Claude 的所有細節，全部封裝在後端內部。

---

## 共有四支 API

### 1. `POST /api/documents/upload` — 上傳文件（觸發 Ingestion）

**前端呼叫方式（`streamlit_app.py:26-30`）：**
```python
requests.post(
    "http://localhost:8000/api/documents/upload",
    files={"file": (file.name, file.getvalue(), file.type)},
    timeout=60,
)
```
傳輸格式為 `multipart/form-data`（二進位檔案上傳的標準格式）。

**後端做什麼（`documents.py:12-27`）：**
1. 檢查副檔名是否合法，只接受 `.pdf`、`.txt`、`.md`，否則回傳 400 錯誤
2. 把檔案寫入 `data/documents/` 資料夾（存實體檔案）
3. 呼叫 `ingest_document()`，觸發完整 Ingestion 流程：
   - chunking（語意切割）
   - embedding（轉向量）
   - 寫入 ChromaDB
4. 回傳結果

**回傳：**
```json
{"filename": "退貨政策說明.pdf", "chunks": 12}
```

**前端收到後：** 顯示「成功上傳，共切成 12 個段落」

---

### 2. `GET /api/documents/` — 列出所有文件

**前端呼叫方式（`streamlit_app.py:39`）：**
```python
requests.get("http://localhost:8000/api/documents/", timeout=10)
```

**後端做什麼（`documents.py:30-32`）：**
去 ChromaDB 撈所有 metadata，取出不重複的 `source` 欄位清單

**回傳：**
```json
{"documents": ["付款方式說明.pdf", "退貨政策說明.txt", "運費與配送說明.md"]}
```

**前端收到後：** 在知識庫管理頁列出所有文件，每筆旁邊附上「刪除」按鈕

---

### 3. `DELETE /api/documents/{filename}` — 刪除文件

**前端呼叫方式（`streamlit_app.py:48`）：**
```python
requests.delete("http://localhost:8000/api/documents/退貨政策說明.pdf", timeout=10)
```

**後端做什麼（`documents.py:35-43`）：**
1. 刪掉 `data/documents/` 裡的實體檔案
2. 呼叫 `delete_document()`，把 ChromaDB 裡這個檔案的所有 chunk 一併刪除

**回傳：**
```json
{"message": "退貨政策說明.pdf 已從知識庫移除"}
```

**前端收到後：** 顯示成功訊息，並重新整理文件列表

---

### 4. `POST /api/chat/` — 使用者提問（觸發 Retrieval + Generator）

**前端呼叫方式（`streamlit_app.py:15`）：**
```python
requests.post(
    "http://localhost:8000/api/chat/",
    json={"message": "我可以退貨嗎？"},
    timeout=120,
)
```
傳輸格式為 `application/json`。

**後端做什麼（`chat.py:15-18`）：**
```python
def chat(body: ChatRequest):
    retrieval = retrieve(body.message)         # Retrieval 階段
    result = generate(body.message, retrieval) # Generator 階段
    return result
```
就兩行，把 Retrieval 和 Generator 串在一起。

**回傳：**
```json
{
  "answer": "根據退貨政策，您需在購買後 7 天內提出申請...",
  "sources": ["退貨政策說明.txt"],
  "confidence": "high"
}
```

**前端收到後：** 顯示回答內容、來源檔案名稱，以及信心標籤

| confidence 值 | 前端顯示 |
|---|---|
| `high` | 🟢 高信心 |
| `low` | 🟡 低信心（建議人工確認） |
| `no_context` | 🔴 知識庫無相關資料 |

---

## 整體溝通流程

### 上傳文件流程

```
使用者在 Streamlit 選擇檔案並點擊上傳
   ↓
POST /api/documents/upload（multipart/form-data）
   ↓
FastAPI：存檔 → ingest_document()
   → chunking → embedding → 寫入 ChromaDB
   ↓
回傳 {"filename": "xxx.pdf", "chunks": 12}
   ↓
Streamlit 顯示「成功上傳，共 12 個段落」
```

### 使用者提問流程

```
使用者在 Streamlit 輸入問題
   ↓
POST /api/chat/（JSON body）
   ↓
FastAPI：retrieve() → generate()
   → embed 問題向量
   → HNSW 查詢 ChromaDB，取前 5 個最近鄰
   → 過濾相似度 < 0.3 的 chunk
   → 組合 prompt（參考文件 + 使用者問題）
   → 呼叫 Claude Haiku API 生成回答
   ↓
回傳 {"answer": "...", "sources": [...], "confidence": "high"}
   ↓
Streamlit 顯示回答 + 來源 + 信心標籤（🟢🟡🔴）
```

---

## API 設計重點整理

| API | Method | 負責觸發 | 前端傳入格式 |
|---|---|---|---|
| `/api/documents/upload` | POST | Ingestion 全流程 | multipart/form-data（檔案） |
| `/api/documents/` | GET | 讀取 ChromaDB metadata | 無 body |
| `/api/documents/{filename}` | DELETE | 刪除檔案 + ChromaDB chunk | 無 body（filename 在 URL） |
| `/api/chat/` | POST | Retrieval + Generator | JSON `{"message": "..."}` |

---

*相關筆記：*
- *[RAG-ingestion-stage.md](RAG-ingestion-stage.md) — chunking、embedding、寫入 ChromaDB*
- *[RAG-retrieval-stage.md](RAG-retrieval-stage.md) — 向量查詢、相似度過濾*
- *[RAG-generator-stage.md](RAG-generator-stage.md) — Prompt 組合、呼叫 Claude、Confidence 機制*
