# Phase 4：CD — 推 Docker Image 到 GHCR

> 學習計劃對應章節：Phase 4（約 1 天）
> 完成日期：2026-09-23
> 狀態：🚧 進行中

---

## 一、背景知識：這個 Phase 在做什麼

### CI vs CD 的真正差別

Phase 3 完成的是 **CI**（Continuous Integration）——每次 push 自動驗證 code 品質。

Phase 4 要加的是 **CD**（Continuous Delivery）——讓通過驗證的版本自動「交付」到某個地方。

```
Phase 3（CI）：
  push → test → docker build → ✅ 結束，image 被丟掉

Phase 4（CI + CD）：
  push → test → docker build → push image 到 GHCR → ✅ image 永久存在，隨時可部署
```

**用一句話區分**：
- CI = 「這個 code 是好的嗎？」
- CD = 「把通過驗證的 code 打包，放到一個可以被部署的地方」

---

### 什麼是 Container Registry？

Container Registry 是「存放 Docker image 的倉庫」。

| | npm | Docker |
|--|--|--|
| 存放的東西 | npm 套件 | Docker image |
| 公開 registry | npmjs.com | Docker Hub |
| GitHub 提供的 | GitHub Packages（npm） | **GHCR**（ghcr.io） |

**GHCR（GitHub Container Registry）** 直接整合在你的 GitHub repo 裡：
- 不需要額外申請服務
- image 和 code 放在同一個地方，容易對應版本
- 可以用 `GITHUB_TOKEN` 直接授權，不需要額外管理 registry 的帳密

---

## 二、Image Tag 策略：為什麼需要兩個 tag

每次推到 GHCR，這個專案會產生兩個 tag：

```
ghcr.io/你的帳號/rag-qa-bot:latest          ← 永遠指向最新版本
ghcr.io/你的帳號/rag-qa-bot:sha-a3f2c1d    ← 這次 commit 的唯一識別碼
```

### 只用 `latest` 的問題

`latest` 每次都會被覆蓋。

**場景**：三個月後線上出了 bug，你需要找出「2 月那次 deploy 用的是哪個 image」：
- 只有 `latest`：找不到，那個版本早就被後來的 `latest` 覆蓋了
- 有 sha tag：`sha-a3f2c1d` 永遠存在，對應到 git commit `a3f2c1d`，一秒定位

### sha tag 的價值

```bash
# sha tag 讓你可以做到：
docker pull ghcr.io/你的帳號/rag-qa-bot:sha-a3f2c1d  # 拉回那個精確版本
git show a3f2c1d                                        # 看那個版本做了什麼
```

**一句話**：`latest` 是給「想要最新版本」的人用的，`sha` 是給「需要追蹤特定版本」的人用的。兩個都要。

---

## 三、`GITHUB_TOKEN`：GitHub 自動提供的臨時通行證

### 它是什麼

每次 GitHub Actions 被觸發，GitHub 會**自動產生一個臨時 token**，注入到 `secrets.GITHUB_TOKEN`。

你不需要去 Settings → Secrets 手動建立它，GitHub 自動幫你做。

```yaml
# 你在 ci.yml 這樣用：
password: ${{ secrets.GITHUB_TOKEN }}

# 但 Secrets 頁面裡完全沒有這個條目
# 它不是你建的，是 GitHub 每次 CI 自動注入的
```

### 它的生命週期

這個 token 只在「這一次 CI run」存活，run 結束就失效。下次 push 又是全新的 token。

### 它能做什麼

有權限操作「這個 repo 本身」的 GitHub 資源：
- 推 image 到這個 repo 的 GHCR ✅
- 讀寫 Issues、建立 PR ✅
- 連到 Anthropic API 等外部服務 ❌（那個需要你手動設定 Secrets）

### 和手動設定的 Secrets 比較

| | `GITHUB_TOKEN` | 手動 Secret（如 `ANTHROPIC_API_KEY`） |
|--|--|--|
| 誰建的 | GitHub 自動產生 | 你手動在 Settings → Secrets 建立 |
| 用途 | 操作 GitHub 自己的資源 | 連外部服務 |
| 有效期 | 只活在這次 CI run | 永久，直到你刪掉 |
| 需要 rotate | 不需要，每次都是新的 | 你自己管理 |

---

## 四、新工具介紹（Phase 4 用到的 Action）

Phase 3 大多用 `run:` 跑 shell 指令，Phase 4 開始用 Docker 官方維護的 Action。

### `docker/login-action@v3`

登入 Container Registry，讓後續的 push 有授權。

```yaml
- name: Log in to GHCR
  uses: docker/login-action@v3
  with:
    registry: ghcr.io
    username: ${{ github.actor }}      # 觸發這次 CI 的 GitHub 帳號
    password: ${{ secrets.GITHUB_TOKEN }}
```

### `docker/build-push-action@v5`

把原本兩步（`docker build` + `docker push`）合成一步，且支援更多進階功能。

```yaml
- name: Build and push
  uses: docker/build-push-action@v5
  with:
    push: true
    tags: |
      ghcr.io/${{ github.repository }}/rag-qa-bot:latest
      ghcr.io/${{ github.repository }}/rag-qa-bot:${{ github.sha }}
```

**為什麼用 Action 而不是直接 `run: docker build && docker push`？**

- 官方 Action 封裝了更多邏輯（build cache、多平台 build、失敗重試）
- 更穩定，由 Docker 官方維護
- `docker build-push-action` 可以在一次 build 就完成 push，不需要先 build 再 push 兩次

---

## 五、GitHub Actions 變數：`github.repository` vs `github.actor`

這兩個容易混淆，在 tag 和 login 裡分別用到不同的：

| 變數 | 值（範例） | 用途 |
|--|--|--|
| `github.actor` | `huangshimin` | 觸發這次 CI 的帳號名，用在 login 的 `username` |
| `github.repository` | `huangshimin/sideproject` | 完整的 `帳號/repo名`，用在 image tag 路徑 |
| `github.sha` | `a3f2c1d8e9...`（完整 40 字） | 這次 commit 的 SHA，用在 sha tag |

**GHCR image 路徑格式**：
```
ghcr.io/<github.repository>/<image-name>:<tag>
ghcr.io/huangshimin/sideproject/rag-qa-bot:latest
```

---

## 六、`if:` 條件：為什麼 CD 只在 main 執行

```yaml
push-image:
  needs: build
  if: github.ref == 'refs/heads/main'   # ← 只有 main branch 才觸發
```

| 情境 | `push-image` 會跑嗎？ |
|--|--|
| push commit 到 dev | ❌ 不跑 |
| 開 PR（dev → main） | ❌ 不跑 |
| merge PR 進 main | ✅ 跑 |

**為什麼只在 main？**

dev branch 是「工作中的狀態」，不是「值得交付的版本」。只有 merge 進 main 代表：
1. 通過了 test job（ruff + pytest）
2. 通過了 build job（Dockerfile 能 build）
3. 人工 review 確認可以合進

才是「這個版本是可以部署的」。

---

## 七、完整 Pipeline 全圖（Phase 4 之後）

```
你在 dev branch 改 code
        ↓
git push origin dev
        ↓
GitHub 偵測到 push
        ↓
┌──────────────────────────────────────────────┐
│  test job（虛擬機器 A）                       │
│  ruff check → pytest tests/                  │
└──────────────────────────────────────────────┘
        ↓ needs: test
┌──────────────────────────────────────────────┐
│  build job（虛擬機器 B）                      │
│  docker build -t rag-qa-bot .                │
└──────────────────────────────────────────────┘
        ↓ push-image：if main → 不執行（現在是 dev）
綠燈 → 開 PR（dev → main）→ CI 再跑一次

merge 進 main
        ↓
┌──────────────────────────────────────────────┐
│  test job → build job（同上）                │
└──────────────────────────────────────────────┘
        ↓ needs: build + if: main → 執行
┌──────────────────────────────────────────────┐
│  push-image job（虛擬機器 C）                 │
│  docker/login-action → 登入 GHCR             │
│  docker/build-push-action → build + push     │
│    → ghcr.io/.../rag-qa-bot:latest           │
│    → ghcr.io/.../rag-qa-bot:sha-xxxxxxx      │
└──────────────────────────────────────────────┘
        ↓
GitHub Packages 出現這個 image ✅
```

---

## 八、GHCR Image 預設是 Private

推上去之後，image 預設只有你能看到（Private）。

**如果要公開展示（例如給面試官看）**：
1. GitHub → 你的 Profile（頭像）→ Packages
2. 找到 `rag-qa-bot`
3. Package Settings → Change visibility → Public

**注意**：改成 Public 後，任何人都能 `docker pull` 這個 image。這個專案沒有敏感內容（API key 不進 image），改成 Public 是安全的。

---

## 九、這個 Phase 的 ci.yml 改動

在原本的 `build` job 後面加入 `push-image` job：

```yaml
  push-image:
    runs-on: ubuntu-latest
    needs: build
    if: github.ref == 'refs/heads/main'
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

---

## 十、驗收步驟與結果

### 驗收清單

- [ ] push commit 到 dev，確認 Actions tab 裡 `push-image` job 沒有出現（if 條件擋住）
- [ ] 開 PR（dev → main），merge 後確認 `push-image` job 執行
- [ ] GitHub → Profile → Packages 出現 `rag-qa-bot`，帶 `latest` 和 sha 兩個 tag
- [ ] 能解釋為什麼 CD job 加了 `if: github.ref == 'refs/heads/main'`

---

## 十一、面試說法

> 「Phase 3 的 CI 只確認 Dockerfile 能 build，但 image 沒有被保存下來。
> Phase 4 加了 CD pipeline——每次有 commit merge 進 main，
> 就自動把 image 推到 GHCR，帶兩個 tag：
> `latest` 讓人知道最新版本在哪，`sha` tag 讓每個 image 都能對應到一個 git commit，
> 方便日後 rollback 或追蹤特定版本的部署。
> Push image 的授權用的是 GitHub 自動提供的 `GITHUB_TOKEN`，
> 不需要手動在 Secrets 設定，也不需要管理 registry 的帳密。」
