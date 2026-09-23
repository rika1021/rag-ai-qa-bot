# Phase 3：GitHub Actions CI

> 學習計劃對應章節：Phase 3（約 1-2 天）
> 完成日期：2026-09-23
> 狀態：✅ 完成

---

## 一、背景知識：這個 Phase 需要先懂的東西

### 什麼是 CI？

CI = Continuous Integration（持續整合）

**沒有 CI 的世界**：
```
你改了程式碼 → push 到 GitHub → 不知道有沒有壞 → 要手動跑測試才知道
```

**有 CI 的世界**：
```
你改了程式碼 → push 到 GitHub → GitHub 自動幫你跑測試 → 幾分鐘後告訴你紅燈或綠燈
```

CI 的核心價值：**讓「驗證 code 有沒有壞」這件事自動化，不依賴人記得手動做。**

---

### 什麼是 GitHub Actions？

GitHub Actions 是 GitHub 內建的 CI/CD 工具。
你在 repo 裡放一個 yaml 設定檔，GitHub 就會依照設定，在特定事件發生時（例如 push）自動跑指定的指令。

你不需要自己準備伺服器，GitHub 提供虛擬機器（runner）來執行。

---

### 虛擬機器（Runner）是什麼？

每次 CI 被觸發，GitHub 會給你一台**全新的虛擬機器**：
- 上面只有基本的作業系統（ubuntu-latest）
- 什麼套件都沒有，需要自己安裝
- 跑完就銷毀，下次又是全新的

```
你 push code
    ↓
GitHub 開一台全新的 ubuntu 虛擬機器
    ↓
虛擬機器執行你 yaml 裡定義的步驟（checkout、pip install、pytest...）
    ↓
回報結果（PASS / FAIL）
    ↓
虛擬機器銷毀
```

**重要**：因為每次都是全新機器，所以每次都要重新安裝套件。
這就是為什麼需要 cache——避免每次都重新下載。

---

### 什麼是 Branch？為什麼 CI 需要 branch 工作流程？

Branch（分支）是 git 的概念，讓你在不影響主線的情況下開發新功能。

```
main branch    ─────────────────────────────→  穩定版本，不直接改
                        ↑
dev branch     ───────── → 你在這裡改 code，改好了開 PR 合併進 main
```

**PR（Pull Request）**：你在 dev 改好了，發一個「我想把這些改動合併進 main」的請求。
CI 會在 PR 被開啟時自動跑，通過了才能 merge。

這樣的好處：main branch 永遠是經過測試的穩定版本。

---

## 二、GitHub Actions 的三層結構

```
Workflow（.github/workflows/ci.yml）
└── Job（例如：test、build）
    └── Step（例如：checkout、pip install、pytest）
```

### Workflow
- 整個自動化流程的定義，存在 `.github/workflows/` 資料夾
- 一個 repo 可以有多個 workflow（例如 `ci.yml`、`deploy.yml`）
- `.github/workflows/` 這個路徑是固定的，GitHub 只認這個位置

### Job
- Workflow 裡的一個工作單位
- 每個 job 跑在一台**獨立的**虛擬機器上
- **預設：多個 job 同時跑（parallel）**，不是依序

### Step
- Job 裡的每一個步驟，依序執行
- 有兩種寫法：

```yaml
# 用別人寫好的 Action
- uses: actions/checkout@v4      # 把 repo clone 到虛擬機器

# 直接執行 shell 指令（和你在 terminal 打的一樣）
- run: pytest tests/ -v
```

---

## 三、核心概念整理

### `on`：什麼時候觸發？

```yaml
on:
  push:
    branches: [main, dev]      # push 到 main 或 dev 時觸發
  pull_request:
    branches: [main]           # 有 PR 要合併進 main 時觸發
```

最常見的工作流程：
1. 你在 `dev` branch 改 code，push 到 GitHub → CI 跑
2. 開 PR（dev → main）→ CI 再跑一次
3. CI 綠燈 → 才能 merge 進 main

---

### `needs`：讓 job 依序執行

**預設**：多個 job 同時跑（因為快）。

```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    # 跑測試

  build:
    runs-on: ubuntu-latest
    # 同時在另一台機器 build Docker image（預設行為）
```

**加上 `needs`**：讓 build 等 test 通過才執行。

```yaml
jobs:
  test:
    runs-on: ubuntu-latest

  build:
    runs-on: ubuntu-latest
    needs: test     # ← test 成功後才跑，test 失敗就跳過
```

**為什麼要 `needs: test`？**
測試失敗代表 code 有問題，這時候繼續 build Docker image 沒有意義，只是浪費時間和資源。

---

### `actions/cache`：為什麼要 cache pip？

每次 CI 觸發，都是全新虛擬機器，什麼套件都沒有，需要重新 `pip install`。
沒有 cache：每次都要重新下載所有套件，約 1-2 分鐘。
有了 cache：requirements 沒變的話，直接用上次存好的，幾秒搞定。

```yaml
- uses: actions/cache@v4
  with:
    path: ~/.cache/pip
    key: ${{ runner.os }}-pip-${{ hashFiles('requirements-eval.txt') }}
```

**key 的邏輯**：
- key 包含 `requirements-eval.txt` 的 hash（檔案內容的指紋）
- requirements 沒變 → hash 不變 → key 一樣 → 命中 cache ✅
- requirements 有變（加了新套件）→ hash 變了 → key 不同 → 重新下載 ✅

跟 Docker layer cache 的邏輯完全一樣：「有沒有變動」決定要不要重用。

---

### GitHub Secrets：為什麼不能把 key 寫在 yaml 裡？

**`.github/workflows/ci.yml` 是 commit 進 repo 的。**

```yaml
# ❌ 絕對不能這樣寫
env:
  ANTHROPIC_API_KEY: sk-ant-xxx
```

問題：
1. 任何有 repo 權限的人都能看到
2. 即使你之後刪掉那行，**git 歷史記錄裡還是有**，永遠找得到

**正確做法：GitHub Secrets**

```yaml
# ✅ 從 GitHub Secrets 讀取
env:
  ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

GitHub Secrets 的特性：
- 加密儲存在 GitHub 伺服器，**不進 git**
- CI 執行時自動注入到環境變數
- log 裡不會顯示實際值（自動遮罩成 `***`）
- 只有 repo admin 可以設定，其他人連值是什麼都看不到

設定位置：GitHub repo → Settings → Secrets and variables → Actions

> **這個專案的 regression test 不需要 API key**（只讀靜態 JSON），
> 所以 Phase 3 不需要設定 Secrets。這是 Phase 1 設計的價值之一。

---

### `uses` vs `run`

```yaml
steps:
  # uses：使用別人封裝好的 Action（可以想成是別人寫好的腳本）
  - uses: actions/checkout@v4
  # → 這個 Action 會把你的 repo clone 到虛擬機器，讓後續步驟能讀到你的 code

  - uses: actions/setup-python@v5
    with:
      python-version: "3.12"
  # → 在虛擬機器上安裝指定版本的 Python

  # run：直接執行 shell 指令，和你在 terminal 打的完全一樣
  - run: pip install -r requirements-eval.txt
  - run: pytest tests/ -v
```

`@v4`、`@v5` 是 Action 的版本號，釘住版本避免 Action 更新後行為改變。

---

## 四、這個專案要建立的檔案

### 目錄結構

```
sideproject/
└── .github/
    └── workflows/
        └── ci.yml     ← GitHub Actions 固定讀這個路徑
```

`.github/workflows/` 是固定路徑，不能改，GitHub 只認這個位置。

### ruff.toml（linter 設定）

```toml
exclude = ["venv", "chroma_db"]
line-length = 100
```

ruff 是 Python 的 linter（程式碼風格檢查工具），
`exclude` 排除不需要檢查的目錄，`line-length` 設定每行最長字數。

### ci.yml 結構

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
      - uses: actions/checkout@v4         # 1. clone repo 到虛擬機器
      - uses: actions/setup-python@v5     # 2. 安裝 Python 3.12
        with:
          python-version: "3.12"
      - uses: actions/cache@v4            # 3. 嘗試從 cache 載入 pip 套件
        with:
          path: ~/.cache/pip
          key: ${{ runner.os }}-pip-${{ hashFiles('requirements-eval.txt') }}
      - run: pip install -r requirements-eval.txt   # 4. 安裝套件（cache 命中則很快）
      - run: pip install ruff                       # 5. 安裝 linter
      - run: ruff check .                           # 6. 檢查程式碼風格
      - run: pytest tests/ -v                       # 7. 跑 regression tests

  build:
    runs-on: ubuntu-latest
    needs: test                            # test 通過後才 build
    steps:
      - uses: actions/checkout@v4
      - run: docker build -t rag-qa-bot . # 確認 Dockerfile 能成功 build
```

---

## 五、概念確認 Q&A

**Q1：`jobs.test` 和 `jobs.build` 是同時跑，還是依序跑？如果要讓 build 等 test 跑完，要怎麼設定？**

預設是**同時跑（parallel）**。
要讓 build 等 test，在 build job 加上 `needs: test`。
這樣 test 失敗時，build 不會執行，避免浪費資源。

**Q2：為什麼要用 `actions/cache` 來 cache pip？沒有 cache 的話會怎樣？**

每次 CI 觸發都是全新虛擬機器，沒有 cache 的話每次都要重新下載所有套件（約 1-2 分鐘）。
Cache 以 `requirements-eval.txt` 的 hash 為 key，requirements 沒變就命中 cache，幾秒完成安裝。

**Q3：GitHub Secrets 和直接在 yaml 裡寫 key 有什麼差別？**

`ci.yml` 是 commit 進 repo 的，直接寫 key 會被所有人看到，且永遠留在 git 歷史裡。
GitHub Secrets 加密存在 GitHub 伺服器，不進 git，log 裡自動遮罩，只有 admin 能設定。

---

## 六、push 到 dev 和開 PR 的 CI 差異

這次實作跑了兩種觸發，兩者目的不同：

```yaml
on:
  push:
    branches: [main, dev]      # push 到 dev 時觸發
  pull_request:
    branches: [main]           # 有 PR 要合進 main 時觸發
```

| | push 到 dev | 開 PR（dev → main） |
|--|------------|-------------------|
| 觸發原因 | 你直接 push commit | 你提出合併請求 |
| 目的 | 確認「這個 commit 本身沒問題」 | 確認「合併進 main 之後不會壞」 |
| 結果顯示在 | Actions tab 的 commit 記錄 | PR 頁面的 checks 區塊 |

**為什麼要跑兩次？**

`push` 是快速回饋，確認你自己的 code 沒問題。
`pull_request` 是保護 main——即使每個 commit 個別都過，
兩個人同時改不同 branch 合在一起可能炸掉，PR 的 CI 就是防這種情況。

---

## 七、PR 開下去到 CI 完成的完整流程

```
gh pr create (dev → main)
      ↓
GitHub 偵測到「有人想把 dev 合併進 main」
      ↓
ci.yml 的 on: pull_request: branches: [main] 被觸發
      ↓
開全新虛擬機器，跑 test job
  → checkout → setup python → cache pip → pip install → ruff → pytest
      ↓
test 通過 → 跑 build job（needs: test）
  → checkout → docker build
      ↓
全部通過 → PR 頁面出現綠色勾勾
      ↓
按 Merge → dev 的 commit 合進 main
```

---

## 八、如何看 CI log 判斷錯誤

```bash
gh run list --limit 5          # 看最近幾次 run 的狀態
gh run view <run-id> --log-failed  # 只看失敗的 step 的 log
```

**讀 log 的方法**：從最底下的 `E` 或 `Error:` 行開始往上看。

```
tests/conftest.py:3: in <module>       ← 錯誤發生的位置
    from dotenv import load_dotenv     ← 觸發錯誤的那行程式碼
E   ModuleNotFoundError: No module named 'dotenv'  ← 錯誤是什麼
```

兩個資訊足以定位問題：
1. **錯誤是什麼**（`E` 那行）
2. **在哪觸發**（上面那行的檔案路徑 + 行號）

---

## 九、驗收步驟與結果

### 實際執行流程

```bash
git checkout -b dev
git add .github/ ruff.toml
git commit -m "add GitHub Actions CI workflow"
git push origin dev
# → CI 觸發，但失敗（ruff 12 個錯誤）→ 修完再 push

git add .
git commit -m "fix ruff lint errors"
git push origin dev
# → CI 觸發，但失敗（ModuleNotFoundError: dotenv）→ 加進 requirements-eval.txt 再 push

git add requirements-eval.txt
git commit -m "add python-dotenv to requirements-eval.txt"
git push origin dev
# → CI 通過 ✅

gh pr create --title "Phase 3: add CI pipeline" ...
# → PR CI 通過 ✅ → merge 進 main
```

### 驗收清單

- [x] push commit 到 `dev` branch，Actions tab 出現正在執行的 workflow
- [x] PR 頁面出現 CI 的綠色勾勾（checks passed）
- [x] 能用 `gh run view --log-failed` 看懂每個 step 的 log 並定位錯誤
- [x] 實際遭遇 CI 紅燈並修復（ruff 錯誤、dotenv 缺失）

---

## 十、面試說法

> 「我用 GitHub Actions 設定了 CI pipeline，每次 push 到 dev branch 或開 PR 進 main，
> 就會自動跑 ruff lint 和 regression tests。
> Test job 和 build job 用 needs 串起來，test 沒過就不浪費時間 build image。
> pip 套件用 actions/cache 加速，以 requirements 的 hash 為 key，
> requirements 沒變的話 cache 命中，安裝時間從 1-2 分鐘降到幾秒。
> Regression test 讀靜態 JSON，不呼叫 Claude API，所以 CI 不需要管理 API key。」
