# Jenkins 架構與 GitHub Actions 差異

> CI/CD 學習路線 第四階段

---

## 一、最根本的設計哲學差異

```
┌─────────────────────────────────────────────────────────────┐
│  GitHub Actions                                             │
│  「平台即服務」(PaaS 思維)                                   │
│                                                             │
│  GitHub 幫你管好一切                                         │
│  → 不用自己架 Server                                         │
│  → 不用管 Runner 的維護、更新、安全性                        │
│  → 程式碼和 CI 設定住在同一個地方（.yml 在 repo 裡）         │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  Jenkins                                                    │
│  「自己架、自己管」(On-Premise 思維)                         │
│                                                             │
│  你自己掌控一切                                              │
│  → 自己架 Jenkins Server（可在公司內網）                     │
│  → 自己管理 Agent（執行工作的機器）                          │
│  → 完全隔離於外網，機密程式碼不出公司                        │
└─────────────────────────────────────────────────────────────┘
```

---

## 二、架構比較圖

### GitHub Actions 架構

```
開發者電腦                  GitHub（雲端）
    │                           │
    │── git push ──────────▶   │
    │                     ┌────┴────────────────┐
    │                     │   GitHub Platform    │
    │                     │                      │
    │                     │  .github/workflows/  │
    │                     │  ci.yml ← 觸發條件   │
    │                     └────────┬─────────────┘
    │                              │ 分派工作
    │              ┌───────────────┼───────────────┐
    │              ▼               ▼               ▼
    │         Runner A        Runner B         Runner C
    │        (ubuntu)        (windows)        (macos)
    │        GitHub 管       GitHub 管        GitHub 管
    │
    │◀── 結果回報（Commit Status API）──────────────────
```

### Jenkins 架構

```
開發者電腦          公司內網
    │                  │
    │── git push ──▶  GitHub (或 GitLab 自架)
    │                  │
    │                  │── Webhook POST ──▶  Jenkins Master
    │                                        （公司內網 Server）
    │                                              │
    │                                              │ 分派工作
    │                              ┌───────────────┼──────────────┐
    │                              ▼               ▼              ▼
    │                         Agent 1          Agent 2        Agent 3
    │                        (Linux VM)       (Windows)    (實體機台)
    │                        公司自管          公司自管      連接硬體！
    │
    │◀── 結果回報（GitHub API）────────────────────────────────────
```

---

## 三、Jenkins 核心概念：Master / Agent 架構

```
┌─────────────────────────────────────────────────┐
│                Jenkins Master                   │
│                                                 │
│  • 接收 Webhook                                  │
│  • 讀取 Jenkinsfile                             │
│  • 決定誰來跑（分派給哪個 Agent）                │
│  • 收集結果、顯示 Dashboard                     │
│  • 不自己跑任何工作（只調度）                   │
└───────────────────────┬─────────────────────────┘
                        │ 分派
           ┌────────────┼────────────┐
           ▼            ▼            ▼
      Agent A       Agent B       Agent C
   Linux Build     Windows      ARM 機台
   （跑 Linux      （跑 Win      （實體機器
    相關工作）      測試）        燒錄韌體）
```

---

## 四、Jenkinsfile — Jenkins 的 Pipeline 設定檔

```groovy
// Jenkinsfile 範例（Groovy 語法）

pipeline {
    agent none                    // 不指定預設 Agent，各 stage 自訂

    environment {
        FIRMWARE_VERSION = "2.1.0"
    }

    stages {

        stage('Code Check') {    // 對應 GitHub Actions 的 Job
            agent { label 'linux-build' }  // 指定跑在哪個 Agent
            steps {              // 對應 GitHub Actions 的 Steps
                checkout scm
                sh 'flake8 src/'
            }
        }

        stage('Build') {
            agent { label 'linux-build' }
            steps {
                sh 'make bmc-firmware'
                archiveArtifacts artifacts: 'build/*.bin'
            }
        }

        stage('Unit Test') {
            agent { label 'linux-build' }
            steps {
                sh 'pytest tests/unit/'
            }
        }

        stage('Integration Test') {
            agent { label 'arm-testbed' }   // 指定跑在實體硬體 Agent！
            steps {
                sh './scripts/flash_bmc.sh'
                sh './scripts/run_llt.sh'
            }
            post {                           // 跑完後不管成功失敗都做
                always {
                    junit 'reports/*.xml'    // 收集測試報告
                }
            }
        }
    }

    post {                                   // 整個 Pipeline 結束後
        success {
            slackSend message: "Build ${env.BUILD_NUMBER} passed ✅"
        }
        failure {
            slackSend message: "Build ${env.BUILD_NUMBER} failed ❌"
            emailext to: 'team@company.com', subject: 'Build Failed'
        }
    }
}
```

### Jenkins Parallel Stage 寫法

```groovy
stage('Parallel Tests') {
    parallel {
        stage('Unit Test') {
            agent { label 'linux' }
            steps { sh 'pytest tests/unit/' }
        }
        stage('Lint') {
            agent { label 'linux' }
            steps { sh 'flake8 src/' }
        }
    }
}
```

---

## 五、語法對照表

| 概念 | GitHub Actions | Jenkins |
|------|---------------|---------|
| 設定檔 | `.github/workflows/ci.yml` | `Jenkinsfile` |
| 語法 | YAML | Groovy (DSL) |
| Pipeline 單位 | Workflow | Pipeline |
| 並行單位 | Job | Stage / Parallel |
| 執行單位 | Step | Step |
| 執行機器 | Runner | Agent |
| 機器指定 | `runs-on: ubuntu-latest` | `agent { label 'xxx' }` |
| 依賴關係 | `needs: [job-a, job-b]` | `stage` 預設依序，平行要加 `parallel {}` |
| 產出物 | `upload/download-artifact` | `archiveArtifacts` / `copyArtifacts` |
| 秘密變數 | `secrets.XXX` | Credentials（Jenkins 介面設定）|
| 觸發條件 | `on: push/pr/schedule` | Webhook + Build Triggers 設定 |

---

## 六、為什麼大公司選 Jenkins？

```
原因 1：程式碼機密性
  GitHub Actions → 程式碼要上傳到 GitHub（雲端）
  Jenkins        → 程式碼完全留在公司內網
                   BMC/BIOS 韌體原始碼不能外洩

原因 2：連接實體硬體
  GitHub Actions → Runner 在 GitHub 雲端，碰不到實體機台
  Jenkins        → Agent 可以是公司機房裡的任何機器
                   直接 SSH 控制 BMC、燒錄韌體

原因 3：龐大的 Plugin 生態系
  Jenkins 有 1800+ 個 Plugin，能整合幾乎所有工具：
  Jira / Slack / 硬體測試框架 / 各種報表工具

原因 4：複雜調度需求
  Jenkins 可以管理幾百台 Agent，精細控制：
  - 這個 Job 只能跑在有 FPGA 的機器
  - 那個 Job 需要 64GB RAM 的機器
  - 限制同時最多 3 個 Job 用這台機器
```

---

## 七、選擇時機

```
✅ 適合 GitHub Actions：
  • 開源專案 / 個人 side project
  • 程式碼可以放在 GitHub 上
  • 不需要連接實體硬體
  • 團隊小、設定簡單優先
  • 快速上手、不想管 Server

✅ 適合 Jenkins：
  • 大型企業內部系統
  • 程式碼必須留在內網（機密性）
  • 需要連接實體機台（硬體/韌體開發）
  • 已有大量歷史 Jenkins 設定
  • 需要複雜的 Agent 調度
```

---

## 八、緯穎最可能的組合（推測）

```
版本控制：  Gerrit（Google 開源，專為企業 Code Review 設計）
            或 GitLab（自架在公司內網）

CI/CD：    Jenkins（自架在公司內網）
            或 GitLab CI（配合 GitLab 使用）

Agent：    公司機房的 Linux Server（跑建置）
            + ARM 測試機台（跑 LLT）
            + Windows 機台（跑 BIOS 相關測試）

容器化：   Docker（統一建置環境）

通知：     Slack 或內部通訊系統
```

---

## 本階段總結

```
核心差異記住這兩點：

1. 架構差異：
   GitHub Actions = 雲端 SaaS，GitHub 幫你管
   Jenkins        = 自架 Server，自己管，完全掌控

2. 選擇邏輯：
   機密性 + 實體硬體 + 大型企業 → Jenkins
   開源 / 個人 / 快速上手       → GitHub Actions
```

### 面試回答框架

> 「GitHub Actions 學習成本低，適合快速驗證概念；
>  但像緯穎這樣涉及機密韌體和實體測試機台的場景，
>  Jenkins 自架在內網才能滿足安全性和硬體整合需求。」

---

## 下一步

→ [06_Server韌體CI_CD特殊流程.md](<06_Server韌體CI_CD特殊流程.md>)（待學習）
