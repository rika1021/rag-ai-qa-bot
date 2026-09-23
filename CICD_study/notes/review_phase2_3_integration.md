# 複習：Docker + GitHub Actions 整合全貌

> 對應章節：Phase 2（Docker）+ Phase 3（GitHub Actions CI）整合複習
> 建立日期：2026-09-23

---

## 一、兩個工具各自解決什麼問題

**Docker** 解決的是「環境」問題：
> 「讓這個應用在任何機器上都能跑起來，不管你裝了什麼。」

**GitHub Actions** 解決的是「驗證」問題：
> 「每次有人改 code，自動確認沒有壞掉。」

**兩個組合在一起**：
> 「每次有人改 code，自動在一個乾淨的環境裡驗證。」

---

## 二、完整流程圖

```
你在本機改 code
      ↓
git push origin dev
      ↓
GitHub 偵測到 push，開一台全新的 ubuntu 虛擬機器
      ↓
┌─────────────────────────────────────────────┐
│  test job（虛擬機器 A）                      │
│  1. checkout：把你的 repo clone 下來         │
│  2. setup python 3.12                       │
│  3. cache pip（requirements 沒變就直接用）   │
│  4. pip install requirements-eval.txt       │
│  5. ruff check .（lint 檢查）               │
│  6. pytest tests/ -v（跑 regression tests） │
└─────────────────────────────────────────────┘
      ↓ test 通過（needs: test）
┌─────────────────────────────────────────────┐
│  build job（虛擬機器 B）                     │
│  1. checkout：把你的 repo clone 下來         │
│  2. docker build -t rag-qa-bot .            │
│     → 用你的 Dockerfile 在 CI 上 build      │
└─────────────────────────────────────────────┘
      ↓ 兩個 job 都通過
commit 頁面出現綠色勾勾 ✅
      ↓
開 PR（dev → main）→ CI 再跑一次
      ↓ PR CI 通過
按 Merge → dev 的 commit 合進 main ✅
```

---

## 三、Docker 在 CI 裡扮演什麼角色？

`build` job 做的事是：
```bash
docker build -t rag-qa-bot .
```

這一步在確認：**「你的 Dockerfile 本身沒有壞掉。」**

**為什麼這很重要？**

假設你改了 `requirements.txt` 加了一個新套件，但忘了更新 Dockerfile——
這個問題在本機可能發現不了（你的 venv 已經有那個套件），
但 CI 的 build job 會在一個**全新的乾淨環境**裡跑 `docker build`，馬上失敗。

CI 幫你模擬「在一台從來沒碰過這個專案的機器上 build」的情境。

---

## 四、三個環境的對照

你現在同時有三個地方可以跑這個應用：

| 環境 | 怎麼跑 | 用途 |
|------|--------|------|
| **本機直接跑** | `uvicorn main:app` + `streamlit run` | 開發時快速測試，改一行馬上看到結果 |
| **本機 Docker** | `docker compose up` | 驗證容器化後的行為，確認 volume、container 網路、環境變數注入 |
| **CI 虛擬機器** | GitHub Actions 自動觸發 | 每次 push 自動驗證，保護 main branch 不被壞 code 污染 |

三個環境的 Python 套件版本、OS 環境都不同，
但 `docker build` 在 CI 上跑成功就代表在任何機器上都能部署。

---

## 五、整個系統的防護層

```
你改 code，push 上去
      ↓
Layer 1：ruff（CI — test job）
  → 格式、import 順序、明顯的 code smell
  → 在「跑」之前就擋下來，秒級回饋

Layer 2：pytest regression test（CI — test job）
  → 確認 RAG 品質指標（recall@3、MRR、faithfulness、answer_relevancy）沒有退步
  → 讀靜態 JSON，0.03 秒，不需要 API key

Layer 3：docker build（CI — build job）
  → 確認 Dockerfile 能成功 build
  → test 通過才跑（needs: test），避免浪費資源

Layer 4：PR review（人工，未來可加）
  → 人眼看 code 邏輯，機器看不到的東西
```

越早的層越快、越便宜；越後面的層越深入。
CI 在你 push 的幾分鐘內跑完前三層，讓人工 review 只需要專注在邏輯上。

---

## 六、push 到 dev 和開 PR 的 CI 差異

```yaml
on:
  push:
    branches: [main, dev]     # push 到 dev 時觸發
  pull_request:
    branches: [main]          # 有 PR 要合進 main 時觸發
```

| | push 到 dev | 開 PR（dev → main） |
|--|------------|-------------------|
| 觸發時機 | 你直接 push commit | 你提出合併請求 |
| 目的 | 確認「這個 commit 本身沒問題」 | 確認「合併進 main 之後不會壞」 |
| 結果顯示在 | Actions tab 的 commit 記錄 | PR 頁面的 checks 區塊 |

**為什麼兩個都需要？**

`push` 是快速個人回饋。
`pull_request` 是保護 main——即使每個 commit 個別都過，
兩個人同時改不同 branch 合在一起可能衝突炸掉，PR 的 CI 就是防這種情況。

**結果**：main branch 裡的每一個 commit，都一定是經過 CI 驗證的。

---

## 七、這個 Phase 實際踩到的坑（面試素材）

### 坑 1：ruff 12 個 lint 錯誤
第一次 push `ci.yml`，CI 馬上紅燈。
原因：專案裡多個檔案的 import 順序不對（stdlib 和 third-party 沒有用空行分隔）。

學到的事：**CI 在 merge 之前就攔住問題**，而且 `build` job 因為 `needs: test` 沒有白跑。

### 坑 2：ModuleNotFoundError: No module named 'dotenv'
修完 lint 再 push，又紅燈。
原因：CI 只裝 `requirements-eval.txt`，但 `conftest.py` 用到的 `python-dotenv` 只在 `requirements.txt`。

學到的事：**CI 環境是全新的虛擬機器，只有你明確裝的東西**。本機跑沒問題不代表 CI 沒問題。

讀 log 的方法：從最底下的 `E` 行往上看，找錯誤類型 + 觸發位置兩個資訊就夠定位問題。

```bash
gh run view <run-id> --log-failed   # 只看失敗的 step
```

---

## 八、Phase 4 預告：CD（Continuous Delivery）

目前 CI 的最後一步只是確認「Dockerfile 能 build」，但 image 沒有去任何地方。

Phase 4 要加的：
```
test 通過 → build 通過 → 把 image 推到 GHCR（GitHub Container Registry）
```

每次 merge 進 main，就會自動有一個可部署的 image 在 registry 上，
帶著兩個 tag：
- `latest`：最新版本
- `sha-xxxxxxx`：這次 commit 的唯一識別碼（可以追溯「哪次部署用的是哪個 commit」）

這就是 CI（驗證）和 CD（交付）的差別——CI 確保品質，CD 確保交付。
