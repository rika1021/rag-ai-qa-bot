# Git + 觸發機制

> CI/CD 學習路線 第一階段

---

## 一、Git 在 CI/CD 的角色

Git 是整個 CI/CD 的**起點**。所有自動化流程都從「程式碼有變動」開始。

```
工程師寫程式
    ↓
git commit（存檔）
    ↓
git push（上傳到遠端）
    ↓
🔔 觸發 CI/CD！
```

---

## 二、Git 核心概念

### 2.1 Branch（分支）— 平行宇宙

```
main（主線，穩定版）
  │
  ├── feature/bmc-sensor-fix     ← 工程師A在修bug
  ├── feature/bios-boot-update   ← 工程師B在加功能
  └── hotfix/fan-control         ← 工程師C在修緊急問題
```

> 每個工程師在自己的「分支」工作，不互相干擾。
> 做完之後再「合併」回主線。

### 2.2 PR / MR（Pull Request / Merge Request）— 申請合併

```
工程師A：「我的 feature/bmc-sensor-fix 做好了，請審查後合併進 main」
            ↓
        提出 PR（Pull Request）
            ↓
        主管/同事 Code Review
            ↓
        ✅ Approve → Merge
        ❌ Request Changes → 修改後重試
```

### 2.3 Commit（提交）— 每一個存檔點

```
commit A3f2b1: "Fix BMC sensor reading overflow"   ← 最新
commit 9d8c7e: "Add fan speed monitoring feature"
commit 4a2b1c: "Initial BMC firmware setup"          ← 最舊
```

---

## 三、觸發機制：Webhook

### 核心概念

```
┌─────────────────────────────────────────────────────────────┐
│                         Webhook 原理                         │
│                                                             │
│  GitHub/GitLab         →        Jenkins / CI Server        │
│  （程式碼平台）                   （自動化執行系統）           │
│                                                             │
│  「有人 push 了！」   ──HTTP POST──▶  「收到！開始跑 pipeline！」│
└─────────────────────────────────────────────────────────────┘
```

**白話比喻：**
Webhook 就像「門鈴」。GitHub 是前門，Jenkins 是管家。
有人按門鈴（push/PR），管家就自動出來做事（跑測試/建置）。

---

## 四、完整觸發流程

```
① 工程師 push 程式碼到 GitHub/GitLab
         │
         ▼
② GitHub 偵測到有變動
         │
         ▼
③ GitHub 發送 Webhook（HTTP POST 請求）給 Jenkins
         │
         │   這個請求長這樣：
         │   {
         │     "event": "push",
         │     "branch": "feature/bmc-sensor-fix",
         │     "author": "engineer_a",
         │     "commit": "a3f2b1..."
         │   }
         │
         ▼
④ Jenkins 收到通知，根據設定決定要做什麼
         │
         ▼
⑤ Jenkins 開始執行 Pipeline（一連串自動化步驟）
         │
         ▼
⑥ 結果回報給 GitHub（成功✅ / 失敗❌）
```

---

## 五、不同事件觸發不同 Pipeline

企業常見設計：**不同動作觸發不同程度的自動化**

| 觸發事件 | 代表什麼 | 通常跑什麼 |
|---------|---------|-----------|
| push 到 feature branch | 工程師在開發中    | 快速測試（smoke test），幾分鐘內完成 |
| 開 PR（Pull Request）  | 申請合進主線      | 完整單元測試 + 程式碼品質檢查       |
| PR 被 Merge 進 main    | 確認合進主線      | 完整測試 + 自動建置 + 打包          |
| 打 Tag（版本號）        | 宣告發行版本      | 完整測試 + 建置 + 部署到測試環境    |
| 每晚定時（Nightly Build）| 排程自動跑      | 最完整的耗時測試（整晚跑）          |

```
feature push  →  [快速 CI]  →  5分鐘
PR opened     →  [完整 CI]  →  20分鐘
main merge    →  [CI + CD]  →  1小時
nightly       →  [全套測試] →  整晚
```

---

## 六、緯穎 Server 場景套用

以 BMC 韌體開發的 Fan Control Bug 修復為例：

```
工程師修好 Fan Control Bug
        │
        ▼ git push feature/fan-control-fix
        │
   ┌────┴──── CI 快跑（編譯 + 靜態分析）
   │          ↳ 確認程式碼能編譯過，語法沒問題
        │
        ▼ 開 PR 到 main
        │
   ┌────┴──── CI 完整跑（編譯 + 單元測試 + 整合測試）
   │          ↳ 確認功能邏輯正確
        │
        ▼ PR 審查通過，Merge 進 main
        │
   ┌────┴──── CD 啟動（建置 BMC firmware image + 燒錄測試機台）
              ↳ 真的燒進硬體，跑 LLT 測試
              ↳ 測試通過 → 這版韌體可以給 QA
```

---

## 七、三大 CI 平台比較

| 平台 | 設定檔位置 | 特色 |
|------|------------|------|
| GitHub Actions | `.github/workflows/xxx.yml` | 直接在 repo 裡設定，最簡單 |
| GitLab CI      | `.gitlab-ci.yml`            | 企業內部部署常用，功能完整 |
| Jenkins        | `Jenkinsfile`               | 最靈活、最老牌，大公司愛用 |

> 緯穎這種規模的公司大概率用 **Jenkins** 或 **GitLab CI**（可自架在內網）。

---

## 八、設定檔範例（GitHub Actions）

```yaml
# 這個 CI 的名稱
name: BMC Firmware CI

# 觸發條件
on:
  push:
    branches: [ main, develop ]   # push 到這些 branch 時觸發
  pull_request:
    branches: [ main ]            # 有 PR 要合進 main 時觸發

# 要做的工作
jobs:
  build-and-test:
    runs-on: ubuntu-latest        # 在 Linux 環境跑

    steps:
      - name: 下載程式碼
        uses: actions/checkout@v3

      - name: 編譯韌體
        run: make build

      - name: 跑單元測試
        run: make test

      # 成功 → PR 旁邊出現綠色勾勾 ✅
      # 失敗 → PR 旁邊出現紅色叉叉 ❌，擋住 Merge
```

**YAML 三個核心區塊：**

```
on:     → 什麼時候跑（觸發條件）
runs-on:→ 在哪裡跑（執行環境）
steps:  → 跑什麼（具體步驟）
```

---

## 九、保護機制：Branch Protection

企業設定「main 不能直接 push，必須透過 PR + CI 通過」：

```
❌ 工程師直接 push 到 main  →  被擋住！

✅ 正確流程：
   1. push 到 feature branch
   2. 開 PR
   3. CI 自動跑測試（必須通過）✅
   4. 至少 1 人 Code Review（必須通過）✅
   5. 才能 Merge 進 main
```

確保主線永遠是「測試過的、有人審查過的」乾淨狀態。

---

## 本階段總結

```
核心概念記住這三個：

1. Webhook = 「有變動」→「通知 CI 系統」的橋樑

2. 不同事件觸發不同深度的測試
   push → 快速  |  PR → 完整  |  merge → 部署

3. Pipeline 設定檔（YAML / Jenkinsfile）定義「觸發條件」和「要做什麼」
```

---

## 下一步

→ [03_Docker基礎.md](<03_Docker基礎.md>)（待學習）
