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

## [2026-09-23] Phase 3 CI 第二次失敗：ModuleNotFoundError: No module named 'dotenv'

### 錯誤情境

修完 ruff 的 12 個 lint 錯誤後再次 push，CI 這次過了 `Lint (ruff)` step，
但在 `Run tests` step 又失敗了。

### 如何從 log 判斷問題

用 `gh run view <run-id> --log-failed` 看失敗的詳細 log，
讀 log 的方法：**從最底下的 `E` 或 `Error:` 行開始往上看**。

```
tests/conftest.py:3: in <module>       ← 錯誤發生的位置（conftest.py 第 3 行）
    from dotenv import load_dotenv     ← 觸發錯誤的那行程式碼
E   ModuleNotFoundError: No module named 'dotenv'  ← 錯誤是什麼
```

兩個資訊定位問題：
1. **錯誤是什麼**：`ModuleNotFoundError` = Python 找不到這個模組，代表套件沒被安裝
2. **在哪觸發**：`conftest.py:3` 在 `from dotenv import load_dotenv`

### 問題原因

CI 的安裝步驟只有：
```yaml
- run: pip install -r requirements-eval.txt
```

`python-dotenv` 存在於 `requirements.txt`（給 app 用），但不在 `requirements-eval.txt`（給 CI 測試用）。
`conftest.py` 需要 `dotenv` 載入 `.env`，所以 CI 環境中找不到這個套件。

### 解法

在 `requirements-eval.txt` 加入：
```
python-dotenv>=1.0.0
```

### 為什麼 Docker 不需要重 build？

`requirements-eval.txt` 只有 CI 在用，Docker 用的是 `requirements.txt`，
`Dockerfile` 裡只有 `COPY requirements.txt .` 和 `RUN pip install -r requirements.txt`，
兩者完全獨立，改 eval 的依賴不影響 image。

### 修改的檔案

- `requirements-eval.txt` — 加入 `python-dotenv>=1.0.0`

### 最終結果

第三次 push 後，CI 全部通過：

```
✓  add python-dotenv to requirements-eval.txt  CI  dev  push  1m53s
```

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

## [2026-09-23] Phase 3 CI 首次觸發：ruff lint 12 個錯誤

### 錯誤情境

push `ci.yml` 到 `dev` branch 後，GitHub Actions 的 `Lint (ruff)` step 失敗，
找到 12 個錯誤，CI 紅燈，`build` job 因 `needs: test` 沒有跑。

### 錯誤分類與解法

**類型一：Import 順序錯誤（I001）— 5 個檔案**

ruff 要求 import 必須按照這個順序，且群組之間用空行分隔：
1. stdlib（Python 內建）：`import os`、`from pathlib import Path`
2. third-party（pip 安裝的）：`import pytest`、`from pydantic_settings import ...`

受影響檔案與修法（全部都是加一個空行分隔）：

| 檔案 | 修法 |
|------|------|
| `tests/test_regression.py` | `json`、`pathlib` 與 `pytest` 之間加空行 |
| `tests/conftest.py` | `pathlib` 與 `dotenv` 之間加空行 |
| `app/core/config.py` | `pathlib` 與 `pydantic_settings` 之間加空行 |
| `streamlit_app.py` | `os` 與 `requests`、`streamlit` 之間加空行 |

**類型二：可簡化的 if（PLR1730）— 1 個**

`app/core/rag/retrieval.py` 第 43 行：
```python
# 修改前
if similarity > top_score:
    top_score = similarity

# 修改後
top_score = max(top_score, similarity)
```

**類型三：加 ignore 規則處理（不修改程式碼）— 6 個**

在 `ruff.toml` 加 `[lint] ignore`，以下規則對這個專案不適用：

| 規則 | 說明 | 忽略原因 |
|------|------|---------|
| `BLE001` | `except Exception` 過於寬泛 | 這個專案的錯誤處理刻意用通用 except，對使用者顯示錯誤訊息 |
| `DTZ005` | `datetime.now()` 沒有 timezone | eval 腳本只是記錄本機時間，不需要 timezone-aware |
| `SIM102` | 巢狀 if 可以合併 | 保留原寫法可讀性較高 |

`test.py` 也加進 `exclude`，因為它是手動驗證腳本，不是正式模組。

### 修改的檔案

- `tests/test_regression.py` — import 排序
- `tests/conftest.py` — import 排序
- `app/core/config.py` — import 排序
- `streamlit_app.py` — import 排序
- `app/core/rag/retrieval.py` — if 簡化為 max()
- `ruff.toml` — 加 exclude 和 ignore 規則

### 學到的事

這次 CI 紅燈是個好例子：**CI 在 PR merge 之前就抓到了問題**，
而且 `build` job 因為 `needs: test` 沒有白跑，節省了 CI 資源。
這就是 CI pipeline 設計的價值——越早失敗，代價越小。

---

## 💡 Docker 相關知識點紀錄

### 1. 執行 Docker 指令不需要進入虛擬環境 (venv)
Docker 的核心優勢在於**環境隔離**。當我們執行 `docker compose up` 時，Docker 會完全根據 `Dockerfile` 內的指令，在「獨立的容器內部」建立專屬的 Python 環境並安裝套件（例如透過 `RUN pip install -r requirements.txt`）。
因此，本機端是否處於 `venv` 虛擬環境，甚至本機端有無安裝 Python，都不會影響 Docker 容器的建置與執行。所有的指令只要確保有安裝 Docker 引擎即可順利運行。

### 2. Docker 的快取機制 (Cache)
當我們修改程式碼後重新執行 `docker compose up --build` 時，Docker **不會**每次都從頭開始執行所有步驟。
Docker 採用分層建置 (Layer-based build) 的機制，如果某一層的原始檔案（如 `requirements.txt` 沒有變動）或指令沒有變更，Docker 就會直接使用上一次建置留下來的「快取 (Cache)」。
例如：在這次修復中，我們只修改了 Dockerfile 後半段下載模型的指令，Docker 會聰明地沿用前面 `pip install` 已經安裝好的依賴套件快取，只從被修改的那一行開始重新執行。這大幅節省了重複下載與安裝套件的時間，讓開發與部署的迭代更加快速。
