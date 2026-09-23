# CI/CD 開發紀錄 (DevLog)

## [2026-09-23] Docker 建置錯誤與修正：Fastembed 模型名稱問題

### 錯誤情境
在執行 `docker compose up --build` 時，於 Dockerfile 的預先下載模型階段遭遇以下錯誤：
```text
=> ERROR [streamlit 5/6] RUN python -c "from fastembed import TextEmbedding; TextEmbedding('paraphrase-multilingual-MiniLM-L12-v2')"

ValueError: Model paraphrase-multilingual-MiniLM-L12-v2 is not supported in TextEmbedding.Please check the supported models using `TextEmbedding.list_supported_models()`
```

### 問題原因
`fastembed` 套件在較新的版本中，要求初始化模型時必須提供**完整的模型名稱**，也就是需要包含提供者前綴（Provider Prefix）。原先在程式碼與 Dockerfile 中僅填寫了 `paraphrase-multilingual-MiniLM-L12-v2`，導致套件無法辨識該模型並引發 `ValueError`。

### 解決方案
將模型名稱補上正確的前綴 `sentence-transformers/`。
分別修改了以下檔案：
1. **[`Dockerfile`](<../../Dockerfile>)**：修改了 `RUN python -c ...` 指令，將模型名稱改為 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`。
2. **[`app/core/config.py`](<../../app/core/config.py>)**：一併更新了設定檔中 `embedding_model` 的預設值，確保後續容器運行時不會發生錯誤。

---

## [2026-09-23] Phase 2 驗收完成

### 驗收結果

| 項目 | 結果 |
|------|------|
| `docker compose up --build` 成功，6/6 服務全部啟動 | ✅ |
| `http://localhost:8000/docs` 出現 Swagger UI | ✅ |
| `http://localhost:8501` Streamlit 介面正常 | ✅ |
| 上傳文件 → Ctrl+C 停止 → `docker compose up` 重啟 → 文件仍存在（volume 有效） | ✅ |

### Build 摘要

```
✔ Image sideproject-streamlit   Built  111.9s
✔ Image sideproject-api         Built  111.8s
✔ Volume sideproject_chroma_data  Created
✔ Network sideproject_default     Created
✔ Container sideproject-api-1     Created
✔ Container sideproject-streamlit-1  Created
```

---

## 💡 Docker 相關知識點紀錄

### 1. 執行 Docker 指令不需要進入虛擬環境 (venv)
Docker 的核心優勢在於**環境隔離**。當我們執行 `docker compose up` 時，Docker 會完全根據 `Dockerfile` 內的指令，在「獨立的容器內部」建立專屬的 Python 環境並安裝套件（例如透過 `RUN pip install -r requirements.txt`）。
因此，本機端是否處於 `venv` 虛擬環境，甚至本機端有無安裝 Python，都不會影響 Docker 容器的建置與執行。所有的指令只要確保有安裝 Docker 引擎即可順利運行。

### 2. Docker 的快取機制 (Cache)
當我們修改程式碼後重新執行 `docker compose up --build` 時，Docker **不會**每次都從頭開始執行所有步驟。
Docker 採用分層建置 (Layer-based build) 的機制，如果某一層的原始檔案（如 `requirements.txt` 沒有變動）或指令沒有變更，Docker 就會直接使用上一次建置留下來的「快取 (Cache)」。
例如：在這次修復中，我們只修改了 Dockerfile 後半段下載模型的指令，Docker 會聰明地沿用前面 `pip install` 已經安裝好的依賴套件快取，只從被修改的那一行開始重新執行。這大幅節省了重複下載與安裝套件的時間，讓開發與部署的迭代更加快速。
