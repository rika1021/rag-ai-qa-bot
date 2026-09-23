# GitHub Actions 深入

> CI/CD 學習路線 第三階段
> ※ 本階段以 GitHub Actions 為主，最後補充 Jenkins 架構差異

---

## 一、GitHub Actions 的整體架構

```
GitHub Repository
  │
  └── .github/
        └── workflows/
              ├── ci.yml        ← 每個 .yml 就是一條 Pipeline
              ├── release.yml
              └── nightly.yml
```

當觸發條件符合，GitHub 就會讀取對應的 `.yml`，
照著上面的指示自動執行。

---

## 二、四層結構（最重要的概念）

```
┌─────────────────────────────────────────┐
│  Workflow（工作流程）                    │  ← 整個 .yml 檔
│                                         │
│  ┌───────────────────────────────────┐  │
│  │  Job（工作）                      │  │  ← 可平行或依序執行
│  │                                   │  │
│  │  ┌─────────────────────────────┐  │  │
│  │  │  Step（步驟）               │  │  │  ← Job 內依序執行
│  │  │                             │  │  │
│  │  │  ┌────────────────────┐     │  │  │
│  │  │  │  Action（動作）    │     │  │  │  ← Step 執行的最小單位
│  │  │  └────────────────────┘     │  │  │
│  │  └─────────────────────────────┘  │  │
│  └───────────────────────────────────┘  │
└─────────────────────────────────────────┘
```

### Job 的執行關係：

```
Workflow 被觸發
    │
    ├── Job A ──────────────────── 在 Runner 機器上跑
    │     ├── Step 1: checkout
    │     ├── Step 2: build
    │     └── Step 3: test
    │
    └── Job B（可與 Job A 平行跑，或等 A 完成再跑）
          ├── Step 1: checkout
          └── Step 2: deploy
```

---

## 三、Runner 是什麼？

```
Runner = 實際執行工作的機器

                GitHub 提供的 Runner
┌──────────────────────────────────────────┐
│  ubuntu-latest   ← Linux，最常用         │
│  windows-latest  ← Windows               │
│  macos-latest    ← macOS                 │
└──────────────────────────────────────────┘

                自架的 Runner（Self-hosted）
┌──────────────────────────────────────────┐
│  你公司自己的機器                         │
│  → 可以連到內網硬體                       │
│  → 企業常用，緯穎這類公司就是這個方案     │
└──────────────────────────────────────────┘
```

---

## 四、完整 YAML 結構解析

```yaml
# ─── Workflow 基本設定 ───────────────────────────────
name: BMC Firmware CI

# ─── 觸發條件 ────────────────────────────────────────
on:
  push:
    branches: [ main, develop ]
    paths:                           # 只有這些路徑改動才觸發
      - 'src/**'
      - 'tests/**'
  pull_request:
    branches: [ main ]
  schedule:
    - cron: '0 2 * * *'             # 每天凌晨 2 點（Nightly Build）
  workflow_dispatch:                 # 允許手動在介面觸發

# ─── 全域環境變數 ─────────────────────────────────────
env:
  FIRMWARE_VERSION: "2.1.0"
  BUILD_TYPE: "release"

# ─── Jobs ────────────────────────────────────────────
jobs:

  # Job 1：建置
  build:
    name: Build Firmware
    runs-on: ubuntu-latest
    steps:
      - name: Checkout code
        uses: actions/checkout@v4        # 使用現成的 Action

      - name: Setup build environment
        run: |
          sudo apt-get update
          sudo apt-get install -y gcc-arm-linux-gnueabi make

      - name: Build BMC firmware
        run: make bmc-firmware
        env:
          CROSS_COMPILE: arm-linux-gnueabi-

      - name: Upload firmware binary
        uses: actions/upload-artifact@v4
        with:
          name: firmware-binary
          path: build/bmc-v*.bin

  # Job 2：測試（等 build 完成才跑）
  test:
    name: Run Tests
    runs-on: ubuntu-latest
    needs: build                         # 宣告依賴 build job

    steps:
      - name: Download firmware binary
        uses: actions/download-artifact@v4
        with:
          name: firmware-binary

      - uses: actions/checkout@v4
      - run: pytest tests/unit/
      - run: pytest tests/integration/

  # Job 3：程式碼品質（和 build 平行跑，沒有 needs）
  lint:
    name: Code Quality Check
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: |
          pip install flake8
          flake8 src/
```

---

## 五、Job 執行關係圖

```
Workflow 觸發
    │
    ├── build ──────────────────────── 先跑
    │     └── （完成後）
    │           ▼
    │         test ─────────────────── 再跑
    │
    └── lint ──────────────────────── 和 build 同時平行跑

時間軸：

t=0   build ████████████████
      lint  ████████
t=N              test ████████████
```

---

## 六、Action（uses）是什麼？

```yaml
# 常用的官方 Actions：

- uses: actions/checkout@v4          # 下載 repo 程式碼
- uses: actions/setup-python@v5      # 安裝 Python
  with:
    python-version: '3.11'

- uses: actions/upload-artifact@v4   # 上傳產出物（Job 間傳遞）
- uses: actions/download-artifact@v4 # 下載產出物

- uses: docker/build-push-action@v5  # 建立並推送 Docker Image
  with:
    push: true
    tags: myimage:latest
```

```
Action 的本質 = 別人打包好的一段自動化腳本
                你直接呼叫，不用自己重寫
```

---

## 七、Secret — 管理敏感資訊

密碼、Token 絕對不能寫在 YAML 裡：

```
GitHub Repo → Settings → Secrets and variables → Actions
  ├── DOCKER_USERNAME = "mycompany"
  ├── DOCKER_PASSWORD = "xxxxx"
  └── SSH_PRIVATE_KEY = "-----BEGIN RSA..."
```

```yaml
- name: Login to Docker Registry
  run: |
    echo "${{ secrets.DOCKER_PASSWORD }}" | \
    docker login -u "${{ secrets.DOCKER_USERNAME }}" --password-stdin
```

---

## 八、Matrix Strategy — 同時測試多種環境

```yaml
jobs:
  test:
    strategy:
      matrix:
        python-version: [3.9, 3.10, 3.11]
        os: [ubuntu-latest, windows-latest]

    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: pytest tests/
```

```
自動展開成 3 × 2 = 6 個並行 Job：

Python 3.9  × Ubuntu
Python 3.9  × Windows
Python 3.10 × Ubuntu
Python 3.10 × Windows
Python 3.11 × Ubuntu
Python 3.11 × Windows
```

---

## 九、Context 與表達式語法

```yaml
steps:
  - name: 印出各種資訊
    run: |
      echo "Branch: ${{ github.ref_name }}"
      echo "Commit: ${{ github.sha }}"
      echo "Actor:  ${{ github.actor }}"
      echo "Event:  ${{ github.event_name }}"

  # 條件判斷：只有 merge 到 main 才執行
  - name: Deploy to production
    if: github.ref == 'refs/heads/main' && github.event_name == 'push'
    run: ./deploy.sh
```

| Context | 意思 |
|---------|------|
| `github.ref_name`   | 當前 branch 或 tag 名稱 |
| `github.sha`        | 當前 commit 的 hash    |
| `github.actor`      | 觸發這次 Workflow 的人  |
| `github.event_name` | 觸發事件類型（push/pr） |

---

## 十、緯穎場景：完整 Server 韌體 Pipeline

```yaml
name: BMC Firmware Full Pipeline

on:
  pull_request:
    branches: [ main ]
  push:
    branches: [ main ]

jobs:

  # 1. 平行：程式碼品質 + 安全掃描
  code-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: flake8 src/ && bandit -r src/

  # 2. 建置韌體（等 code-check 過）
  build:
    needs: code-check
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Build in Docker container
        run: |
          docker run --rm \
            -v $(pwd):/workspace \
            build-env:latest \
            make bmc-firmware
      - uses: actions/upload-artifact@v4
        with:
          name: bmc-binary
          path: build/*.bin

  # 3. 單元測試（和 build 平行）
  unit-test:
    needs: code-check
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pytest tests/unit/ -v

  # 4. 整合測試（等 build + unit-test 都過）
  integration-test:
    needs: [build, unit-test]
    runs-on: self-hosted             # 自架 Runner，連接實體機台
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: bmc-binary
      - name: Flash firmware to test machine
        run: ./scripts/flash_bmc.sh bmc-v*.bin
      - name: Run LLT tests
        run: ./scripts/run_llt.sh

  # 5. 只有 merge 到 main 才發布
  release:
    needs: integration-test
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    steps:
      - name: Tag and release
        run: ./scripts/release.sh ${{ env.FIRMWARE_VERSION }}
```

```
整條 Pipeline 的流向：

code-check ──┬── build ─────────────────────────┐
             │                                   ▼
             └── unit-test ──────────── integration-test → release
                                        （self-hosted Runner
                                          連接實體測試機台）
```

---

## 本階段總結

```
GitHub Actions 核心概念：

結構層次：
  Workflow → Job → Step → Action
  （.yml）  （並行）（依序）（uses:）

重要機制：
  needs:     → Job 依賴關係（控制執行順序）
  matrix:    → 多環境平行測試
  secrets:   → 敏感資訊管理
  if:        → 條件執行
  artifacts  → Job 間傳遞檔案

和緯穎的連結：
  self-hosted Runner → 連接公司內網實體機台
  這是企業 CI/CD 的關鍵！
```

---

## 下一步

→ [05_Jenkins架構與差異.md](<05_Jenkins架構與差異.md>)（待學習）
