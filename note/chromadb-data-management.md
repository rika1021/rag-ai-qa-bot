# ChromaDB 資料管理

---

## 一、切塊觸發時機

### 只有透過上傳 API 才會觸發

切塊（chunking）→ embedding → 存入 ChromaDB 的流程，**只有**在你透過介面或 API 上傳檔案時才會觸發：

```
使用者點「上傳至知識庫」
    ↓
POST /api/documents/upload
    ↓
documents.py → ingest_document() 被呼叫
    ↓
切塊 → embedding → 存入 ChromaDB
```

### 直接修改 `data/documents/` 不會觸發

`data/documents/` 只是存放原始檔案的資料夾。你在裡面修改或新增檔案，ChromaDB **完全不知道**，機器人還是會用舊的向量內容回答。

### 操作對照表

| 操作 | ChromaDB 會更新嗎？ |
|------|-------------------|
| 透過介面點「上傳至知識庫」 | ✅ 會 |
| 重新上傳同名檔案 | ✅ 會（先刪舊的再存新的，不會重複）|
| 直接修改 `data/documents/` 裡的檔案 | ❌ 不會 |
| 直接把新檔案複製進 `data/documents/` | ❌ 不會 |

---

## 二、正確的修改文件流程

如果你要更新知識庫裡的文件內容：

```
✅ 正確做法：
1. 在本機修改文件內容（存成新的 .txt / .pdf）
2. 回到 Streamlit Tab2「知識庫管理」
3. 重新上傳這份檔案

❌ 錯誤做法：
直接打開 data/documents/FAQ.txt 改內容
→ ChromaDB 裡還是舊的向量，機器人答案不會更新
```

**重新上傳同名檔案是安全的**：`ingestion.py` 裡有做保護，發現同名檔案已存在時，會先刪除舊的所有 chunk，再存入新的：

```python
# ingestion.py 的邏輯
existing = collection.get(where={"source": filename})
if existing["ids"]:
    collection.delete(where={"source": filename})  # 先刪舊的

collection.add(...)  # 再存新的
```

---

## 三、如何查看 ChromaDB 裡存的內容

### 用 Python Shell 查看（最直接）

啟動虛擬環境後進入 Python shell：

```bash
source venv/bin/activate
python3
```

然後執行：

```python
from app.core.vectorstore import get_collection

col = get_collection()

# 看總共有幾個 chunk
print("總 chunk 數：", col.count())

# 看前 5 筆的原文和 metadata
result = col.get(limit=5, include=["documents", "metadatas"])

for doc, meta in zip(result["documents"], result["metadatas"]):
    print("---")
    print(f"來源：{meta['source']}，第 {meta['chunk_index']} 塊")
    print(f"內容：{doc[:120]}...")
```

範例輸出：
```
總 chunk 數：12
---
來源：FAQ.txt，第 0 塊
內容：退貨政策

1. 退貨期限：商品購買後 7 天內可申請退貨。
2. 退貨條件：商品須保持原始包裝，且未使用過。...
---
來源：FAQ.txt，第 1 塊
內容：3. 退貨流程：請聯繫客服信箱 support@example.com，附上訂單編號與退貨原因。
4. 退款時間：退貨審核通過後...
```

### 可以看到什麼？看不到什麼？

| | 能看到嗎？ |
|--|-----------|
| 每個 chunk 的原始文字 | ✅ 可以 |
| 來源檔名（source）| ✅ 可以 |
| chunk 編號（chunk_index）| ✅ 可以 |
| 向量本身（384 個浮點數）| ⚠️ 技術上可以，但沒有意義，人看不懂 |

查看向量的方式（純好奇用）：

```python
result = col.get(limit=1, include=["embeddings"])
print(result["embeddings"][0][:10])  # 只印前 10 個數字
# 輸出類似：[0.123, -0.456, 0.789, ...]
```

### 查看特定文件的所有 chunk

```python
result = col.get(
    where={"source": "FAQ.txt"},
    include=["documents", "metadatas"]
)
print(f"FAQ.txt 共有 {len(result['documents'])} 個 chunk")
```

---

## 四、ChromaDB 資料存在哪裡？

向量資料存在專案根目錄的 `chroma_db/` 資料夾，是持久化的（PersistentClient），重啟服務後資料不會消失。

```
sideproject/
└── chroma_db/       ← ChromaDB 的資料檔案存在這裡
    └── ...（二進位格式，不能直接用文字編輯器開）
```

如果你想**清空所有向量資料**重新開始，直接刪除整個 `chroma_db/` 資料夾，下次啟動時 ChromaDB 會自動重新建立空的資料庫。
