# 補充：Webhook 與 CI 回報機制

> 針對 02_Git與觸發機制.md 的延伸問答

---

## Q1：Webhook 是什麼？需要另外安裝嗎？

### Webhook 的本質

Webhook **不是一個工具**，是一種**通訊機制的概念**。

```
一般的通訊方式（你主動問）：
  你 → 問 GitHub：「有新的 commit 嗎？」  （每隔幾秒一直問）

Webhook 的通訊方式（它主動通知你）：
  GitHub → 通知你：「有新的 commit 了！」（只在事情發生時才說）
```

Webhook 的實體就是一個 **HTTP POST 請求**，由 GitHub 主動送出。

---

### Webhook 和 GitHub Actions 的關係

```
情境 A：GitHub Actions（你正在學的）
  → Webhook 完全內建，你完全不用管
  → 只要在 .yml 寫 on: push，GitHub 自動處理一切

情境 B：GitHub + Jenkins（企業常見）
  → 要在 GitHub Settings 手動設定 Webhook URL
  → 填入你的 Jenkins Server 地址
  → 之後 GitHub 有事件，就自動 POST 給 Jenkins

情境 C：GitHub + 你自己的系統
  → 同上，填你自己的 Server URL
  → 你的 Server 要寫程式接收這個 POST 請求
```

### Jenkins 情境下的設定畫面（概念）

```
GitHub Repo → Settings → Webhooks → Add webhook

Payload URL:  http://jenkins.company.com/github-webhook/
Content type: application/json
Events:       ✅ Push events
              ✅ Pull requests
```

### 結論

```
・GitHub Actions → Webhook 完全內建，不用設定，不用安裝
・Jenkins        → 要在 GitHub 設定 Webhook URL 指向 Jenkins
・Webhook 本身   → 不是工具，是「HTTP POST 通知」這件事的名稱
```

---

## Q2：Pipeline 跑完後，結果怎麼回報給 GitHub？

### 不是 HTTP Response！是另一個獨立的 API 請求

```
❌ 很多人誤以為的樣子：

  GitHub ──POST──▶ Jenkins（Webhook）
         ◀── 200 OK，結果：成功 ──（同一條連線回應）


✅ 實際的樣子：

  第一條通訊（Webhook）：
    GitHub ──POST──▶ Jenkins：「有 push 了！」
           ◀── 202 Accepted ──（只是說「我收到了」，不是結果）

    ← 這條連線到此結束，Jenkins 開始執行工作 →

  第二條通訊（Commit Status API）：
    Jenkins ──POST──▶ GitHub API：「這個 commit 測試成功了」
                      （幾分鐘後，Jenkins 跑完才送）
```

### GitHub 怎麼接受這個回報？

GitHub 有專門的 API 接收狀態：

```
POST https://api.github.com/repos/公司/專案/statuses/a3f2b1...
{
  "state":       "success",         ← 或 failure / pending / error
  "description": "All tests passed",
  "context":     "jenkins/build",   ← 這個狀態的名稱
  "target_url":  "http://jenkins.company.com/job/123"
}
```

### GitHub 收到後顯示在 PR 頁面：

```
✅ jenkins/build  All tests passed    Details →
✅ jenkins/test   Unit tests passed   Details →
❌ jenkins/lint   Linting failed      Details →

→ 有任何一個是 ❌，就擋住 Merge
```

---

## 整個通訊完整時序圖

```
工程師                GitHub               Jenkins / CI

  │── git push ──▶  │                        │
  │                 │── POST /webhook ──▶    │  （Webhook 通知）
  │                 │ ◀── 202 Accepted ────  │  （只是確認收到）
  │                 │                        │
  │                 │                        │ 開始執行...
  │                 │                        │ 建置中...
  │                 │                        │ 測試中...
  │                 │                        │
  │                 │ ◀── POST /statuses ──  │  （回報結果，獨立請求）
  │                 │     { state: success } │
  │                 │                        │
  │ ◀── PR 上出現 ✅  │                        │
```

---

## 總結表

| 問題 | 答案 |
|------|------|
| Webhook 是工具嗎？ | 不是，是「主動通知」的通訊機制，實體是 HTTP POST |
| GitHub Actions 要設定 Webhook 嗎？ | 不用，完全內建 |
| Jenkins 要設定 Webhook 嗎？ | 要，在 GitHub Settings 填入 Jenkins URL |
| ⑤→⑥ 是 HTTP Response 嗎？ | 不是，是 CI 跑完後另外主動送的 GitHub Commit Status API |
