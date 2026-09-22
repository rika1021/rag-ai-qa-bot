# DEVLOG — RAG 客服機器人開發日誌

記錄開發過程中踩過的坑、決策原因、以及對應的修改。
格式：症狀 → 根本原因 → 解法步驟 → 修改的檔案 → 學到的事

---

## 問題紀錄

---

### [2026-09-08] FastAPI 啟動失敗 — 套件版本連鎖衝突

**症狀**

執行 `uvicorn main:app --reload` 後，出現以下錯誤序列：

第一波錯誤：
```
TypeError: unsupported operand type(s) for |: 'function' and 'NoneType'
```
位置：`vectorstore.py` 第 7 行，`_chroma_client: chromadb.PersistentClient | None = None`

第二波錯誤（修正上述後）：
```
ImportError: cannot import name 'GenerationMixin' from 'transformers.generation'
```
位置：`sentence_transformers/cross_encoder/CrossEncoder.py`

第三波錯誤（升級 sentence-transformers 後）：
```
[transformers] Disabling PyTorch because PyTorch >= 2.5 is required but found 2.2.2
NameError: name 'nn' is not defined
```

**根本原因**

三個問題各自獨立，但連鎖發生：

1. **`chromadb.PersistentClient` 是 function，不是 class**
   Python 的 `X | None` 型別標註語法，要求 `X` 必須是一個型別（class）。
   `chromadb.PersistentClient` 是工廠函式（factory function），不是 class，
   所以 `chromadb.PersistentClient | None` 在執行時會報 `TypeError`。

2. **`transformers 4.57.6` 與 `sentence-transformers 3.1.1` 不相容**
   `sentence-transformers 3.1.1` 是 2024 年底釋出，當時 `transformers` 只到 4.4x 版本。
   `transformers 4.57.6` 把 `GenerationMixin` 移到不同位置，導致舊版 `sentence-transformers` import 失敗。

3. **`torch 2.2.2` 與 `NumPy 2.x` 不相容，且與新版 `sentence-transformers` 也不相容**
   - `torch 2.2.2` 是用 NumPy 1.x 編譯的，無法在 NumPy 2.x 環境下執行
   - 最新版 `sentence-transformers 6.0.1` 需要 `torch >= 2.5`，但安裝的是 2.2.2
   - 升級 `torch` 是個大工程（幾 GB），且會引入更多版本管理複雜度

**解法步驟**

1. **修正型別標註問題**：在 `vectorstore.py` 頂部加入 `from __future__ import annotations`，讓型別標註變成字串（lazy evaluation），不在執行時被求值，避免 `TypeError`。

2. **放棄 `sentence-transformers` + `torch` 整條依賴鏈**：這條路版本地雷太多（torch / numpy / transformers 三方互相約束），對學習專案不值得花時間解。

3. **改用 ChromaDB 內建的 `DefaultEmbeddingFunction`**：
   - 同樣是 `all-MiniLM-L6-v2` 模型
   - 透過 **ONNX Runtime** 執行，完全不需要 PyTorch
   - 沒有 NumPy 版本衝突問題
   - ChromaDB 自己管理模型下載與快取

4. **安裝必要套件**：
   ```bash
   pip uninstall -y sentence-transformers torch
   pip install "chromadb[default]" onnxruntime
   ```

**修改的檔案**

| 檔案 | 修改內容 | 原因 |
|------|----------|------|
| `app/core/vectorstore.py` | 加入 `from __future__ import annotations`；移除 `SentenceTransformer` 相關 import；改用 `DefaultEmbeddingFunction` | 修正型別標註問題、替換 embedding 實作 |
| `requirements.txt` | 移除 `sentence-transformers`；加入 `chromadb[default]`、`onnxruntime` | 反映實際使用的套件 |

**改後的 `vectorstore.py` 核心邏輯**

```python
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

_ef = None

def get_embedding_function():
    global _ef
    if _ef is None:
        _ef = DefaultEmbeddingFunction()  # ONNX 版 all-MiniLM-L6-v2
    return _ef

def embed(texts: list[str]) -> list[list[float]]:
    return get_embedding_function()(texts)
```

**學到的事**

1. **`from __future__ import annotations`** 讓檔案內所有型別標註變成字串，延遲到真正需要時才求值。適合用來解決「型別標註在 runtime 報錯」的問題，是 Python 3.10+ `X | Y` 語法的相容解法。

2. **ONNX Runtime vs PyTorch 做 inference 的差異**：
   - PyTorch：完整的深度學習框架，適合訓練和研究，但很重（幾 GB）
   - ONNX Runtime：微軟開發的推理引擎，只做 inference，輕量快速，不需要 PyTorch
   - 對 RAG 的 embedding 這個使用場景（只做 inference，不訓練），ONNX Runtime 更合適

3. **版本鎖定的重要性**：`sentence-transformers`、`torch`、`transformers`、`numpy` 四者版本必須精確配對。對學習專案，直接使用框架內建的 embedding function 可以避免管理這四個套件版本的複雜度。

4. **`chromadb.PersistentClient` 是工廠函式**：它回傳一個 `chromadb.api.client.Client` 實例，不是 class 本身，所以不能直接用來做型別標註的 class reference。

---

---

### [2026-09-08] 文件上傳 500 錯誤 — ONNX CoreML 執行失敗

**症狀**

前端顯示「上傳失敗：500 Server Error」，FastAPI 終端機出現：

```
onnxruntime.capi.onnxruntime_pybind11_state.Fail: [ONNXRuntimeError] : 1 : FAIL :
Non-zero status code returned while running CoreML node.
Error executing model: Unable to compute the prediction using a neural network model (error code: -1).
```

**根本原因**

`DefaultEmbeddingFunction`（ChromaDB 內建的 ONNX embedding）在 macOS 上預設會嘗試使用 **CoreML ExecutionProvider**（Apple 的硬體加速器）。但目前的 ONNX 模型版本與 macOS 上的 CoreML 不相容，導致模型推理失敗並拋出錯誤。

這不是模型本身的問題，而是 **執行後端選擇** 的問題。ONNX Runtime 支援多種執行後端（CPU、CoreML、CUDA 等），macOS 優先嘗試 CoreML，但失敗了。

**解法步驟**

改用 `ONNXMiniLM_L6_V2`（`DefaultEmbeddingFunction` 的底層 class），並明確指定只使用 CPU：

```python
from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import ONNXMiniLM_L6_V2

_ef = ONNXMiniLM_L6_V2(preferred_providers=["CPUExecutionProvider"])
```

驗證方式：
```bash
python -c "from app.core.vectorstore import embed; r = embed(['測試']); print('向量維度:', len(r[0]))"
# 輸出：向量維度: 384
```

**修改的檔案**

| 檔案 | 修改內容 | 原因 |
|------|----------|------|
| `app/core/vectorstore.py` | 將 `DefaultEmbeddingFunction()` 換成 `ONNXMiniLM_L6_V2(preferred_providers=["CPUExecutionProvider"])` | 強制使用 CPU，跳過失敗的 CoreML 加速器 |

**學到的事**

1. **ONNX Runtime 的 ExecutionProvider 機制**：ONNX Runtime 支援多種硬體後端，macOS 上預設嘗試順序為 CoreML → CPU。`preferred_providers` 參數可以覆蓋這個順序，直接指定要用哪個後端。

2. **`DefaultEmbeddingFunction` vs `ONNXMiniLM_L6_V2`**：前者是後者的別名（alias），但沒有暴露 `preferred_providers` 參數，需要直接使用底層 class 才能控制執行後端。

3. **telemetry 的 WARNING 可以忽略**：`Failed to send telemetry event: capture() takes 1 positional argument but 3 were given` 是 ChromaDB 內部 telemetry（使用統計）的 bug，不影響功能，可以安全忽略。

---

### [2026-09-08] 聊天 500 錯誤 — anthropic SDK 與 httpx 版本不相容

**症狀**

前端輸入問題後顯示「發生錯誤：500 Server Error」，FastAPI 終端機出現：

```
TypeError: Client.__init__() got an unexpected keyword argument 'proxies'
```

位置：`anthropic/_base_client.py`，在建立 `anthropic.Anthropic()` client 時發生。

**根本原因**

`anthropic==0.34.2` 是 2024 年中的舊版，內部使用 `httpx` 時會傳入 `proxies` 參數。
但目前環境安裝的 `httpx >= 0.28.0` 已經移除了 `proxies` 參數，導致初始化 client 時報 `TypeError`。

這是「SDK 版本 vs 依賴套件版本」的不相容問題，與 RAG 邏輯完全無關。

**解法步驟**

直接升級 `anthropic` 到最新版（1.x），新版改用 `httpx2` 且已修正此問題：

```bash
pip install --upgrade anthropic
# 升級結果：anthropic 0.34.2 → 1.4.0
```

**修改的檔案**

| 檔案 | 修改內容 | 原因 |
|------|----------|------|
| `requirements.txt` | `anthropic==0.34.2` → `anthropic>=1.4.0` | 反映實際可用版本，避免未來重新安裝時又裝到舊版 |

**學到的事**

1. **`httpx` 的 `proxies` 參數在 0.28.0 版本被移除**：改成用 `mounts` 參數。舊版 SDK 若寫死 `proxies`，升級 httpx 後就會炸掉。

2. **`anthropic` 0.x vs 1.x 的差異**：1.x 是重大改版，從 `httpx` 換成 `httpx2`（Anthropic fork 的版本），解決了這類依賴衝突。

3. **版本鎖定 (`==`) vs 版本下限 (`>=`) 的取捨**：
   - `==` 鎖定：確保可重現，但容易遇到「鎖定的版本與其他套件打架」的問題
   - `>=` 下限：允許自動升級，適合像 `anthropic` 這種快速迭代的 SDK

---

### [2026-09-08] 聊天請求 Timeout — 首次初始化耗時過長

**症狀**

上傳文件成功後，在聊天框輸入問題，前端顯示：

```
發生錯誤：HTTPConnectionPool(host='localhost', port=8000): Read timed out. (read timeout=30)
```

FastAPI 終端機沒有出現 500 錯誤，代表請求有送到後端，只是處理時間超過 30 秒。

**根本原因**

ONNX Runtime 在 **第一次執行 embedding** 時需要初始化模型（載入權重、建立 session），在 CPU 模式下（我們上一個 issue 強制改成 CPU）這個初始化比較慢，容易超過 Streamlit 預設的 30 秒 timeout。

第二次之後模型已在記憶體中，速度就會正常。

**解法步驟**

把 `streamlit_app.py` 裡 `/api/chat/` 的 timeout 從 30 秒拉長到 120 秒：

```python
# 修改前
response = requests.post(f"{API_BASE}/api/chat/", json={"message": message}, timeout=30)

# 修改後
response = requests.post(f"{API_BASE}/api/chat/", json={"message": message}, timeout=120)
```

修改後重新送出問題，成功回傳答案。第二次問問題速度明顯快很多。

**修改的檔案**

| 檔案 | 修改內容 | 原因 |
|------|----------|------|
| `streamlit_app.py` | `timeout=30` → `timeout=120` | 首次 ONNX 模型初始化在 CPU 模式下需要較長時間 |

**學到的事**

1. **ONNX 模型首次載入比較慢**：第一次呼叫 `embed()` 需要初始化 ONNX session（類似 JIT 編譯），之後就快了。這是「冷啟動」（cold start）問題，在生產環境通常會在啟動時就預熱（warm up）模型。

2. **timeout 要根據場景設定**：30 秒對一般 API 夠用，但涉及 ML 推理或 LLM 呼叫時，首次呼叫可能需要更長時間。

3. **timeout 錯誤 vs 500 錯誤的區別**：
   - **timeout**：請求有送到後端，但後端來不及在限制時間內回應，是前端等不夠久
   - **500**：後端處理時發生例外，是後端程式出錯

---

### [2026-09-10] RAG 品質優化 — 換 Embedding 模型 + 語意切塊

**症狀**

測試三個問題時發現回答品質不穩定：

1. 「配送有哪些機制？」→ 找到對的文件但抓到錯的段落
2. 「介紹會員等級」→ 只回傳邊緣資訊，漏掉核心內容
3. 「說明付款有哪些方式」→ 相關文件完全沒被撈到

**根本原因**

三個問題各自對應不同的根因：

1. **固定字數切塊打斷語意**：原本用 `RecursiveCharacterTextSplitter` 以 500 字為單位切塊，會切在段落中間，導致同一個概念被分散到兩個 chunk，檢索時只撈到其中一半。

2. **英文優先的 embedding 模型對中文理解差**：原本使用 `all-MiniLM-L6-v2`，這個模型以英文資料訓練為主，中文語意相似度計算不準確，導致語意相關的 chunk 在向量空間中距離較遠，無法被撈到。

3. **PDF 頁間分隔符問題**：`pypdf` 抽出 PDF 文字時，頁與頁之間只有 `\n`，如果語意切塊以 `\n\n` 作為段落分界，PDF 文字就整份變成一個大段落，再被固定字數切開，等於語意切塊對 PDF 完全沒有作用。

**解法步驟**

1. **換多語言 Embedding 模型（fastembed）**：
   ```bash
   pip uninstall -y onnxruntime
   pip install fastembed==0.3.6
   ```
   將 embedding 模型從 `ONNXMiniLM_L6_V2`（英文優先）換成 `paraphrase-multilingual-MiniLM-L12-v2`（支援 50+ 語言），透過 `fastembed` 套件執行。

2. **實作語意切塊 `_semantic_chunk()`**：以 `\n\n` 為段落邊界，短段落（< 80 字）與下一段合併，超過 500 字的段落再用 `RecursiveCharacterTextSplitter` 補切。加入合併總長度保護（`len(buffer) + len(para) <= max_size`），避免合併後超過 max_size。

3. **修正 PDF 頁間分隔符**：`_load_document()` 的 PDF 路徑從 `"\n".join(...)` 改成 `"\n\n".join(...)`，讓頁間有明確的段落邊界。

4. **清除舊向量資料並重新上傳**：換模型後向量空間不同，必須刪除 `chroma_db/` 重新建立。

5. **解決 uvicorn `--reload` 反覆重啟問題**：`fastembed` 第一次呼叫會下載模型（~100MB），模型檔案寫入 venv 目錄時觸發 watchfiles，導致 server 不斷重啟、上傳 timeout。解法：先在沒有 server 的情況下預熱模型，再以不帶 `--reload` 的方式啟動：
   ```bash
   python -c "from app.core.vectorstore import get_embed_model; get_embed_model(); print('完成')"
   uvicorn main:app   # 不帶 --reload
   ```

**修改的檔案**

| 檔案 | 修改內容 |
|------|----------|
| `requirements.txt` | 移除 `onnxruntime`，加入 `fastembed==0.3.6` |
| `app/core/vectorstore.py` | 換成 `fastembed.TextEmbedding` + 多語言模型，移除 `embedding_function` 參數，embed 改由 Python 側手動呼叫 |
| `app/core/rag/ingestion.py` | 新增 `_semantic_chunk()`；`_load_document()` PDF 路徑改用 `\n\n` join |
| `app/core/config.py` | `embedding_model` 更新為 `paraphrase-multilingual-MiniLM-L12-v2` |

**`similarity_threshold` 決策紀錄**

換完模型並重新上傳文件後，對三個原本失敗的 query 觀察 top-5 分數分佈：

| Query | 正確文件的分數範圍 | 錯誤文件混入情況 |
|-------|-------------------|-----------------|
| 配送有哪些機制？ | 0.536–0.636 | 無，5/5 全正確 |
| 介紹會員等級 | 0.443–0.557 | 第4筆混入配送文件（0.464） |
| 說明付款有哪些方式 | 0.589、0.603 | 3/5 為配送文件（0.568–0.599） |

**結論**：所有結果的分數都在 0.43 以上，沒有接近 0.30 的低分出現。問題不是閾值太嚴，而是「付款」和「運費/配送」在語意上本身就有重疊（都涉及金額與交易），閾值無法靠調整來區分正確與錯誤的 chunk。`similarity_threshold` **維持 0.30 不動**，主要目標（付款方式 PDF 從完全撈不到 → 出現在 top-2）已達成。

**學到的事**

1. **換 embedding 模型 = 舊向量不能用**：向量的數值意義和產生它的模型綁定，換模型後必須重新 embed 所有文件，舊的向量資料直接刪除。

2. **PDF 文字抽取後的換行格式**：`pypdf` 頁間只有 `\n`，不是 `\n\n`，語意切塊若依賴 `\n\n` 作為段落邊界，就需要在讀取時先做頁間分隔符的預處理。

3. **fastembed 首次呼叫會下載模型**：若在 uvicorn `--reload` 執行期間觸發，下載的檔案會被 watchfiles 偵測為「程式碼變動」，導致 server 不斷重啟。開發期間的解法是先預熱模型再啟動 server，或使用 `--reload-dir app` 限縮監看範圍。

4. **語意切塊的合併邏輯需要總長度保護**：短段落合併時若只檢查 buffer 長度而不檢查合併後的總長度，可能把短 buffer 和超長段落合在一起，反而讓後續的固定字數切法更難保留語意完整性。

### [2026-09-10] RAG 系統功能驗證 — 四個問題測試結果

**測試目的**

確認 RAG 優化（換多語言 Embedding 模型 + 語意切塊）後，系統能正確回答各類型的客服問題。

**測試問題與結果摘要**

| # | 問題 | 結果 | 來源文件 | 信心度 |
|---|------|------|----------|--------|
| 1 | 怎麼樣可以成為會員？ | 正確回答銅卡免費註冊、銀/金/鑽石升等消費門檻 | 會員制度與等級說明.md | 低信心（建議人工確認） |
| 2 | 付款方式有哪些？ | 正確列出 LINE Pay、Apple Pay、樂購錢包、信用卡 | 付款方式說明.pdf、運費與配送說明.md | 低信心（建議人工確認） |
| 3 | 退貨退款有哪些要注意的事 | 正確說明部分退貨注意事項、退貨被拒絕常見原因 | 退貨政策說明.txt | 高信心 |
| 4 | 國定假期可以正常收到包裹嗎？ | 正確說明文件僅涵蓋春節安排，誠實回答無法回答其他國定假期 | 運費與配送說明.md、退貨政策說明.txt | 低信心（建議人工確認） |

**結果截圖路徑**

```
/Users/huangshimin/Desktop/rika/面試/sideproject/結果照片/
```

**觀察**

- 四個問題全數成功回答，RAG 優化後的核心功能驗證通過。
- 第 4 題「國定假期」的回答品質特別好：文件只記載春節安排，系統沒有硬掰答案，而是誠實告知「根據現有文件無法提供完整回答」，這是正確的 RAG 行為。
- 「低信心（建議人工確認）」是系統設計的信心度標示，非錯誤，代表 RAG 找到相關文件但語意匹配分數未達高信心門檻。

<!-- 新的問題紀錄請往下新增，保持時間順序 -->
