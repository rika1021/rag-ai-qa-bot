# RAG 架構對比筆記 — sideproject vs AI Hub

> 記錄時間：2026-09-11
> 目的：理解兩個系統在同一個 RAG 框架下，各階段的設計差異與原因

---

## 一、整體架構對比

### sideproject — 3 段式標準 RAG

```
文件上傳
   ↓
[Stage 1] Ingestion
   chunking → embedding → 寫入 ChromaDB
   ↓
[Stage 2] Retrieval
   embed 問題 → HNSW 向量搜尋 → 相似度過濾
   ↓
[Stage 3] Generator
   組合 prompt → Claude Haiku → 回傳答案
```

### AI Hub — 5 段式強化 RAG

```
文件上傳（觸發事件）
   ↓
[Stage 01] 文件採編 LibrarianAgent              ← 對應 Ingestion
   LLM 語意分段 → Taxonomy 匹配 → 存 PostgreSQL
   ↓
[Stage 02] 意圖分類 + 查詢分析                  ← 額外（sideproject 沒有）
   4-way 路由 → generateObject 取得 6 個欄位
   ↓
[Stage 03] 混合檢索 DeterministicRetrievalEngine ← 對應 Retrieval
   Taxonomy Routing → SQL pg_trgm 多維評分
   ↓
[Stage 04] JIT RBAC 權限過濾                    ← 額外（sideproject 沒有）
   Promise.all 並行校驗每筆文件的存取權限
   ↓
[Stage 05] 增強生成 OmniscientAgentV2            ← 對應 Generator
   動態 Skill Prompt → Multi-step Agentic Loop → Gemini 2.5 Flash
```

---

## 二、技術棧對比

| 項目 | sideproject | AI Hub |
|---|---|---|
| **LLM（生成）** | Claude Haiku 4.5 | Gemini 2.5 Flash |
| **LLM（採編）** | 無（規則切割） | Moonshot Kimi-k2.5（256K context） |
| **Embedding 模型** | paraphrase-multilingual-MiniLM-L12-v2（本地） | Google Vertex AI text-multilingual-embedding-002 |
| **向量資料庫** | ChromaDB（本地檔案） | PostgreSQL + pgvector（僅用於記憶體） |
| **文件搜尋方式** | 向量相似度（HNSW cosine） | SQL pg_trgm 多維評分（**不用向量**） |
| **文件儲存** | ChromaDB 本地 | PostgreSQL |
| **快取** | 無 | Redis 雙層（L1 4hr / L2 24hr） |
| **AI SDK** | Anthropic SDK | Vercel AI SDK（streamText / generateObject） |
| **後端語言** | Python + FastAPI | TypeScript + NestJS |
| **前端** | Streamlit | SvelteKit |

---

## 三、Ingestion 階段對比（Stage 01）

### sideproject

```python
# 切割：空行語意切割 + RecursiveCharacterTextSplitter 兜底
raw_paragraphs = text.split("\n\n")
# 超過 500 字才用 RecursiveCharacterTextSplitter 細切

# Embedding：本地模型轉 384 維向量
embeddings = embed(chunks)

# 儲存：向量 + 原文一起存進 ChromaDB
collection.add(ids=..., documents=chunks, embeddings=embeddings, metadatas=...)
```

**特點：**
- 文字切割是程式規則（空行 + 字數），不用 LLM
- 採編時就做 Embedding，向量存在 ChromaDB
- 只支援一種文件來源（本地上傳）

### AI Hub

```
Step 1: 內容提取
    DCC: S3 → pdf-parse 解析 → 送 Kimi-k2.5 結構化分段
    KMS: S3 → 直接讀 Markdown
    BPM: DB → form_data JSON → 轉文字
    HR:  DB → 員工欄位 → 組合文字

Step 2: Taxonomy 匹配
    LLM 讀文件摘要 → 從 ai_hub_taxonomy 表選最吻合的分類 ID

Step 3: 寫入資料庫（Transaction）
    刪除舊 segments → 建立新 ai_hub_segment → 建立分類關聯

Step 4: 寫 ai_hub_index_log（Token 用量、處理時間）
```

**特點：**
- 切割由 Kimi-k2.5（256K context）閱讀整份文件後依語意邊界決定
- **採編時完全不做 Embedding**，Segment 只存純文字
- 自動套用 Scrubber Policy 脫敏（手機號、財務數據）
- Taxonomy 自動擴展：LLM 可建議新增分類節點

### 關鍵差異

| | sideproject | AI Hub |
|---|---|---|
| **切割執行者** | 程式規則 | Kimi-k2.5 LLM |
| **語意完整性** | 可能在句子中間斷 | 每段自成完整語意 |
| **採編時做 Embedding** | **有** | **完全沒有** |
| **儲存型態** | ChromaDB（向量 + 文字） | PostgreSQL（純文字 + 分類標籤） |
| **文件來源數** | 1 種 | 4 種（KMS/DCC/BPM/HR） |
| **PII 脫敏** | 無 | 有 |

---

## 四、額外 Stage 02 — 意圖分類 + 查詢分析（AI Hub 獨有）

sideproject **沒有這個階段**，所有問題都直接走完整 RAG 管線。

AI Hub 在進 Retrieval 之前，先用一次 LLM 呼叫做兩件事：

**第一層：4-way 意圖分類**

```
使用者問題
   ↓
   ├── CHITCHAT      → 直接回答，不查知識庫（Fast Path）
   ├── SKILL_ACTION  → 直接呼叫工具
   ├── PEOPLE_FINDER → 搜人員資料庫（Fast Path）
   └── KNOWLEDGE_QA  → 走完整 RAG 管線
```

**第二層：查詢分析（KNOWLEDGE_QA 才觸發）**

一次 `generateObject` 呼叫，取得 6 個欄位：

| 欄位 | 作用 |
|---|---|
| `taxonomyIds` | SQL WHERE 條件，縮小搜尋範圍 |
| `keywords` | SQL 評分參數 + L1 Cache Key |
| `mandatoryKeywords` | 必須出現的詞，SQL 加權評分 |
| `expertSearchKeywords` | 搜員工資料庫用（與文件關鍵字角度不同） |
| `acknowledgment` | 串流給前端的開場白（UX 用） |
| `memoryAction` | 是否將本次問題存入長期記憶 |

**為什麼這個設計重要：**
傳統做法需要 3-4 次 LLM 呼叫分別取得這些資訊，AI Hub 用一次 `generateObject` 全部拿到，大幅節省 Token 和延遲。

---

## 五、Retrieval 階段對比（Stage 03）

### sideproject

```python
# 問題也做 Embedding（與 Ingestion 同一個模型）
query_embedding = embed([query])[0]

# HNSW 向量搜尋：O(log N) 近似最近鄰
results = collection.query(
    query_embeddings=[query_embedding],
    n_results=5,
)

# 距離轉相似度，過濾門檻
similarity = 1 - distance
if similarity >= 0.3:
    filtered_chunks.append(doc)
```

**搜尋邏輯：** 把問題轉成向量，在 384 維空間找最近的 Segment。

### AI Hub

```sql
-- Taxonomy Routing 先縮小範圍（Stage 02 拿到的 taxonomyIds）
WHERE rel.taxonomy_id IN ({taxonomyIds})
   OR content ILIKE ANY({keywords})

-- 5 維複合評分（不是單一 cosine similarity）
SELECT *,
    similarity(content, {query})  AS sim_score,          -- pg_trgm trigram
    CASE WHEN doc_title ILIKE '%{kw}%' THEN 2.0 END      AS title_score,
    CASE WHEN content ILIKE '%{kw}%' THEN 1.0 END        AS kw_score,
    CASE WHEN content ILIKE '%{mandatory}%' THEN 1.5 END AS mandatory_score,
    COUNT(matched_keywords) * 2.0                         AS keyword_match_count_score
ORDER BY total_score DESC
LIMIT 40
```

**搜尋邏輯：** SQL trigram 字面匹配，不需要向量，速度快、省成本。

### 關鍵差異

| | sideproject | AI Hub |
|---|---|---|
| **搜尋方式** | 向量相似度（HNSW cosine） | SQL pg_trgm 多維評分（**完全不用向量**） |
| **問題要做 Embedding 嗎** | **要** | **不需要** |
| **搜尋範圍** | 全量（HNSW 加速） | Taxonomy Routing 先縮小，再評分 |
| **評分維度** | 1 維（cosine similarity） | 5 維複合評分 |
| **快取** | 無 | L1 Redis：關鍵字 → Segment ID（4 小時） |
| **Expert 搜尋** | 無 | 與文件搜尋並行（Promise.all） |

---

## 六、額外 Stage 04 — JIT RBAC 權限過濾（AI Hub 獨有）

sideproject **沒有權限控制**，所有文件對所有人可見。

AI Hub 在 Retrieval 拿到 Segment 後，**即時**（Just-In-Time）查資料庫校驗每筆文件的存取權限：

| 來源 | 存取條件 |
|---|---|
| KMS | 作者本人 OR kmsAclEntry 匹配（user/dept/all）；無記錄 = 公開 |
| BPM | 作者本人 OR 在簽核鏈（bpm_task_sign）上 |
| DCC | 預設公開 |
| HR | 預設公開 |

**被攔截時不直接丟棄，而是：**
1. 記錄發布人資訊
2. 傳給 LLM → LLM 在回覆中告知「該文件由 XX 發布，請向其申請權限」
3. 寫稽核 Log（unauthorized_attempt）

**JIT vs 靜態權限的差異：**
靜態做法是建索引時就決定誰能看，後來權限變動就會對不上。JIT 是每次查詢當下即時查最新 DB，確保文件剛被撤銷也立即生效。

---

## 七、Generator 階段對比（Stage 05）

### sideproject

```python
# 固定 System Prompt
SYSTEM_PROMPT = "你是客服助理，只能根據【參考文件】回答..."

# 單次生成
response = client.messages.create(
    model="claude-haiku-4-5-20251001",
    system=SYSTEM_PROMPT,
    messages=[{"role": "user", "content": user_message}],
)
```

**特點：** 一問一答，Prompt 固定，單次生成。

### AI Hub

```typescript
// System Prompt 動態組裝（三層 Skill）
// 1. 基礎意圖技能（KNOWLEDGE_QA 載入 ai-hub-knowledge-retrieval）
// 2. LLM 建議的專業技能（括號內，如 ai-hub-bpm）
// 3. 關鍵字觸發的技能（query 含「請假」→ 自動載入 ai-hub-hr-specialist）

// Multi-step Agentic Loop（最多 5 步）
const result = await streamText({
  model: gemini25Flash,
  system: dynamicSystemPrompt,  // 動態組裝
  tools: skillTools,            // 按 Skill 按需開放
  stopWhen: stepCountIs(5),
  maxSteps: 5,
});
```

**可用工具：**

| Tool | 用途 |
|---|---|
| `search_knowledge_base` | Context 不足時主動補充查詢 |
| `search_expert` | 搜負責人員工資料 |
| `get_article_content` | 讀 KMS 完整全文（從 S3） |
| `search_my_bpm_records` | 查個人待簽核任務 |
| `save_user_memory` | 主動記住使用者偏好 |
| `load_specialized_skill` | 動態加載更多專業指令 |

**雙層 Redis 快取：**
```
L1：keyword → segmentIds（4 小時）
    → 命中時跳過 PostgreSQL 查詢

L2：完整問題 → 最終回覆文字（24 小時）
    → 命中時完全跳過 LLM 生成
    → Key 含 userId + segmentIds，不同權限不共用答案
```

**pgvector 長期記憶：**
```
寫入：LLM 自主決定是否呼叫 save_user_memory Tool
查詢：每次 KNOWLEDGE_QA 自動觸發（與意圖分析並行）
向量：text-multilingual-embedding-002（768 維）
用途：跨 session 記住「直屬主管是 Amy」等事實
```

### 關鍵差異

| | sideproject | AI Hub |
|---|---|---|
| **System Prompt** | 固定字串 | 動態三層 Skill 組裝 |
| **生成模式** | 單次 generate | Multi-step Agentic Loop（最多 5 步）|
| **長期記憶** | 無 | pgvector 跨 session 持久化 |
| **答案快取** | 無 | L2 Redis（含 userId 防越權） |
| **工具數量** | 0 | 8 個，按 Skill 按需開放 |

---

## 八、最關鍵的設計差異：向量的使用方式

這是兩個系統最根本的不同：

### sideproject：向量是核心搜尋機制

```
Ingestion: 文字 → Embedding → 向量存 ChromaDB
Retrieval: 問題 → Embedding → cosine similarity 找最近鄰
```

向量是搜尋本身，問題和文件都要轉向量才能比對。

### AI Hub：向量只用在「記憶體」，不用在文件搜尋

```
Ingestion:  文字 → PostgreSQL（無 Embedding，無向量）
Retrieval:  問題 → pg_trgm SQL（無 Embedding，純文字比對）

長期記憶:   事實 → Embedding → pgvector（這裡才用向量）
```

**為什麼這樣設計？**
- 文件關鍵字會直接出現在文件內文，字面 trigram 匹配就夠用
- 省去每次查詢的 Embedding API 呼叫（速度快、成本低）
- 長期記憶需要語意橋接（問「誰是我主管」→ 記憶「Amy 是我主管」，字面完全不同），才需要向量

---

## 九、10 項優化對比（AI Hub vs 基礎 RAG）

| # | 優化項目 | sideproject | AI Hub |
|---|---|---|---|
| 1 | **文件分段** | 規則切割（空行 + 字數） | Kimi-k2.5 LLM 語意分段 |
| 2 | **Taxonomy Routing** | 無，全量搜尋 | 預先分類，查詢縮小範圍 |
| 3 | **意圖前置路由** | 無，所有問題走完整 RAG | 4-way 分類，非 QA 跳過 RAG |
| 4 | **Expert 並行預載** | 無 | 文件搜尋 + 員工搜尋 Promise.all |
| 5 | **JIT 權限過濾** | 無 | 查詢當下即時校驗最新 DB 狀態 |
| 6 | **RBAC 感知快取** | 無 | L2 Key 含文件 ID 集合，安全隔離 |
| 7 | **pgvector 長期記憶** | 無 | 使用者偏好跨 session 持久化 |
| 8 | **Multi-step Agentic** | 單次生成 | 最多 5 步，LLM 自行補充資料 |
| 9 | **Taxonomy 自動擴展** | 靜態分類 | LLM 可建議新增分類節點 |
| 10 | **PII 自動脫敏** | 無 | 採編時自動遮蔽個資 |

---

*相關筆記：*
- *sideproject 詳細筆記：[RAG-ingestion-stage.md](RAG-ingestion-stage.md) / [RAG-retrieval-stage.md](RAG-retrieval-stage.md) / [RAG-generator-stage.md](RAG-generator-stage.md)*
- *AI Hub 詳細架構：[富宸-aihub/aihub-rag-architecture.md](富宸-aihub/aihub-rag-architecture.md)*
- *AI Hub 意圖分析深度解析：[富宸-aihub/aihub-intent-analysis.md](富宸-aihub/aihub-intent-analysis.md)*
