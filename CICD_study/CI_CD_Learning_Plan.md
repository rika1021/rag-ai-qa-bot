# CI/CD 實作學習計劃 — RAG QA 客服機器人

## Context

已有一個 Python FastAPI + ChromaDB + Claude API 的 RAG QA 客服機器人 side project，但沒有任何 CI/CD 設定。
目標是透過這個真實專案，由淺入深地學會 Docker → GitHub Actions → Kubernetes，最終讓整個 pipeline 跑起來，同時累積面試亮點。

**每個 Phase 的結構**：
1. **學什麼** — 這個階段涵蓋的核心概念，附推薦資源
2. **概念確認** — 動手前先能回答這些問題，答不出來代表還需要再讀
3. **實作** — 在你的 RAG 機器人專案上實際操作
4. **驗收** — 用這個標準確認自己真的做對了

---

## 整體學習路徑

```
Phase 1: pytest 測試確認   →   Phase 2: Docker   →   Phase 3: GitHub Actions CI
                                                              ↓
                                               Phase 4: CD (推 Docker image)
                                                              ↓
                                   Phase 5a: K8s 概念   →   Phase 5b: minikube 部署
```

---

## Phase 1：確認 pytest 測試可跑（約 0.5 天）

### 學什麼

**目標**：理解「測試為什麼是 CI 的前提」，以及這個專案的測試結構是什麼。

**要讀的東西**：
- [pytest 官方文件 — Getting Started](https://docs.pytest.org/en/stable/getting-started.html)（15 分鐘）
- 直接閱讀 `tests/test_regression.py` 和 `tests/conftest.py`

**核心概念**：
- 什麼是 regression test（退步測試）？為什麼不讓 CI 每次都跑完整的 LLM evaluation？
- `pytest fixture` 是什麼？`conftest.py` 的作用是什麼？
- `pytest.skip()` 和測試失敗有什麼差別？

---

### 概念確認

在動手前，試著用自己的話回答這三個問題：

1. 這個專案的 `tests/test_regression.py` 做了什麼事？它有真的呼叫 Claude API 嗎？
2. 如果 `eval/results.json` 不存在，測試會「失敗（FAILED）」還是「跳過（SKIPPED）」？為什麼這兩個結果不一樣？
3. 為什麼 CI 在執行 `pytest` 時不需要 `ANTHROPIC_API_KEY`？

---

### 實作

1. 確認測試能跑通：
   ```bash
   pip install -r requirements-eval.txt
   pytest tests/ -v
   ```
   應看到 4 個測試全部 PASSED。

2. 確認 `eval/results.json` 有被追蹤（不在 `.gitignore` 裡）：
   ```bash
   git status eval/results.json
   # 應顯示 "nothing to commit"，不是 "ignored"
   ```
   如果是 ignored，從 `.gitignore` 移除後 commit：
   ```bash
   git add eval/results.json
   git commit -m "add eval results for CI regression tests"
   ```

---

### 驗收

- [ ] `pytest tests/ -v` 跑出 4 個 PASSED，沒有 FAILED 也沒有 SKIPPED
- [ ] 能向別人解釋這個測試「讀一個 JSON 檔斷言數字」而非「跑真實 RAG pipeline」的設計決策

---

## Phase 2：Docker（約 1-2 天）

### 學什麼

**目標**：理解 container 是什麼，以及為什麼它能解決「在我電腦上可以跑」的問題。

**要讀的東西**：
- [Docker 官方文件 — What is a container?](https://docs.docker.com/get-started/docker-concepts/the-basics/what-is-a-container/)（20 分鐘）
- [Dockerfile reference](https://docs.docker.com/reference/dockerfile/)（重點看 `FROM`、`WORKDIR`、`COPY`、`RUN`、`CMD`）
- [docker-compose overview](https://docs.docker.com/compose/)（10 分鐘）

**核心概念**：
- image 和 container 的差別（一個是模板，一個是跑起來的實例）
- Dockerfile 每一行是一個 layer，layer 可以被 cache
- volume 解決了什麼問題（container 停掉後資料消失）
- `.dockerignore` 的作用（類比 `.gitignore`）

---

### 概念確認

在動手前，試著用自己的話回答這三個問題：

1. 如果你改了 `requirements.txt`，Docker build 時哪些 layer 會重新執行、哪些會用 cache？
2. ChromaDB 把資料存在 `chroma_db/` 目錄裡，如果 container 重啟且沒有 volume，資料會怎樣？
3. 為什麼不把 `.env`（含 API key）COPY 進 image？應該怎麼傳入 API key？

---

### 實作

**`Dockerfile`**（放在 sideproject 根目錄）：
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 預先下載 embedding model，避免 container 啟動時才下載（約 100MB）
# fastembed 在第一次呼叫時才從網路下載 model，若不在 build 階段處理，
# 每次 container 冷啟動都要重新下載，CI 或受限網路環境中會直接失敗
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('paraphrase-multilingual-MiniLM-L12-v2')"

COPY . .
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**`.dockerignore`**：
```
venv/
chroma_db/
__pycache__/
.env
*.pyc
.git/
CICD_study/
```

**`docker-compose.yml`**（本機開發用）：
```yaml
services:
  api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
    volumes:
      - chroma_data:/app/chroma_db

  streamlit:
    build: .
    command: streamlit run streamlit_app.py --server.port 8501
    ports:
      - "8501:8501"
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
    depends_on:
      - api

volumes:
  chroma_data:
```

> **注意**：Streamlit 容器連 FastAPI 時，URL 要從 `localhost:8000` 改成 `http://api:8000`（container 間用 service name 溝通），記得更新 `streamlit_app.py` 裡的 base URL，或改用環境變數控制。

**在本機測試**：
```bash
# 確保根目錄有 .env 檔含 ANTHROPIC_API_KEY
docker-compose up --build
```

---

### 驗收

- [ ] `docker-compose up --build` 成功，`http://localhost:8000/docs` 出現 Swagger UI
- [ ] 停掉 container（`Ctrl+C`）再重新 `docker-compose up`，之前上傳的文件仍然存在（volume 有效）
- [ ] 能解釋為什麼 Dockerfile 要把 `COPY requirements.txt .` 和 `RUN pip install` 放在 `COPY . .` 之前

---

## Phase 3：GitHub Actions CI（約 1-2 天）

### 學什麼

**目標**：理解什麼是 CI，以及 GitHub Actions 的基本結構。

**要讀的東西**：
- [GitHub Actions — Understanding GitHub Actions](https://docs.github.com/en/actions/about-github-actions/understanding-github-actions)（概念篇，30 分鐘）
- [Workflow syntax for GitHub Actions](https://docs.github.com/en/actions/writing-workflows/workflow-syntax-for-github-actions)（重點看 `on`、`jobs`、`steps`、`uses`、`run`）

**核心概念**：
- CI（Continuous Integration）是什麼：每次有人 push code，自動跑測試確保沒有壞掉
- workflow / job / step 三層結構的關係
- `on: push` 和 `on: pull_request` 的差別
- `uses`（用別人寫好的 Action）vs `run`（直接執行 shell 指令）
- GitHub Secrets 是什麼，為什麼不能把 API key 直接寫在 yaml 裡

**Git branching 工作流程**（CI 的前提）：
```bash
git checkout -b dev          # 建立 dev branch
# ... 做修改 ...
git push origin dev          # push 到 GitHub
# 在 GitHub 上開 Pull Request: dev → main
# CI 在 PR 觸發，綠燈後才 merge
```

---

### 概念確認

在動手前，試著用自己的話回答這三個問題：

1. `jobs.test` 和 `jobs.build` 是同時跑，還是依序跑？如果你要讓 `build` 等 `test` 跑完再跑，要怎麼設定？
2. 為什麼要用 `actions/cache` 來 cache pip？沒有 cache 的話會怎樣？
3. GitHub Secrets 和直接在 yaml 裡寫 `env: ANTHROPIC_API_KEY: sk-ant-xxx` 有什麼差別？

---

### 實作

**建立目錄**（`.github/workflows/` 是 GitHub Actions 的固定路徑，不能改）：
```bash
mkdir -p .github/workflows
```

**`ruff.toml`**（放在 sideproject 根目錄，控制 linter 範圍）：
```toml
exclude = ["venv", "chroma_db"]
line-length = 100
```

**`.github/workflows/ci.yml`**：
```yaml
name: CI

on:
  push:
    branches: [main, dev]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Cache pip
        uses: actions/cache@v4
        with:
          path: ~/.cache/pip
          key: ${{ runner.os }}-pip-${{ hashFiles('requirements-eval.txt') }}

      - name: Install dependencies
        run: |
          pip install -r requirements-eval.txt
          pip install ruff

      - name: Lint (ruff)
        run: ruff check .

      - name: Run tests
        run: pytest tests/ -v
        # 目前的 regression tests 不呼叫 API，不需要 ANTHROPIC_API_KEY

  build:
    runs-on: ubuntu-latest
    needs: test          # test job 成功後才執行
    steps:
      - uses: actions/checkout@v4
      - name: Build Docker image
        run: docker build -t rag-qa-bot .
```

**測試**：push 一個 commit 到 `dev` branch，到 GitHub → Actions tab 觀察 workflow 的執行過程。

---

### 驗收

- [ ] PR 頁面或 commit 頁面出現 CI 的綠色勾勾（checks passed）
- [ ] 能在 Actions tab 看懂每個 step 的 log，知道哪個 step 做了什麼
- [ ] 故意在 code 裡加一個 lint 錯誤，確認 CI 會在 ruff step 失敗（紅叉）

---

## Phase 4：CD — 推 Docker image 到 GHCR（約 1 天）

### 學什麼

**目標**：理解 CD 和 CI 的差別，以及 container registry 是什麼。

**要讀的東西**：
- [GitHub Packages — Working with the Container registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)（20 分鐘）
- 搜尋「CI CD difference」，讀任何一篇 5 分鐘的解釋

**核心概念**：
- CI：自動跑測試（保護 code 品質）
- CD：自動把通過測試的 code 打包並送到某個地方（registry、staging 環境等）
- Container Registry 是什麼（類比：Docker Hub 是 npm 的 image 版）
- 為什麼 image 要有版本 tag，只用 `latest` 的問題是什麼

---

### 概念確認

在動手前，試著用自己的話回答這兩個問題：

1. 如果你的 image 只有 `latest` tag，三個月後你想找出「2 月某次 deploy 用的是哪個 image」，你做得到嗎？
2. `GITHUB_TOKEN` 是哪裡來的？和你手動在 Secrets 設定的 secret 有什麼差別？

---

### 實作

在 `ci.yml` 的 jobs 中加入 `push-image`：

```yaml
  push-image:
    runs-on: ubuntu-latest
    needs: build
    if: github.ref == 'refs/heads/main'   # 只有 merge 到 main 才推 image
    steps:
      - uses: actions/checkout@v4
      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - name: Build and push
        uses: docker/build-push-action@v5
        with:
          push: true
          tags: |
            ghcr.io/${{ github.repository }}/rag-qa-bot:latest
            ghcr.io/${{ github.repository }}/rag-qa-bot:${{ github.sha }}
```

**Push 完之後**：
1. GitHub → 你的 Profile → Packages，找到 `rag-qa-bot`
2. 預設是 **private**，若想公開展示：Package Settings → Change visibility → Public

---

### 驗收

- [ ] merge 一個 PR 到 main 後，GitHub Packages 出現帶有 `latest` 和 sha 兩個 tag 的 image
- [ ] 能解釋為什麼 CD job 加了 `if: github.ref == 'refs/heads/main'`，PR 的時候不會觸發

---

## Phase 5：Kubernetes — 分兩階段

### Phase 5a：概念（約 2 天）

### 學什麼

**目標**：在跑任何指令之前，先能讀懂 K8s YAML 並理解各物件的關係。

**要讀的東西**：
- [Kubernetes — What is Kubernetes?](https://kubernetes.io/docs/concepts/overview/)（30 分鐘）
- [Pods](https://kubernetes.io/docs/concepts/workloads/pods/)
- [Deployments](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/)
- [Services](https://kubernetes.io/docs/concepts/services-networking/service/)
- [ConfigMaps](https://kubernetes.io/docs/concepts/configuration/configmap/)
- [Secrets](https://kubernetes.io/docs/concepts/configuration/secret/)
- [Persistent Volumes](https://kubernetes.io/docs/concepts/storage/persistent-volumes/)

**安裝 kubectl**（只裝 CLI，先不跑 cluster）：
```bash
brew install kubectl
```
有了 kubectl 才能做 YAML 語法驗證：
```bash
kubectl --dry-run=client -f k8s/deployment.yaml
```

| 物件 | 用途 | 對應 docker-compose 概念 |
|------|------|--------------------------|
| Pod | 最小執行單位，跑 container | 一個 container |
| Deployment | 管理 Pod 的數量和版本 | `services` 的 build/image 設定 |
| Service | 讓 Pod 可以被網路訪問 | `ports` 映射 |
| ConfigMap | 非敏感設定 | `environment` 裡的非機密設定 |
| Secret | 敏感資訊 | `environment` 裡的機密，不能寫進檔案 |
| PersistentVolumeClaim | 持久化儲存 | `volumes` |

---

### 概念確認

在動手前，試著用自己的話回答這三個問題：

1. Pod 和 Deployment 的差別是什麼？為什麼不直接部署 Pod？
2. 如果有兩個 Pod 跑同一個 app，它們怎麼共享一個 PVC？（提示：想想 ChromaDB + SQLite 會有什麼問題）
3. 為什麼 K8s Secret 不能建成 `secret.yaml` 並 commit 進 repo？

---

### 實作（先只寫 YAML，不 apply）

建立 `k8s/` 目錄並寫好以下 YAML，理解每個欄位，用 `kubectl --dry-run=client -f` 驗證語法：

```
k8s/
├── namespace.yaml
├── configmap.yaml
├── pvc.yaml
├── deployment.yaml   # replicas: 1（ChromaDB + SQLite 不支援多 writer）
└── service.yaml
```

---

### 驗收

- [ ] 能不看文件，解釋 `deployment.yaml` 裡每個主要欄位（`replicas`、`selector`、`template`、`containers`）的作用
- [ ] 能解釋為什麼 `replicas: 2` 在這個專案裡會造成 bug

---

### Phase 5b：minikube 本機部署（約 2-3 天）

### 學什麼

**目標**：把前一階段寫好的 YAML 實際 apply 到本機的 K8s cluster。

**要讀的東西**：
- [minikube — Get Started](https://minikube.sigs.k8s.io/docs/start/)（跟著 Hello World 走一遍，20 分鐘）
- [kubectl Cheat Sheet](https://kubernetes.io/docs/reference/kubectl/quick-reference/)（當參考查詢用）

**核心概念**：
- minikube 在你電腦上開一個單節點的 K8s cluster（裝在 VM 或 Docker 裡）
- `kubectl` 是 K8s 的 CLI，和 cluster 溝通
- `kubectl apply` vs `kubectl create` 的差別
- `kubectl port-forward` 讓本機可以打 cluster 內部的 service

---

### 概念確認

在動手前，試著用自己的話回答這兩個問題：

1. minikube 的 image registry 和你電腦的 local Docker daemon 是同一個嗎？這代表什麼？
2. `kubectl port-forward` 和 Service 的 `NodePort` 都能讓你從本機打 API，差別是什麼？

---

### 實作

**安裝 minikube**：
```bash
brew install minikube
minikube start
```

**載入 image 到 minikube**（因為 GHCR image 是 private，最簡單的方式是 load local image）：
```bash
docker build -t rag-qa-bot:local .
minikube image load rag-qa-bot:local
```

在 `deployment.yaml` 使用：
```yaml
image: rag-qa-bot:local
imagePullPolicy: Never   # 告訴 K8s 不要去 registry 拉，用 minikube 本地的
```

**部署流程**（順序很重要，namespace 要先建）：
```bash
# 1. 先建 namespace
kubectl apply -f k8s/namespace.yaml

# 2. 建 secret（用指令，不要建 yaml 檔，secret.yaml 不能 commit 進 repo）
kubectl create secret generic rag-qa-secret \
  --from-literal=ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
  -n rag-qa

# 3. 其他所有 manifest
kubectl apply -f k8s/
```

**觀察和驗證**：
```bash
kubectl get pods -n rag-qa           # 看 Pod 狀態
kubectl logs <pod-name> -n rag-qa    # 看 Pod 的 log
kubectl port-forward svc/rag-qa-bot 8000:8000 -n rag-qa
curl http://localhost:8000/docs      # 看到 Swagger UI 就成功
```

---

### 驗收

- [ ] `kubectl get pods -n rag-qa` 顯示 Pod 是 `Running` 狀態（不是 `Pending` 或 `CrashLoopBackOff`）
- [ ] port-forward 後 `http://localhost:8000/docs` 出現 Swagger UI
- [ ] 故意刪掉 Pod（`kubectl delete pod <name> -n rag-qa`），觀察 Deployment 自動重建一個新的 Pod

---

## 整體時程建議

| Phase | 內容 | 預估時間 |
|-------|------|---------|
| 1 | 確認 pytest 可跑 | 0.5 天 |
| 2 | Docker + docker-compose | 1–2 天 |
| 3 | GitHub Actions CI | 1–2 天 |
| 4 | CD + GHCR | 1 天 |
| 5a | K8s 概念 + YAML 撰寫 | 2 天 |
| 5b | minikube 本機部署 | 2–3 天 |
| **合計** | | **約 8–11 天** |

---

## 面試亮點展示重點

完成後 GitHub repo 上可以展示：

1. **CI badge** — README 上的綠色 passing badge
2. **GHCR image（雙 tag）** — 展示 `latest` + `sha` 的 image traceability
3. **k8s YAML** — 能解釋為什麼 `replicas: 1`、為什麼 Secret 不進 repo
4. **DEVLOG 更新** — 記錄每個 Phase 遇到的坑（面試說故事的材料）

---

## 驗收（端對端）

1. **Docker**：`docker-compose up --build` → `http://localhost:8000/docs` 出現 Swagger UI
2. **CI**：push commit 到 `dev`，開 PR → GitHub Actions 綠燈
3. **CD**：merge 到 main → GHCR 出現 `latest` + sha 兩個 tag
4. **K8s**：`kubectl get pods -n rag-qa` Running，port-forward 後能用 API
