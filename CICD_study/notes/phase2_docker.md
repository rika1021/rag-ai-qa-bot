# Phase 2：Docker

> 學習計劃對應章節：Phase 2（約 1-2 天）
> 完成日期：2026-09-22
> 狀態：✅ 完成

---

## 一、核心概念整理

### Image vs Container

| 概念 | 類比 | 說明 |
|------|------|------|
| **Image** | 食譜 / 模板 | 靜態的，描述「要怎麼建立環境」，可以分享、推到 registry |
| **Container** | 依食譜做出來的菜 / 執行中的實例 | 動態的，從 image 啟動，有自己的 process、network、filesystem |

- 同一個 image 可以同時跑多個 container，彼此獨立
- Container 停掉後**不會**回到 image——它只是停止，資料還在
- Container 刪掉後，裡面寫入的資料**全部消失**（除非用 volume）

```
Dockerfile  →  docker build  →  Image  →  docker run  →  Container
（描述步驟）     （執行建造）     （模板）    （啟動實例）    （跑起來的環境）
```

---

### Dockerfile Layer 與 Cache

Dockerfile 每一行指令執行後，Docker 會對當時的檔案系統做一個**快照（snapshot）**，
這個快照就叫 **layer**。

**Cache 規則：如果這一行的「輸入」沒有改變，直接用上次的 layer，不重新執行。**

一旦某個 layer 失效（輸入有變），**它之後的所有 layer 全部跟著重新執行**。

```dockerfile
FROM python:3.12-slim          # layer 1：基底 image（幾乎不變）
WORKDIR /app                   # layer 2：建目錄（不變）
COPY requirements.txt .        # layer 3：複製 requirements.txt
RUN pip install ...            # layer 4：安裝套件 ← 最慢，要讓它 cache 住
RUN python -c "from fastembed" # layer 5：下載 embedding model（約 100MB）
COPY . .                       # layer 6：複製所有 source code ← 最常變
CMD ["uvicorn", ...]           # layer 7：啟動指令
```

**情境一：只改了 `main.py`**
- layer 1-5：全部 cache 命中 ✅（省掉 pip install + 下載 model 的 5-10 分鐘）
- layer 6：`COPY . .` 偵測到 source code 有變 → 重新執行
- layer 7：跟著重新執行

**情境二：改了 `requirements.txt`（加了新套件）**
- layer 1-2：cache 命中 ✅
- layer 3：`COPY requirements.txt .` 偵測到內容有變 → 重新執行
- layer 4 以後：**全部重跑**（pip install、下載 model、COPY . .）

**為什麼 `COPY requirements.txt` 要放在 `COPY . .` 前面？**
因為「改 code 但沒改套件」是最常見的情境。這樣排序讓 pip install 的 layer 能被 cache 住，
每次改 code 只需要幾秒 build，不需要重裝套件。

---

### Volume（持久化儲存）

**問題**：Container 有自己獨立的 filesystem，停掉並刪除後，裡面寫入的資料全消失。

**這個專案的問題**：ChromaDB 把向量資料存在 `/app/chroma_db/` 目錄。
沒有 volume 的話，每次重啟 container 就要重新上傳所有文件、重建向量索引。

**解法**：Volume 把 container 內的目錄對應到 container 外部的儲存空間，
讓資料在 container 生命週期之外持續存在。

```yaml
# docker-compose.yml
services:
  api:
    volumes:
      - chroma_data:/app/chroma_db   # container 內的 /app/chroma_db
                                     # 對應到名為 chroma_data 的 volume

volumes:
  chroma_data:                       # Docker 管理的具名 volume
```

Volume 的資料存在 Docker 管理的地方（不在你的專案目錄裡），
container 重啟後，資料還在。

#### 沒有 Docker vs 有 Docker 的儲存位置對比

**沒有 Docker 時**，直接在本機跑 `uvicorn main:app`，ChromaDB 寫資料到：
```
/Users/huangshimin/Desktop/rika/面試/sideproject/chroma_db/
```
就是專案資料夾裡的 `chroma_db/`，打開 Finder 可以直接看到。

**有 Docker 時**，ChromaDB 在 container 內部跑，寫資料到 container 內部的路徑：
```
/app/chroma_db/     ← container 內部，跟本機的 sideproject/chroma_db/ 無關
```
Container 有自己獨立的 filesystem，container 被刪掉，這個目錄也跟著消失。

**Volume 的作用**：把 container 內的 `/app/chroma_db/` 對應到 Docker 管理的系統目錄：
```
/var/lib/docker/volumes/sideproject_chroma_data/   ← Docker 管理，不在專案資料夾
              ↕ 對應
      /app/chroma_db/  （container 內部）
```

```
沒有 Docker：
  本機 sideproject/chroma_db/  ←  ChromaDB 直接寫這裡

有 Docker + volume：
  Docker volume（系統目錄）    ←  ChromaDB 寫 container 內的 /app/chroma_db/
          ↕ 對應
  /app/chroma_db/（container 內部）
```

Volume 是真實存在於硬碟的，只是位置在 Docker 的系統目錄，不在你的專案資料夾。
它的目的是讓資料的生命週期**脫離 container**——container 刪掉，資料還在。

---

### .dockerignore

和 `.gitignore` 一樣的概念：告訴 `docker build` 哪些檔案/目錄不要打包進 **build context**（傳給 Docker daemon 的檔案集合）。

**為什麼重要？**
- `COPY . .` 會把 build context 裡的所有東西複製進 image
- 沒有 `.dockerignore` 的話，`venv/`（幾百MB）、`chroma_db/`（向量資料）、`.env`（含機密）都會進去

這個專案的 `.dockerignore`：
```
venv/        ← Python 虛擬環境，container 裡會重新 pip install，不需要帶進去
chroma_db/   ← 向量資料，container 應該用 volume 管理，不應該打包進 image
.env         ← 含 API key，絕對不能進 image
__pycache__/ ← 編譯快取，不需要
*.pyc        ← 編譯快取
.git/        ← git 歷史，不需要
CICD_study/  ← 學習筆記，不需要
```

---

### 為什麼不把 .env COPY 進 image？

Image 是可以被分享、推到 registry（Docker Hub、GHCR）的東西。
如果 `.env`（含 `ANTHROPIC_API_KEY=sk-ant-xxx`）被打包進 image，
任何拿到這個 image 的人都能讀出 API key。

**正確做法：container 啟動時從外部注入環境變數**

```yaml
# docker-compose.yml
services:
  api:
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      # ${...} 表示從你本機的 shell 環境變數或 .env 檔讀取
      # 這個值在 container 啟動時注入，不存在 image 裡
```

你的 `.env` 檔（含真實 key）只存在本機，永遠不進 image，也不進 git repo。

---

### docker-compose 是什麼？

`docker-compose` 是**多個 container 的編排工具**。
當你的應用需要多個 service 同時跑（這個專案有 `api` + `streamlit`），
用 docker-compose 可以一個指令全部啟動，而不需要手動跑多個 `docker run`。

**docker-compose.yml 的結構**：
```yaml
services:        # 每個 service 對應一個 container
  api:           # service 名稱（container 之間用這個名稱互相找到對方）
    build: .     # 用當前目錄的 Dockerfile build image
    ports:
      - "8000:8000"   # 本機port:container port
    environment:
      - KEY=VALUE     # 注入環境變數
    volumes:
      - volume名:container內路徑

volumes:         # 宣告具名 volume
  chroma_data:
```

---

### Container 之間怎麼溝通？

在 docker-compose 裡，每個 service 都有一個**內部 DNS 名稱**，就是 service 的名字。

```
streamlit container 想連 api container：
❌ http://localhost:8000   ← localhost 在 container 裡指的是自己，不是別的 container
✅ http://api:8000         ← "api" 是 docker-compose 裡的 service 名稱
```

這就是為什麼 `streamlit_app.py` 要改成讀環境變數：
- 本機直接跑：`API_BASE_URL` 未設定 → fallback 到 `http://localhost:8000`
- docker-compose 跑：`API_BASE_URL=http://api:8000` → 用 service name 連

```python
# streamlit_app.py
API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")
```

### 為什麼有了 docker-compose，只需要一個 terminal？

**沒有 Docker 時**，你直接在本機跑 process，每個 process 需要一個 terminal 佔著：
```
Terminal 1：uvicorn main:app --port 8000    ← 佔著不能關
Terminal 2：streamlit run streamlit_app.py  ← 佔著不能關
```

**有 docker-compose 後**，`docker compose up` 同時啟動多個 container，
每個 container 跑自己的 process，全部交給 Docker 管理：
```
docker compose up
    ├── 啟動 api container       → 裡面跑 uvicorn
    └── 啟動 streamlit container → 裡面跑 streamlit
```

你只需要一個 terminal，log 也集中輸出（`api-1 |` 和 `streamlit-1 |` 混在一起）。

但更根本的差別不是 terminal 數量，而是**環境的可重現性**：

| | 沒有 Docker | 有 Docker |
|--|------------|----------|
| 環境 | 你本機的 Python、套件版本 | 固定在 image，任何機器都一樣 |
| 啟動 | 2 個 terminal，記住順序 | 1 個指令 |
| 停止 | 每個 terminal 各按 Ctrl+C | 1 個 Ctrl+C 全停 |
| 給別人跑 | 說明一堆環境設定步驟 | `docker compose up` 一行搞定 |

---

## 二、這個專案建立的檔案

### Dockerfile 逐行解說

```dockerfile
FROM python:3.12-slim
# 基底 image：Python 3.12，slim 版（去掉不必要的套件，image 較小）

WORKDIR /app
# 設定工作目錄，之後的 COPY/RUN 都在 /app 底下執行

COPY requirements.txt .
# 只複製 requirements.txt（不是全部 source code）
# 目的：讓下面的 pip install layer 可以獨立 cache

RUN pip install --no-cache-dir -r requirements.txt
# 安裝套件，--no-cache-dir 讓 pip 不在 image 裡留下下載快取，減少 image 體積

RUN python -c "from fastembed import TextEmbedding; TextEmbedding('paraphrase-multilingual-MiniLM-L12-v2')"
# 預先下載 embedding model（約 100MB）
# fastembed 第一次呼叫時才下載 model，如果不在 build 階段處理，
# 每次 container 冷啟動都要等幾分鐘，在受限網路（如 CI）中甚至會失敗

COPY . .
# 現在才複製所有 source code
# 這時 pip install 的 cache 已經存好，改 code 不會觸發重裝套件

EXPOSE 8000
# 宣告 container 會用 8000 port（文件用途，不強制）

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
# container 啟動時執行的指令
# --host 0.0.0.0 讓 container 外部可以連進來（預設的 127.0.0.1 只有 container 內部能連）
```

### docker-compose.yml 逐行解說

```yaml
services:
  api:
    build: .                          # 用當前目錄的 Dockerfile build
    ports:
      - "8000:8000"                   # 本機 8000 → container 8000
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}   # 從本機 .env 注入
    volumes:
      - chroma_data:/app/chroma_db    # 持久化 ChromaDB 資料

  streamlit:
    build: .                          # 用同一個 Dockerfile build（不同 CMD）
    command: streamlit run streamlit_app.py --server.port 8501
    # 覆蓋 Dockerfile 的 CMD，改成跑 streamlit
    ports:
      - "8501:8501"
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - API_BASE_URL=http://api:8000  # 告訴 streamlit 去找 api 這個 service
    depends_on:
      - api                           # 確保 api container 先啟動

volumes:
  chroma_data:                        # Docker 管理的具名 volume
```

---

## 三、概念確認 Q&A

**Q1：如果你改了 `requirements.txt`，Docker build 時哪些 layer 會重新執行、哪些會用 cache？**

`COPY requirements.txt .` 這個 layer 偵測到內容有變 → 失效。
它之後的所有 layer 全部重新執行：`RUN pip install`、`RUN python -c "from fastembed..."`、`COPY . .`、`CMD`。
`FROM`、`WORKDIR` 這兩個在它前面的 layer 繼續用 cache。

**Q2：ChromaDB 把資料存在 `chroma_db/` 目錄，如果 container 重啟且沒有 volume，資料會怎樣？**

每次 container 重啟，`/app/chroma_db/` 都是空的，所有上傳過的文件和向量資料全部消失，
需要重新上傳才能使用 RAG 功能。
有了 volume（`chroma_data:/app/chroma_db`），資料存在 Docker 管理的 volume 裡，
container 重啟後資料仍然存在。

**Q3：為什麼不把 `.env`（含 API key）COPY 進 image？應該怎麼傳入 API key？**

Image 可以被推到 registry 並分享，任何人拿到 image 都能讀出裡面的檔案。
API key 應該在 container **啟動時**從外部注入，不存在 image 裡。
在 docker-compose.yml 裡用 `environment: - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}`，
docker-compose 啟動時從本機 `.env` 讀取 key，再傳給 container。

---

## 四、常用指令

```bash
# 建 image 並啟動所有 container（有改 Dockerfile 或 code 時用 --build）
docker-compose up --build

# 啟動（不重 build）
docker-compose up

# 背景執行
docker-compose up -d

# 停止並移除 container（volume 不受影響）
docker-compose down

# 停止並移除 container + volume（資料也清掉，完全重置）
docker-compose down -v

# 查看正在跑的 container
docker ps

# 查看某個 container 的 log
docker-compose logs api
docker-compose logs streamlit

# 進入 container 的 shell（debug 用）
docker-compose exec api bash
```

---

## 五、驗收步驟

```bash
# 1. 確認根目錄有 .env 檔且含有 ANTHROPIC_API_KEY
cat .env  # 應看到 ANTHROPIC_API_KEY=sk-ant-...

# 2. 啟動（第一次會比較久，要下載 embedding model 約 100MB）
docker-compose up --build

# 3. 驗收 1：Swagger UI
# 打開瀏覽器 → http://localhost:8000/docs

# 4. 驗收 2：volume 有效
# 上傳一份文件 → Ctrl+C 停止 → docker-compose up → 文件仍然存在
```

### 驗收清單

- [x] `docker compose up --build` 成功，`http://localhost:8000/docs` 出現 Swagger UI
- [x] 停掉再重啟，之前上傳的文件仍然存在（volume 有效）
- [x] 能解釋為什麼 `COPY requirements.txt .` + `RUN pip install` 要放在 `COPY . .` 之前

---

## 六、面試說法

> 「我用 Docker 把這個 FastAPI + ChromaDB 的 RAG 機器人容器化。
> Dockerfile 的順序有刻意設計：先 COPY requirements.txt、pip install，
> 再 COPY source code，這樣改 code 時 pip install 的 layer 能被 cache 住，
> build 時間從幾分鐘降到幾秒。ChromaDB 的向量資料用 named volume 持久化，
> 確保 container 重啟後不用重新上傳文件。
> API key 透過 docker-compose 的 environment 在啟動時注入，不存在 image 裡，
> 避免推到 registry 後洩漏。」
