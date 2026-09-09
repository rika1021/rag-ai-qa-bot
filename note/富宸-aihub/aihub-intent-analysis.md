# AI Hub 意圖分析（Intent Analysis）深度學習筆記

> 本筆記整理自對 `bpm-backend-main/src/module/ai-hub/services/deterministic-retrieval-engine.ts` 的學習提問
>
> 對應的全流程追蹤報告：https://claude.ai/code/artifact/e8c2bcb4-ae19-4759-a0f5-54f848af33f3
>
> 📋 **完整講稿（含口語）**：`富宸-aihub/aihub-script-full.txt`

---

## 目錄

1. [analyzeIntent() 六個欄位全解析](#一analyzeintent-六個欄位全解析)
2. [字詞解釋：taxonomyIds / pg_trgm / Segment / L1 Cache / kw_score](#二字詞解釋)
3. [query 的來源與 keywords 生成機制](#三query-的來源與-keywords-生成機制)
4. [keywords vs expertSearchKeywords 的差異](#四keywords-vs-expertsearchkeywords-的差異)
5. [Taxonomy Tree 存在哪裡？](#五taxonomy-tree-存在哪裡)
6. [Segment 就是 RAG 的 Chunk 嗎？](#六segment-就是-rag-的-chunk-嗎)
7. [L1/L2 Cache 的底層機制](#七l1l2-cache-的底層機制)
8. [Memory 系統深度解析（記憶三層混淆澄清）](#八memory-系統深度解析)

---

## 一、analyzeIntent() 六個欄位全解析

### 怎麼來的

一次 `generateObject` 呼叫，LLM 輸出符合 Zod Schema 的結構化 JSON。這是這個系統最重要的 **Token 優化點**：傳統做法需要 3–4 次 LLM 呼叫，這裡只需要 **1 次**。

```ts
// Zod Schema 示意
const intentSchema = z.object({
  intent:               z.string(),
  taxonomyIds:          z.array(z.string()),
  keywords:             z.array(z.string()),
  mandatoryKeywords:    z.array(z.string()),
  expertSearchKeywords: z.array(z.string()),
  acknowledgment:       z.string(),
  memoryAction:         z.enum(["none", "save", "update", "delete"]),
});
```

LLM 的輸入：使用者 query + 整棵 Taxonomy 樹（24hr 靜態快取）+ System Prompt 指引。

### 實際回傳範例（query: "我的請假簽核會要給誰簽"）

```json
{
  "intent":                "KNOWLEDGE_QA (ai-hub-bpm)",
  "taxonomyIds":           ["tx_bpm_approval", "tx_hr_leave"],
  "keywords":              ["請假", "簽核", "審核人", "簽核流程"],
  "mandatoryKeywords":     ["請假"],
  "expertSearchKeywords":  ["請假流程", "HR審核"],
  "acknowledgment":        "讓我幫您查詢請假簽核的審核人...",
  "memoryAction":          "none"
}
```

### 六個欄位逐一解析

| 欄位 | 怎麼組成 | 作用 | 儲存型態 |
|------|---------|------|---------|
| `intent` | LLM 從 4 種類型選一個 + 括號補充建議 Skill | 決定路由（走 RAG 或跳過）、載入哪些 Skill、maxSteps | 不存 DB，當次請求 if/else 判斷 |
| `taxonomyIds` | LLM 從現有 Taxonomy 節點清單中選取 | SQL WHERE 條件，縮小搜尋範圍 | 不存 DB，SQL 查詢參數 |
| `keywords` | LLM 從 query 萃取代表搜尋意圖的詞彙組 | L1 Cache Key 組成 + SQL 評分（kw_score / keyword_match_count_score） | 不存 DB，間接影響 Redis key |
| `mandatoryKeywords` | keywords 的子集，沒有就一定不是答案的詞 | SQL mandatory_score 評分維度 | 不存 DB，SQL 查詢參數 |
| `expertSearchKeywords` | 描述「人的職責」的詞彙，與 keywords 角度不同 | searchExperts() 搜尋 HR 員工表 | 不存 DB，函式參數 |
| `acknowledgment` | LLM 預生成的「我正在幫你查...」文字 | 串流給使用者作為即時回饋（UX 用） | 不存 DB，串流後丟棄 |
| `memoryAction` | LLM 判斷是否有值得記憶的新資訊 | 若非 none → 觸發 upsertUserMemory() 寫 pgvector | 本身不存 DB，但可觸發記憶寫入 |

### 總結：這 6 個欄位存在哪裡？

```
所有欄位 → TypeScript 物件（記憶體，請求結束就消失）
    │
    ├── intent              → if/else 判斷、Skill 載入邏輯
    ├── taxonomyIds         → SQL WHERE 參數
    ├── keywords            → SQL 評分參數 + Redis L1 key 的一部分
    ├── mandatoryKeywords   → SQL 評分參數
    ├── expertSearchKeywords → searchExperts() 參數
    ├── acknowledgment      → 串流前端，用後丟棄
    └── memoryAction        → 若非 none，觸發 pgvector 記憶寫入
                              （memoryAction 本身不存）
```

---

## 二、字詞解釋

### taxonomyIds

Taxonomy = 分類學。在 AI Hub 裡是**知識庫的分類樹**，概念類似圖書館的書架分類標籤。

```
Taxonomy Tree（分類樹）
├── tx_hr              ← 人力資源
│   ├── tx_hr_leave    ← 請假管理
│   └── tx_hr_salary   ← 薪資福利
├── tx_bpm             ← BPM 流程
│   └── tx_bpm_approval ← 簽核流程
├── tx_dcc             ← 受控文件
└── ...
```

每份文件在索引時會被掛上一個 taxonomy 節點；搜尋時只掃對應節點的文件。

---

### pg_trgm

`pg` = PostgreSQL；`trgm` = trigram（三元組）。

**原理**：把字串拆成每 3 個字元一組，比對兩段文字共有多少相同的 trigram 來算相似度。

```
"請假簽核"  →  ["請假簽", "假簽核"]
"apple"    →  ["app", "ppl", "ple"]
```

特點：不要求完全匹配，語意接近但用詞略不同的文件也能找到。是 PostgreSQL 的擴充模組。

#### pg_trgm 的兩層執行機制

pg_trgm 在 AI Hub 裡分兩層，功能不同：

**第一層：入場門檻（WHERE 條件）**

用 GIN index 快速過濾掉完全無關的 Segment，只留下候選集：

```sql
WHERE similarity(segment.content, '請假簽核') > 0.1
  AND segment.taxonomy_id = ANY(ARRAY['tx_bpm_approval', 'tx_hr_leave'])
```

這一步只是篩門檻，不決定排名。

**第二層：多維評分排名（ORDER BY）**

對候選集裡的每一筆 Segment，計算 5 個分數加總，取前 N 名：

| 評分維度 | 說明 |
|---|---|
| `sim_score` | 全文 trigram 相似度（0~1 之間） |
| `title_score` | 標題相似度，加權比內文高 |
| `kw_score` | 關鍵字在 Segment 裡出現次數 × 各詞重要性 |
| `mandatory_score` | mandatoryKeywords 若全部出現則加分 |
| `keyword_match_count` | 命中了幾個不同關鍵字 |

```sql
(sim_score + title_score + kw_score + mandatory_score + keyword_match_count_score)
  AS total_score
ORDER BY total_score DESC
LIMIT 20
```

設計目的：光靠 trigram 相似度，一篇湊巧相似但無關的文件可能混入；多維交叉驗證讓真正相關的文件排在最前面。

---

### Segment

文件不是整篇存入 DB，而是切成一段一段，每段叫 **Segment（段落 / 切片）**。

```
原始文件：《請假流程說明（5 頁 PDF）》
                  ↓ LibrarianAgent 切割
Segment 001：申請資格與假別說明
Segment 002：簽核流程（部門主管 → HR）
Segment 003：特殊假別規定
```

切割原因：LLM 的 context window 有限，只把「最相關的幾段」送進 LLM，省 token。

---

### L1 Cache

Cache = 快取，把算過一次的結果存起來，下次直接拿，不重新算。

L1、L2 是快取的層級：

```
L1 Cache（4 小時）：關鍵字 → 符合的 Segment ID 清單
    ↓ MISS
L2 Cache（24 小時）：完整問題 → 最終回覆文字
    ↓ MISS
LLM 生成（花時間、花 token）
```

- L1 = 「這幾個詞對應哪些文件」的索引快取
- L2 = 「這個問題的最終答案」的結果快取

---

### kw_score

kw = keyword（關鍵字）；score = 分數。

SQL 評分公式的其中一個維度：統計一個 Segment 裡關鍵字出現的次數與種類，換算成分數。

```
total_score = sim_score + title_score + kw_score + mandatory_score + keyword_match_count_score
```

---

## 三、query 的來源與 keywords 生成機制

### query 從哪裡來

就是使用者打的那句話，原封不動傳入函式：

```
使用者輸入 → "我的請假簽核會要給誰簽"
                  ↓
analyzeIntent(query)  ← query 就是這個字串
```

### keywords 是誰定義的？有沒有預設字典？

**沒有任何人事先定義，也沒有預設字典。** LLM 靠自身的語言理解能力自己決定。

System Prompt 只給方向指引，例如：
> 「從使用者問題中提取最能代表搜尋意圖的關鍵名詞、動詞和複合詞，用於後續資料庫查詢。」

LLM 讀到「我的請假簽核會要給誰簽」後，自行判斷：
- 「我的」是限定詞 → 不提取
- 「請假」是核心主題 → 提取
- 「簽核」是動作 → 提取
- 「審核人」是使用者真正想找的資訊 → 提取
- 「簽核流程」是相關概念 → 提取

### 有限制的欄位 vs 沒有限制的欄位

| 欄位 | 有無限制 | 原因 |
|------|---------|------|
| `taxonomyIds` | **有**，只能選現有節點 | LLM 收到完整節點清單作為參考 |
| `keywords` | **沒有**，LLM 自由生成 | 純語意提取，無預設字典 |
| `expertSearchKeywords` | **沒有**，LLM 自由生成 | 純語意提取，無預設字典 |

---

## 四、keywords vs expertSearchKeywords 的差異

兩者都不是對著資料庫已有內容生成的，都是純粹基於使用者問題文字的語意提取。

**核心差異：搜的目標不同。**

### keywords → 搜文件內容（pg_trgm）

偏向「會出現在文件正文裡的詞」：

```json
["請假", "簽核", "審核人", "簽核流程"]
  ↑ 這些詞很可能出現在 HR 政策文件的內文裡
```

### expertSearchKeywords → 搜人（HR 員工表）

偏向「描述一個人工作職責的說法」，通常比 keywords 更完整：

```json
["請假流程", "HR審核"]
  ↑ 員工資料表會寫「負責請假流程管理」
    而不只是「請假」這個單詞
```

即使問同一個問題，兩組關鍵字從不同角度描述同一件事——一個對準文件，一個對準人。

---

## 五、Taxonomy Tree 存在哪裡？

**存在 PostgreSQL 資料庫**，用 `parent_id` 自關聯形成樹狀結構：

```sql
-- ai_hub_taxonomy 表（示意）
id               | parent_id       | name
-----------------+------------------+------------------
tx_hr            | NULL             | 人力資源
tx_hr_leave      | tx_hr            | 請假管理
tx_bpm           | NULL             | BPM 流程
tx_bpm_approval  | tx_bpm           | 簽核流程
```

**為什麼還有 24hr 靜態快取？**

Taxonomy 節點很少變動，每次 `analyzeIntent` 都查 DB 太浪費。所以用 class-level 靜態變數把整棵樹快取在 Node.js 進程的記憶體裡，每 24 小時重讀一次：

```ts
class DeterministicRetrievalEngine {
  private static taxonomyCache: Taxonomy[] | null = null;  // class 層級變數
  private static cacheExpireAt: Date | null = null;

  private async getTaxonomies() {
    if (this.taxonomyCache && Date.now() < this.cacheExpireAt) {
      return this.taxonomyCache;  // 直接用記憶體裡的
    }
    this.taxonomyCache = await prisma.ai_hub_taxonomy.findMany();
    this.cacheExpireAt = Date.now() + 24 * 60 * 60 * 1000;
    return this.taxonomyCache;
  }
}
```

---

## 六、Segment 就是 RAG 的 Chunk 嗎？

**本質相同，但切割策略更精細。**

### 基礎 RAG 的 Chunk

```
固定大小切割（例如每 500 tokens，重疊 50 tokens）

[段落1: 500 tokens][段落2: 500 tokens][段落3: ...]
     ↑ 可能在句子中間切斷，語意不完整
```

### AI Hub 的 Segment

LibrarianAgent 把整份文件餵給 Kimi-k2.5（256K context），叫它依語意邊界分段：

```
原始 PDF：《請假辦法》（5 頁）
              ↓ LLM 語意分段
Segment 001：申請資格與假別說明（完整一節）
Segment 002：申請流程（含完整簽核路徑）
Segment 003：特殊狀況處理（完整一節）
     ↑ 每段在語意上是獨立完整的，不在句子中間切
```

### 對比表

| | 基礎 RAG Chunk | AI Hub Segment |
|---|---|---|
| 切割方式 | 固定 token 數 | LLM 語意理解後切 |
| 語意完整性 | 可能破碎 | 每段自成意義 |
| 切割執行者 | 程式規則 | Kimi-k2.5（256K）|
| 儲存位置 | 向量資料庫（通常） | PostgreSQL |
| 搜尋方式 | 向量相似度 | pg_trgm + 多維評分 |

> 注意：AI Hub 刻意**不用向量搜尋** Segment（只用 SQL）。pgvector 只用在「記憶體」那一塊。

### LibrarianAgent 分段只做一次嗎？

**對，只在文件上傳時做一次**，屬於離線前處理（offline ingestion pipeline），與查詢流程完全分開：

```
上傳 PDF/Word → LibrarianAgent → Kimi-k2.5 分段 → 存入 PostgreSQL（Segment 表）
```

全流程圖裡的 14 個 Stage 是「使用者問問題時」的線上路徑。到了 Stage 05/06 撈 Segment 時，那些 Segment 早就切好存在 DB 裡了，查詢時不會重新切割。

只有兩種情況才重新觸發分段：
- 文件被更新（新版本上傳）
- 管理員手動 re-index

### Segment 建立時有沒有做 Embedding？

**沒有。** Segment 存進 DB 時，只存了：
- 原始文字內容（`content`）
- Taxonomy ID（分類標籤）
- 標題（`docTitle`）

**沒有向量欄位**，搜尋時也不需要把問題轉成向量。整個 Segment 搜尋過程純 SQL，沒有任何 embedding API 呼叫。

這也是為什麼 Segment 搜尋只能靠字面三元組匹配，而不能做語意搜尋——這是開發者刻意的設計選擇（速度快、省成本、pg_trgm 對中文關鍵字匹配已夠用）。

---

## 七、L1/L2 Cache 的底層機制

### Redis 是什麼、住在哪裡

Redis 是一個**獨立執行的進程**，資料存在 **RAM（主記憶體）**，不是磁碟。

```
┌─────────────────────────────────────────────┐
│               作業系統（OS）                 │
│                                              │
│  ┌──────────────┐    ┌──────────────────┐   │
│  │  Node.js 進程 │    │   Redis 進程      │   │
│  │  (AI Hub API) │    │                  │   │
│  │               │TCP │  全部資料         │   │
│  │  ioredis 套件 │←──→│  存在這個進程的   │   │
│  │  （Redis 客戶端）│  │  Heap Memory     │   │
│  └──────────────┘    │  （RAM 裡）        │   │
│                       └──────────────────┘   │
└─────────────────────────────────────────────┘
```

Node.js 透過 **TCP Socket + RESP（Redis Serialization Protocol）** 與 Redis 通訊。

### Redis 的底層資料結構

Redis 內部用一張全域 **Hash Table（哈希表）** 管理所有 key，查找是 O(1)：

```
Redis 全域 Hash Table
┌────────────────────────────────────────────────────────────┐
│  hash(key)  →  value（Redis Object / robj）                 │
├────────────────────────────────────────────────────────────┤
│  "ai-hub:l1:v3:請假,簽核"  →  robj { "seg_001,seg_003,..." }│
│  "ai-hub:l2:v3:uid:md5"   →  robj { "您的請假單..." }       │
└────────────────────────────────────────────────────────────┘
```

### TTL 機制（不靠 OS Timer）

Redis 不是為每個 key 建一個計時器（太耗資源），用兩個機制：

```
① 懶刪除（Lazy Expiry）
   讀某個 key 時，Redis 先檢查「過期了嗎？」
   過期了 → 刪掉，回傳 null
   還沒   → 正常回傳

② 主動掃描（Active Expiry）
   每 100ms 隨機抽樣 20 個有 TTL 的 key
   過期的就刪除
   若這批有 > 25% 過期 → 繼續抽下一批
```

### AI Hub 的兩層 Cache

| | L1 Cache | L2 Cache |
|---|---|---|
| 存的內容 | 關鍵字 → Segment ID 清單 | 完整問題 → 最終回覆文字 |
| Key 格式 | `ai-hub:l1:{kbVersion}:{sorted_keywords}` | `ai-hub:l2:{kbVersion}:{userId}:{MD5(q+kw+ids)}` |
| TTL | 4 小時 | 24 小時 |
| 命中效果 | 跳過 SQL 掃描 | 跳過整個 LLM 生成 |

L2 key 含 `userId` 和可讀 segment IDs，確保不同權限使用者不共用答案（RBAC-aware）。

### Redis vs CPU L1/L2 Cache（同名不同物）

| | CPU L1/L2 Cache | Redis Cache（AI Hub） |
|---|---|---|
| 位置 | CPU 晶片內部 SRAM | RAM（主記憶體） |
| 大小 | KB 級 | GB 級 |
| 速度 | 0.5–10 ns（奈秒） | 0.1–1 ms（毫秒） |
| 管理者 | CPU 硬體自動 | 開發者手動設計 |
| 程式可控 | 不可控 | 完全可控 |

> AI Hub 的 L1/L2 只是借用「分層快取」的命名概念，實際上都是 Redis 應用層，與 CPU 硬體無關。

### 要不要持久化到磁碟？

Redis 預設是純記憶體，重啟後資料消失。可選兩種持久化：
- **RDB**：定期把整個資料集寫成二進位快照到磁碟
- **AOF**：每次寫操作都 append 到日誌檔

快取資料是「可以重新計算」的（cache miss → 重跑 SQL → 重新快取），所以 AI Hub 的快取**不需要持久化**。

---

## 八、Memory 系統深度解析

### 三種容易混淆的「記憶體」

在 AI Hub 的脈絡下，「記憶體」這個詞有三種完全不同的意思：

| 名稱 | 是什麼 | 存在哪裡 |
|---|---|---|
| **對話歷史（Session）** | 這輪對話的來回紀錄 | `ai_hub_message` 資料表，Stage 00 注入 |
| **使用者事實記憶（Memory）** | 跨 session 的使用者事實，如「直屬主管是 Amy」 | 獨立的 `ai_hub_memory` 表，Stage 02 向量搜尋 |
| **RAM 記憶體** | 電腦硬體空間 | 與這個系統完全無關 |

Stage 02 說的「記憶」是中間那個——系統把「某次對話中學到的使用者事實」持久化存起來，下次新 session 還能取用。

### 向量搜尋的使用範圍（全系統）

| 搜尋目標 | 是什麼 | 用什麼搜尋 | 有無 Embedding |
|---|---|---|---|
| **使用者記憶（Memory）** | 跨 session 使用者事實 | pgvector 向量搜尋 | **有** |
| **知識庫 Segment** | 文件段落 | pg_trgm + SQL 多維評分 | **完全沒有** |
| **Expert（人員）** | 員工表 | SQL 關鍵字匹配 | **完全沒有** |

記憶需要向量搜尋的原因：問「我的請假誰簽？」跟記憶「直屬主管是 Amy」字面上完全不同，必須靠語意相似度橋接。Segment 的關鍵字會直接出現在文件內文，字面匹配就夠用。

### 記憶儲存的 DB Schema（示意）

記憶存進 DB 時，同時存兩個欄位：

```
ai_hub_memory 表
┌─────────────┬──────────────────────────────────────────────┐
│ userId      │ "emp_001"                                    │
│ content     │ "直屬主管是 Amy Chen，部門為工程部"            │
│ embedding   │ [0.023, -0.187, 0.441, ...]（1536 維向量）    │
│ type        │ "fact"                                       │
│ status      │ "active"                                     │
│ createdAt   │ 2025-03-01T10:00:00Z                        │
└─────────────┴──────────────────────────────────────────────┘
```

搜尋時用：`ORDER BY embedding <=> query_vector`（pgvector 的 cosine 距離語法）。

### 記憶系統的設計位置（具體檔案）

這套記憶系統是開發者**完全自己設計的**，沒有任何框架預設行為。分散在三個檔案：

**`memory-store.ts`（底層）**
- `upsertUserMemory()`：把新事實轉成向量後存入 DB
- `search()`：把 query 轉成向量，用 cosine similarity 撈出相關記憶

**`omniscient-tools.ts` 第 281 行（寫入觸發點）**

```typescript
save_user_memory: tool({
  description: "主動記住使用者的偏好、長期事實或特定規則...",
  execute: async ({ content, key, type }) => {
    return await memoryStore.upsertUserMemory({ userId, content, key, type ... });
  },
}),
```

這是一個 LLM 工具。當 LLM 覺得「這句話值得記住」時，自主呼叫這個工具來觸發寫入——**不是每次對話都存，而是由 LLM 自己判斷**。

**`omniscient-agent-v2.ts` 第 499 行（偏好讀取）**

```typescript
// 一般 SQL，非向量搜尋，讀取暱稱/回應風格等靜態偏好
const preferences = await this.prisma.ai_hub_memory.findMany({
  where: { employeeId: acl.userId, status: "active", ... }
});
```

**`omniscient-agent-v2.ts` 第 561 行（語意搜尋讀取）**

```typescript
// pgvector 向量搜尋，找語意相關的記憶
const [relatedMemories, analysisResult] = await Promise.all([
  this.memoryStore.search(["ai-hub", acl.userId], { query, limit: 20 }),
  this.retrievalEngine.analyzeIntent(query),
]);
```

同一個 `ai_hub_memory` 表，根據需求走不同的讀取路徑：偏好用 SQL 直接撈，事實用向量搜。
