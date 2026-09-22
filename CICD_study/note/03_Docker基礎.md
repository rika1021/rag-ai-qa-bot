# Docker 基礎

> CI/CD 學習路線 第二階段

---

## 一、為什麼 CI/CD 需要 Docker？

```
沒有 Docker 的世界：

工程師A的電腦：Python 3.9、套件版本X  →  測試通過 ✅
CI Server：    Python 3.7、套件版本Y  →  測試失敗 ❌
正式環境：     Python 3.11、套件版本Z →  ???       ❓

「在我電腦跑得好好的啊！」← 最經典的工程師台詞
```

```
有 Docker 的世界：

工程師A、CI Server、正式環境 → 全部用同一個「容器」跑
                               環境 100% 一致
                               永遠不會有環境差異問題 ✅
```

---

## 二、最重要的兩個概念：Image vs Container

用「食譜 vs 料理」來記：

```
┌─────────────────────────────────────────────┐
│                                             │
│   Image（映像檔）= 食譜                      │
│   ・靜態的、唯讀的                           │
│   ・定義「環境長什麼樣子」                   │
│   ・可以複製、傳遞、分享                     │
│                                             │
│   Container（容器）= 實際煮出來的料理        │
│   ・動態的、可以執行                         │
│   ・從 Image「啟動」出來的實例               │
│   ・可以同時啟動很多個（同一份食譜煮很多份）  │
│                                             │
└─────────────────────────────────────────────┘

         Image ──────────▶  Container A（正在跑）
           │   啟動          Container B（正在跑）
           │                 Container C（正在跑）
```

### 具體例子：

```
Ubuntu + Python 3.9 + pytest + 你的測試程式碼
              ↓  打包成
         Image（firmware-test:v1.0）
              ↓  啟動
  CI Server 執行 Container，跑完就刪掉
```

---

## 三、Docker 核心架構

```
┌──────────────────────────────────────────────────────┐
│                      你的電腦                         │
│                                                      │
│  ┌─────────────────────────────────────────────┐    │
│  │              Docker Engine                  │    │
│  │  (負責管理所有 Image 和 Container 的程式)     │    │
│  │                                             │    │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  │    │
│  │  │Container │  │Container │  │Container │  │    │
│  │  │  測試A   │  │  測試B   │  │  建置C   │  │    │
│  │  └──────────┘  └──────────┘  └──────────┘  │    │
│  │         ↑              ↑             ↑       │    │
│  │         └──────────────┴─────────────┘       │    │
│  │                   Images                     │    │
│  └─────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────┘
```

### Container 的隔離性：

```
你的電腦作業系統
  │
  ├── Container A：有自己的 Python 3.9、自己的套件、自己的檔案系統
  ├── Container B：有自己的 Python 3.11、完全不同的套件
  └── Container C：有自己的 Node.js 環境

  → 互相完全隔離，不會干擾，刪掉不留痕跡
```

---

## 四、Dockerfile — 定義 Image 的「食譜」

```dockerfile
# 範例：BMC 韌體測試環境的 Dockerfile

FROM ubuntu:22.04          # ← 從 Ubuntu 22.04 開始

RUN apt-get update && \    # ← 安裝系統套件
    apt-get install -y \
    python3 python3-pip \
    gcc make

WORKDIR /app               # ← 設定工作目錄

COPY requirements.txt .    # ← 複製套件清單進去

RUN pip3 install -r \      # ← 安裝 Python 套件
    requirements.txt

COPY . .                   # ← 複製全部程式碼進去

CMD ["python3", "-m",      # ← 預設執行指令
     "pytest", "tests/"]
```

### Dockerfile 指令一覽：

| 指令 | 作用 | 比喻 |
|------|------|------|
| `FROM`    | 以哪個 Image 為基礎    | 選哪個廚房         |
| `RUN`     | 執行指令（安裝軟體等） | 在廚房做準備工作   |
| `COPY`    | 把檔案複製進 Image     | 把食材放進廚房     |
| `WORKDIR` | 設定工作目錄           | 指定在廚房哪個區域 |
| `ENV`     | 設定環境變數           | 調整廚房設定       |
| `CMD`     | Container 啟動時執行什麼 | 開始烹飪的動作   |

---

## 五、常用 Docker 指令

```bash
# 從 Dockerfile 建立 Image
docker build -t firmware-test:v1.0 .
#            ↑ 取名字              ↑ Dockerfile 在這裡（目前資料夾）

# 啟動 Container
docker run firmware-test:v1.0
#          ↑ 用這個 Image 啟動

# 查看正在跑的 Container
docker ps

# 停止 Container
docker stop <container-id>

# 查看所有 Images
docker images

# 刪除 Image
docker rmi firmware-test:v1.0
```

---

## 六、Docker Registry — Image 的倉庫

```
工程師A 建立 Image
        │
        ▼ docker push
  ┌─────────────────────────────────────┐
  │       Docker Registry（倉庫）        │
  │                                     │
  │  DockerHub（公開）                  │
  │  Harbor / ECR（公司私有）← 企業常用  │
  └─────────────────────────────────────┘
        │
        ▼ docker pull
  CI Server 下載同一個 Image 來跑
        │
        ▼ docker pull
  測試機台 下載同一個 Image 來跑
```

---

## 七、Docker 在 CI/CD Pipeline 的位置

```
① git push
     │
     ▼
② CI 觸發（Webhook → Jenkins）
     │
     ▼
③ Jenkins 去 Registry 拉 Image
  docker pull build-env:latest
     │
     ▼
④ 在 Container 裡面執行建置
  docker run build-env:latest make build
     │
     ▼
⑤ 在 Container 裡面執行測試
  docker run test-env:latest pytest tests/
     │
     ▼
⑥ 把建置好的成品打包成新的 Image
  docker build -t firmware:v2.1.0 .
  docker push firmware:v2.1.0
     │
     ▼
⑦ 部署：在目標機器上拉這個 Image 跑
```

---

## 八、緯穎 Server 場景套用

```
build-env Image 內容：
├── ARM 交叉編譯工具鏈（cross-compiler）
├── BMC SDK
├── Python + 測試框架
└── 所有必要開發工具

           ↓

CI Server 跑 Container（確保每次編譯環境一致）
    └── make bmc-firmware → bmc-v2.1.0.bin

           ↓

把這個 .bin 檔傳給 Test Farm 的實體機台燒錄
（韌體本身不是 Docker，Docker 只負責「建置環境」）
```

> ⚠️ 重要：韌體最終要**燒錄進硬體**，硬體不跑 Docker。
> Docker 的用途是**統一建置和測試環境**，不是讓硬體跑 Docker。

---

## 九、Docker Compose — 多個 Container 協同工作

當需要好幾個服務一起跑（例如測試程式 + 資料庫 + Mock Server）：

```yaml
# docker-compose.yml 範例

services:
  test-runner:           # 跑測試的 Container
    image: firmware-test:v1.0
    depends_on:
      - mock-bmc         # 等 mock-bmc 起來再跑

  mock-bmc:              # 模擬 BMC 的 Container
    image: mock-bmc:latest
    ports:
      - "623:623"        # IPMI port
```

```bash
docker-compose up    # 一個指令全部啟動
docker-compose down  # 一個指令全部關掉
```

---

## 本階段總結

```
核心概念記住這三個：

1. Image = 食譜（靜態）
   Container = 依食譜煮出來的料理（動態可執行）

2. Dockerfile 定義如何建立 Image
   → FROM 基礎 → RUN 安裝 → COPY 程式碼 → CMD 執行

3. Docker 在 CI/CD 的價值：
   「確保建置/測試環境在所有地方 100% 一致」
```

---

## 下一步

→ [04_Jenkins實作.md](<04_Jenkins實作.md>)（待學習）
