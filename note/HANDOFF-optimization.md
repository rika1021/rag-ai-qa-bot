# RAG 品質優化交接文件

> 這份文件是在 session 過長之前寫的交接紀錄。
> 新 session 直接從「實作步驟」開始，不需要重新討論背景。

---

## 專案位置

```
/Users/huangshimin/Desktop/rika/面試/sideproject/
```

虛擬環境：`venv/`（已建立）

啟動指令：
```bash
cd /Users/huangshimin/Desktop/rika/面試/sideproject
source venv/bin/activate
uvicorn main:app --reload          # 終端機 1
streamlit run streamlit_app.py     # 終端機 2
```

---

## 背景：為什麼要優化

測試時發現三類回答品質問題：

| 問題 | 症狀 | 根因 |
|------|------|------|
| 「配送有哪些機制？」 | 找到對的文件但抓到錯的段落 | 固定字數切塊打斷了語意 |
| 「介紹會員等級」 | 只回傳邊緣資訊，漏掉核心內容 | 同上 |
| 「說明付款有哪些方式」 | 相關文件完全沒被撈到 | 英文優先 embedding 對中文語意理解差 |

決定實作三個優化方向：
- **A** — 語意切塊（paragraph-aware chunking）
- **B** — 換中文 Embedding 模型
- **E** — 降低相似度閾值（0.30 → 0.20）

---

## 實作步驟（按順序執行）

### ⚠️ 重要提示：B 換完 Embedding 模型後，舊的向量資料必須清除

向量是和模型綁定的，換模型 = 向量空間不同 = 舊資料無法使用。
實作完 B 之後，**必須刪掉 `chroma_db/` 資料夾，重啟後重新上傳所有文件**。

---

### 步驟 1：安裝套件

```bash
source venv/bin/activate
pip uninstall -y onnxruntime
pip install fastembed==0.3.6
```

---

### 步驟 2：修改 `requirements.txt`

把：
```
onnxruntime
```
換成：
```
fastembed==0.3.6
```

---

### 步驟 3：修改 `app/core/vectorstore.py`

把整個檔案換成：

```python
from __future__ import annotations

import chromadb
from chromadb.config import Settings as ChromaSettings
from fastembed import TextEmbedding

from app.core.config import settings

_chroma_client = None
_embed_model = None
COLLECTION_NAME = "knowledge_base"


def get_chroma_client():
    global _chroma_client
    if _chroma_client is None:
        _chroma_client = chromadb.PersistentClient(
            path=str(settings.chroma_dir),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
    return _chroma_client


def get_embed_model():
    global _embed_model
    if _embed_model is None:
        _embed_model = TextEmbedding(
            model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        )
    return _embed_model


def get_collection():
    client = get_chroma_client()
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def embed(texts: list[str]) -> list[list[float]]:
    model = get_embed_model()
    return [v.tolist() for v in model.embed(texts)]
```

**和舊版的差異**：
- `ONNXMiniLM_L6_V2` → `fastembed.TextEmbedding`（多語言模型）
- `get_collection()` 移除 `embedding_function` 參數（改由 Python 側手動 embed）
- `embed()` 需要 `.tolist()` 把 numpy array 轉成 list

---

### 步驟 4：修改 `app/core/rag/ingestion.py`

把整個檔案換成：

```python
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

from app.core.config import settings
from app.core.vectorstore import embed, get_collection


def _load_document(file_path: Path) -> str:
    if file_path.suffix.lower() == ".pdf":
        reader = PdfReader(str(file_path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    return file_path.read_text(encoding="utf-8")


def _semantic_chunk(text: str) -> list[str]:
    """
    以段落（雙換行）為單位切塊，保留語意完整性。
    太短的段落和下一段合併；超過 max_size 的段落再用 RecursiveCharacterTextSplitter 切。
    """
    max_size = settings.chunk_size      # 500
    overlap = settings.chunk_overlap    # 50
    min_paragraph = 80

    raw_paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    merged: list[str] = []
    buffer = ""
    for para in raw_paragraphs:
        if not buffer:
            buffer = para
        elif len(buffer) < min_paragraph:
            buffer = buffer + "\n\n" + para
        else:
            merged.append(buffer)
            buffer = para
    if buffer:
        merged.append(buffer)

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=max_size, chunk_overlap=overlap
    )
    final_chunks: list[str] = []
    for para in merged:
        if len(para) > max_size:
            final_chunks.extend(splitter.split_text(para))
        else:
            final_chunks.append(para)

    return final_chunks


def _make_chunk_id(filename: str, index: int) -> str:
    return f"{filename}_chunk_{index}"


def ingest_document(file_path: Path) -> int:
    raw_text = _load_document(file_path)
    chunks = _semantic_chunk(raw_text)

    if not chunks:
        return 0

    filename = file_path.name
    ids = [_make_chunk_id(filename, i) for i in range(len(chunks))]
    metadatas = [{"source": filename, "chunk_index": i} for i in range(len(chunks))]
    embeddings = embed(chunks)

    collection = get_collection()

    existing = collection.get(where={"source": filename})
    if existing["ids"]:
        collection.delete(where={"source": filename})

    collection.add(
        ids=ids,
        documents=chunks,
        embeddings=embeddings,
        metadatas=metadatas,
    )

    return len(chunks)


def delete_document(filename: str) -> None:
    collection = get_collection()
    collection.delete(where={"source": filename})


def list_documents() -> list[str]:
    collection = get_collection()
    result = collection.get(include=["metadatas"])
    seen: set[str] = set()
    for meta in result["metadatas"]:
        seen.add(meta["source"])
    return sorted(seen)
```

**和舊版的差異**：
- 新增 `_semantic_chunk()` 函式
- `ingest_document()` 裡改呼叫 `_semantic_chunk()` 而不是 `RecursiveCharacterTextSplitter`

---

### 步驟 5：修改 `app/core/config.py`

兩個地方改：

```python
embedding_model: str = "paraphrase-multilingual-MiniLM-L12-v2"   # 原本是 all-MiniLM-L6-v2
similarity_threshold: float = 0.20   # 原本是 0.30
```

---

### 步驟 6：清除舊向量資料並重新上傳

```bash
# 停止 uvicorn（Ctrl+C）
rm -rf chroma_db/
uvicorn main:app --reload    # 重新啟動
```

然後開 Streamlit，在 Tab2「知識庫管理」重新上傳所有文件。

---

### 步驟 7：驗證

**驗證 embedding 正常（終端機執行）**：
```bash
source venv/bin/activate
python -c "from app.core.vectorstore import embed; r = embed(['退貨要幾天內申請？']); print('向量維度:', len(r[0]))"
# 期待輸出：向量維度: 384
```

**驗證問答品質**：
1. 「配送有哪些機制？」→ 應能找到 `運費與配送說明.md` 的核心段落
2. 「介紹會員等級」→ 應能找到等級說明的完整段落
3. 「說明付款有哪些方式」→ 應能從 `付款方式說明.pdf` 取得結果

---

### 步驟 8：記錄到 DEVLOG.md

優化結果（成功或失敗）都要記錄到 `DEVLOG.md`，格式和之前四個 error 記錄一致。

---

## 不需要修改的檔案

- `app/core/rag/retrieval.py` — 已自動讀 `settings.similarity_threshold`，不用動
- `app/core/rag/generator.py` — 不用動
- `app/api/routes/chat.py` — 不用動
- `app/api/routes/documents.py` — 不用動
- `main.py` — 不用動
- `streamlit_app.py` — 不用動

---

## 修改的檔案總覽

| 檔案 | 修改內容 |
|------|----------|
| `requirements.txt` | 移除 `onnxruntime`，加入 `fastembed==0.3.6` |
| `app/core/vectorstore.py` | 換成 `fastembed.TextEmbedding` + 多語言模型，移除 `embedding_function` 參數 |
| `app/core/rag/ingestion.py` | 新增 `_semantic_chunk()`，取代 `RecursiveCharacterTextSplitter` 直接呼叫 |
| `app/core/config.py` | `similarity_threshold` 0.30 → 0.20，更新 `embedding_model` 字串 |

---

## 可能遇到的問題

**問：`fastembed` 安裝後 import 失敗**
答：確認虛擬環境有啟動（`source venv/bin/activate`），以及 pip 指向 venv 內的版本。

**問：第一次 embed 很慢**
答：`fastembed` 第一次呼叫會下載模型（約 100MB），正常現象，之後就快了。
如果 Streamlit timeout，把 `streamlit_app.py` 裡的 `timeout=120` 改成 `timeout=300`。

**問：embed 後向量維度不是 384**
答：`paraphrase-multilingual-MiniLM-L12-v2` 正確維度是 384。如果不是，代表模型名稱有誤，回頭確認步驟 3 的 `model_name` 字串。

**問：上傳文件後 ChromaDB 顯示 0 chunk**
答：可能是 `_semantic_chunk()` 的段落切法對 PDF 效果差（PDF 抽取出來的文字可能沒有 `\n\n`）。
臨時解法：把 PDF 的 `\n` 也當成分隔符，在 `_semantic_chunk()` 裡改成 `text.split("\n\n") or text.split("\n")`。
