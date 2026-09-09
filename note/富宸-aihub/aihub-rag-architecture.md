# 富宸 AI Hub — RAG 架構深度分析
>
> 📋 **架構介紹專用（互動 HTML）**：https://claude.ai/code/artifact/1dfe6109-b6f8-4f97-a689-4e9aebb63857
> 📋 **完整講稿（含口語）**：`富宸-aihub/aihub-script-full.txt`
>
> 📊 **視覺化互動報告**：https://claude.ai/code/artifact/31a80903-855f-4e27-96e3-fb49b33aa7a0
>
> 🎯 **面試五問完整解答**：https://claude.ai/code/artifact/c377d25d-6ada-4cbc-b451-718802d41354
>
> 🔍 **端到端流程追蹤（請假查詢全流程）**：https://claude.ai/code/artifact/e8c2bcb4-ae19-4759-a0f5-54f848af33f3
>
> 📖 **意圖分析深度學習筆記**：`sideproject/note/aihub-intent-analysis.md`
>
> 原始碼位置：`bpm-backend-main/src/module/ai-hub/`

---

## 目錄

1. [結論先說：有沒有用 RAG？](#一結論先說有沒有用-rag)
2. [整體架構（五段式管線）](#二整體架構五段式管線)
3. [Stage 01 — 文件採編（LibrarianAgent）](#三stage-01--文件採編librarianagent)
4. [Stage 02 — 意圖分類 + 查詢分析](#四stage-02--意圖分類--查詢分析)
5. [Stage 03 — 混合檢索（DeterministicRetrievalEngine）](#五stage-03--混合檢索deterministicretrievalengine)
6. [Stage 04 — JIT RBAC 權限過濾](#六stage-04--jit-rbac-權限過濾)
7. [Stage 05 — 增強生成（OmniscientAgentV2）](#七stage-05--增強生成omniscientagentv2)
8. [優化總整理（10 項 vs 基礎 RAG）](#八優化總整理10-項-vs-基礎-rag)

---

## 一、結論先說：有沒有用 RAG？

**有，而且是強化版。**

| 技術棧 | 說明 |
|--------|------|
| LLM（生成） | Google Vertex AI — Gemini 2.5 Flash |
| LLM（採編） | Moonshot Kimi-k2.5（256K context） |
| 向量資料庫 | PostgreSQL + pgvector（記憶用） |
| 文件檢索 | PostgreSQL + pg_trgm（SQL trigram 相似度） |
| 快取 | Redis（雙層：L1 / L2） |
| AI SDK | Vercel AI SDK（`streamText` / `generateObject`） |
| Embedding | Google Vertex AI `text-multilingual-embedding-002` |
| 事件驅動 | AWS SQS（採編任務隊列） |
| 檔案儲存 | AWS S3（KMS / DCC 原始文件） |

---

## 二、整體架構（五段式管線）

```
[文件來源]
KMS / DCC / BPM / HR
        │  (觸發採編事件)
        ▼
┌─────────────────────────────────────────────────────────┐
│  Stage 01: 文件採編 (Offline)                            │
│  LibrarianAgent  ←  Kimi-k2.5 (256K)                   │
│  PDF解析 → LLM結構化分段 → Taxonomy匹配 → 存 DB          │
└───────────────────────────┬─────────────────────────────┘
                            │  (ai_hub_segment 表)
                            ▼
                    [PostgreSQL 知識庫]

─────────────────── 以下為查詢時觸發 ───────────────────────

使用者提問
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│  Stage 02: 意圖分類 + 查詢分析 (Online)                  │
│  Gemini 2.5 Flash                                        │
│  4-way 分類 → 若 QA: generateObject 取得 6 個欄位        │
└───────────────────────────┬─────────────────────────────┘
                            │  (taxonomyIds / keywords)
                            ▼
┌─────────────────────────────────────────────────────────┐
│  Stage 03: 混合檢索 (Online)                             │
│  DeterministicRetrievalEngine                            │
│  Taxonomy Routing + SQL 多維評分 + Expert 並行預載        │
└───────────────────────────┬─────────────────────────────┘
                            │  (rawSegments + experts)
                            ▼
┌─────────────────────────────────────────────────────────┐
│  Stage 04: JIT RBAC 權限過濾 (Online)                    │
│  Promise.all 並行校驗每筆文件的即時存取權限               │
└───────────────────────────┬─────────────────────────────┘
                            │  (authorizedSegments)
                            ▼
┌─────────────────────────────────────────────────────────┐
│  Stage 05: 增強生成 (Online)                             │
│  OmniscientAgentV2  ←  Gemini 2.5 Flash (Reasoner)     │
│  動態 Skill Prompt + Multi-step Tools + Redis 快取       │
└─────────────────────────────────────────────────────────┘
    │
    ▼
串流回應（SSE）→ 前端
```

---

## 三、Stage 01 — 文件採編（LibrarianAgent）

**檔案**：`services/librarian-agent.ts`、`services/dcc-processor.ts`

### 四種來源的處理方式

| 來源 | 取得方式 | 分段策略 |
|------|----------|----------|
| KMS | 從 S3 下載 Markdown | 整份文件為 1 個 segment |
| DCC | 從 S3 下載 PDF / 文字檔 | **LLM 結構化分段**（Kimi-k2.5） |
| BPM | 讀 `form_data` JSON | 整份為 1 個 segment（只處理 approved） |
| HR | 讀員工資料表 | 整份員工資料為 1 個 segment |

### 採編完整流程（4 步）

```
Step 1: 內容提取
    DCC: S3 → pdf-parse 本地解析文字 → 送 Kimi-k2.5 結構化分段
    KMS: S3 → 直接讀 Markdown
    BPM: DB → form_data JSON → 轉文字
    HR:  DB → 員工欄位 → 組合文字

Step 2: Taxonomy 匹配
    LLM 讀文件摘要 → 從 ai_hub_taxonomy 表選最吻合的 ID
    若無匹配 → 可建議新增分類（自動擴展）

Step 3: 寫入資料庫（Transaction）
    刪除舊 segments（同 sourceId + sourceType）
    → 建立新 ai_hub_segment
    → 建立 ai_hub_segment_taxonomy 關聯

Step 4: 寫 ai_hub_index_log（Token 用量、處理時間）
```

### Kimi-k2.5 分段的 JSON 輸出格式

```json
{
  "segments": [
    {
      "title": "退貨政策 > 申請條件",
      "content": "...",
      "chapter": "第三章",
      "sequence": 0
    }
  ]
}
```

### vs 基礎 RAG 的優化

| 優化項目 | 基礎 RAG | AI Hub 做法 |
|----------|----------|-------------|
| **分段方式** | 固定字元數（如 512 tokens）切割 | LLM 依章節語意切割，保留 chapterInfo / pageNumber |
| **PII 脫敏** | 無 | 分段時套用 Scrubber Policy，遮蔽手機號、財務數據 |
| **分類自動擴展** | 無 | LLM 可建議新增 Taxonomy，隨業務演化 |

---

## 四、Stage 02 — 意圖分類 + 查詢分析

**檔案**：`services/omniscient-agent-v2.ts`（`chatStream` 方法）

### 第一層：4-way 意圖分類

```
使用者問題
    │
    ▼ (generateText, Gemini 2.5 Flash)
    ├── CHITCHAT      → Fast Path，1 step，不查知識庫
    ├── SKILL_ACTION  → 直接呼叫 Tool，2 steps
    ├── PEOPLE_FINDER → Expert Search Fast Path，2 steps
    └── KNOWLEDGE_QA  → 完整 RAG 管線，最多 5 steps
```

### 第二層：查詢分析（單次複合輸出）

針對 `KNOWLEDGE_QA`，用 `generateObject` + Zod Schema **一次 LLM 呼叫**取得：

```typescript
{
  taxonomyIds: string[]          // 匹配的分類 ID → 後續 SQL 過濾用
  keywords: string[]             // 核心檢索關鍵字
  mandatoryKeywords: string[]    // 必須包含的術語（高權重）
  expertSearchKeywords: string[] // 專家搜尋關鍵字（並行 Expert Search 用）
  acknowledgment: string         // 擬人化開場白，前端 streaming 第一句
  memoryAction: {
    shouldStore: boolean         // 是否將本次問題存入長期記憶
    type: string
    content: string
  }
}
```

### vs 基礎 RAG 的優化

| 優化項目 | 基礎 RAG | AI Hub 做法 |
|----------|----------|-------------|
| **意圖前置路由** | 所有問題都走完整 RAG | 閒聊 / 指令提前分流，跳過知識庫查詢 |
| **複合輸出** | 多次 LLM 呼叫取得不同資訊 | 一次 `generateObject` 取得 6 個欄位 |

---

## 五、Stage 03 — 混合檢索（DeterministicRetrievalEngine）

**檔案**：`services/deterministic-retrieval-engine.ts`（`v2Retrieve`、`fetchSegments` 方法）

### 評分公式（樓層定位模式 / 有 taxonomyIds）

```sql
WITH ranked AS (
    SELECT *,
        similarity(s.content, {query}) as sim_score,           -- pg_trgm trigram 相似度
        CASE WHEN doc_title ILIKE '%{query}%' THEN 2.0 END as title_score,
        CASE WHEN content ILIKE '%{kw1}%' THEN 1.0 END as kw_score,
        CASE WHEN content ILIKE '%{mandatory}%' THEN 1.5 END as mandatory_score,
        (SELECT COUNT(DISTINCT k)
         FROM unnest({keywords}) k
         WHERE content ILIKE '%' || k || '%') * 2.0 as keyword_match_count_score
    FROM ai_hub_segment s
    LEFT JOIN ai_hub_segment_taxonomy rel ON s.id = rel.segment_id
    WHERE rel.taxonomy_id IN ({taxonomyIds})
       OR content ILIKE ANY({keywords})
)
SELECT * FROM ranked
WHERE (sim_score + title_score + kw_score + mandatory_score + keyword_match_count_score) > 0.1
ORDER BY score DESC
LIMIT 40
```

全域模式（無 taxonomyIds）：相同評分邏輯，去掉分類過濾，`LIMIT 15`。

### Expert 並行預載（主動式）

```typescript
// Segment 搜尋與 Expert 搜尋同時發出，不互相等待
const [rawSegments, preloadedExperts] = await Promise.all([
  segmentSearch,    // SQL 知識庫檢索
  expertSearch,     // 員工資料庫查詢（responsibilities / title / name）
]);
```

Expert 搜尋優先級：`expertSearchKeywords[0]` > `keywords[0]` > Taxonomy mainCategory 提取的部門名

### vs 基礎 RAG 的優化

| 優化項目 | 基礎 RAG | AI Hub 做法 |
|----------|----------|-------------|
| **搜尋範圍** | 全量向量搜尋 | Taxonomy Routing 先縮小範圍，再評分 |
| **評分維度** | 單一 cosine similarity | 5 維複合評分（相似度 + 標題 + 關鍵字 + 必要詞 + 覆蓋率） |
| **Expert 搜尋** | 無 | 與文件搜尋並行，結果直接放入 context |
| **L1 快取** | 無 | Redis 快取 `keywords → segmentIds`，TTL 4hr |

---

## 六、Stage 04 — JIT RBAC 權限過濾

**檔案**：`services/deterministic-retrieval-engine.ts`（`checkRealtimeAccess` 方法）

### 各來源的權限規則

| 來源 | 條件 1（狀態） | 條件 2（身份）|
|------|---------------|---------------|
| **KMS** | `status = published` | 作者本人 OR kmsAclEntry 匹配（user/dept/all）; 無 ACL 記錄 = 公開 |
| **BPM** | `status = approved` | 作者本人 OR 在 `bpm_task_sign`（簽核鏈）上 |
| **DCC** | 無（預設公開） | — |
| **HR** | 無（預設公開） | — |

### 被攔截的受限內容處理

```
攔截 → 記錄發布人（creatorName / creatorDept）
     → 批量查詢發布人英文名稱補全
     → 放入 restrictedAuthors 傳給 LLM
     → LLM 在回覆中告知：「該文件由 XX 發布，請向其申請權限」
     → Trace Log 記錄 unauthorized_attempt 稽核事件
```

### vs 基礎 RAG 的優化

| 優化項目 | 基礎 RAG | AI Hub 做法 |
|----------|----------|-------------|
| **校驗時機** | 靜態（建索引時決定） | JIT（每次查詢當下即時查 DB） |
| **受限內容** | 直接丟棄 | 告知存在、引導申請權限，兼顧安全與體驗 |

---

## 七、Stage 05 — 增強生成（OmniscientAgentV2）

**檔案**：`services/omniscient-agent-v2.ts`、`services/omniscient-tools.ts`、`services/skill-loader.ts`

### Skill-Native 動態 System Prompt

System Prompt **不是固定字串**，由三層動態組裝：

```
1. 基礎意圖技能（由 intent 決定，從 manifest.json 讀取）
   → KNOWLEDGE_QA 載入 ai-hub-knowledge-retrieval 等核心技能

2. LLM 建議的專業技能（intent 括號內）
   → KNOWLEDGE_QA (ai-hub-bpm) → 額外載入 ai-hub-bpm 技能

3. 關鍵字觸發的技能（manifest.json triggers 設定）
   → query 包含「請假」→ 觸發 ai-hub-hr-specialist

每個技能 = data/skills/{name}/SKILL.md（YAML Frontmatter 宣告允許使用的 Tool）
```

### 可用工具組（Agent Tools，每次根據 Skill 按需開放）

| Tool 名稱 | 用途 |
|-----------|------|
| `search_knowledge_base` | 主動補充查詢，Context 不足時使用 |
| `search_expert` | 根據職責 / 部門關鍵字搜尋負責人 |
| `get_article_content` | 讀取 KMS 文章完整全文（從 S3） |
| `search_my_bpm_records` | 查詢個人待簽核任務或已發起文件 |
| `save_user_memory` | 主動記住使用者偏好與事實 |
| `load_specialized_skill` | 動態加載更多專業指令（HR / 法務 / 財務） |
| `update_bot_profile` | 更新 AI 助手頭像與暱稱 |
| `read_document_content` | 讀取指定 Segment 的完整內容 |

### 雙層 Redis 快取

```
L1：keyword → segmentIds
    Key:   ai-hub:l1:{version}:{sorted_keywords}
    Value: ["seg_id_1", "seg_id_2", ...]
    TTL:   4 小時
    作用:  命中 → 跳過 PostgreSQL 查詢，直接用 ID 取資料

L2：最終 LLM 答案
    Key:   ai-hub:l2:{version}:{MD5(query|keywords|segmentIds|userId)}
    Value: 完整回覆文字
    TTL:   24 小時
    作用:  命中 → 完全跳過 LLM，直接串流快取內容
    安全:  Key 含 segmentIds（代表使用者實際可讀的文件集合），不同權限不共用快取
```

### pgvector 長期記憶（AiHubMemStore）

```
寫入時機：AI 判斷值得記憶 → 呼叫 save_user_memory Tool
Embedding 模型：text-multilingual-embedding-002（Google Vertex AI）
向量維度：根據模型（768 維）
儲存位置：ai_hub_memory 表（PostgreSQL pgvector）

查詢時機：每次 KNOWLEDGE_QA 自動觸發，與意圖分析並行執行
查詢方式：cosine similarity，取 top 20，注入 System Prompt 的「悄悄話」區塊
```

### vs 基礎 RAG 的優化

| 優化項目 | 基礎 RAG | AI Hub 做法 |
|----------|----------|-------------|
| **System Prompt** | 固定字串 | 根據意圖動態組合 Skill 文件，最小工具暴露 |
| **推理模式** | 單次 Generate | Multi-step Agentic Loop，最多 5 步（`stopWhen: stepCountIs(5)`） |
| **長期記憶** | 無跨對話記憶 | pgvector 儲存使用者偏好，跨對話持久化 |
| **答案快取** | 無 | L2 Redis 快取（含 userId 防止越權） |
| **上下文裁剪** | 無 | `pruneMessages` 壓縮歷史，節省 Token |

---

## 八、優化總整理（10 項 vs 基礎 RAG）

| # | 優化項目 | 基礎 RAG | AI Hub |
|---|----------|----------|--------|
| 1 | **文件分段** | 固定 chunk size | LLM（Kimi-k2.5）依語意結構分段 |
| 2 | **Taxonomy Routing** | 無，全量搜尋 | 預先分類，查詢時縮小範圍 |
| 3 | **意圖前置路由** | 無 | 4-way 分類，非 QA 意圖跳過 RAG |
| 4 | **Expert 並行預載** | 無 | 與文件搜尋並行，省去後續 Tool 呼叫 |
| 5 | **JIT 權限過濾** | 靜態索引 | 查詢當下即時校驗最新 DB 狀態 |
| 6 | **RBAC 感知快取** | 無 | L2 Key 含文件 ID 集合，安全隔離 |
| 7 | **pgvector 長期記憶** | 無 | 使用者偏好跨對話持久化 |
| 8 | **Multi-step Agentic** | 單次生成 | 最多 5 步，LLM 自行補充資料 |
| 9 | **Taxonomy 自動擴展** | 靜態分類 | 採編時 LLM 可建議新增分類 |
| 10 | **PII 自動脫敏** | 無 | 分段時濾除個資，防止敏感資料進知識庫 |
