# Phase 1：確認 pytest 測試可跑

> 學習計劃對應章節：Phase 1（約 0.5 天）
> 完成日期：2026-09-22
> 狀態：✅ 完成

---

## 一、核心概念整理

### Regression Test（退步測試）

Regression test 的目的是**確認每次改動之後，品質指標沒有變差**。
它不是在測試「功能是否正確」，而是在測試「我改了某個東西，有沒有讓系統變爛」。

這個專案的情境：每次調整 chunking 策略、embedding 模型、similarity threshold，
都要確保 recall@3、MRR、faithfulness、answer_relevancy 這四個分數沒有掉到閾值以下。

#### 測試類型對照表

| 類型 | 測試什麼 | 例子 |
|------|---------|------|
| **Unit test** | 一個函式的邏輯是否正確 | `split_text("abc", size=2)` 應該回傳 `["ab", "c"]` |
| **Integration test** | 幾個模組組合在一起有沒有壞掉 | API endpoint 打進去，資料庫有沒有正確寫入 |
| **Regression test** | 改動後整體品質有沒有退步 | 改了 chunking，recall@3 有沒有掉下來 |

Regression test 是一個**用途描述**，不是技術類型，可以用 pytest 或任何框架實作。
它和 unit test 是平行關係，不是包含關係。

#### 為什麼這個專案用 regression test 而非 unit test？

RAG 系統的「正確性」很難用 unit test 驗證：
- 你無法寫「給這個問題，函式必須回傳這個字串」——LLM 每次說法不同
- chunking 改一點，向量搜尋結果就不一樣，也無法寫死期望值

能做的就是：**跑一批標準問題，量化品質分數，確認分數沒有掉**。
這就是 regression test 在 ML/AI 系統中的核心價值。

### pytest fixture

Fixture 是「測試用的共享前置資料或設定」，讓多個測試函式可以共用同一份準備好的物件，
不需要在每個 test 函式裡重複寫準備的程式碼。

```python
@pytest.fixture(scope="session")
def eval_results():
    # 這個 fixture 整個測試 session 只跑一次
    return json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
```

`scope="session"` 代表這個 fixture 在整個 `pytest` 執行過程中只初始化一次，
所有使用它的測試函式共用同一個 `eval_results` 物件，不會重複讀取 JSON 檔。

### conftest.py 的作用

`conftest.py` 是 pytest **自動載入**的設定檔。
放在這裡的 fixture 不需要被 import，pytest 在收集測試時會自動找到並讓測試使用。

這個專案的 `conftest.py` 做了兩件事：
1. 在所有測試跑之前，載入 `.env` 檔（讓 `ANTHROPIC_API_KEY` 可用）
2. 定義 `eval_results` fixture（讀取 `eval/results.json`）

### pytest.skip() vs FAILED

| 狀態 | 什麼時候出現 | 代表什麼 | CI 會報警嗎 |
|------|------------|---------|------------|
| SKIPPED | `pytest.skip()` 被呼叫，或前置條件不滿足 | 測試沒有執行 | 不會 |
| FAILED | 測試執行了，但 `assert` 失敗 | 程式碼有問題 | 會阻擋 merge |
| PASSED | 測試執行了，所有 `assert` 通過 | 一切正常 | 不會 |

這個專案的設計：如果 `eval/results.json` 不存在，fixture 呼叫 `pytest.skip()`，
讓測試變成 SKIPPED 而不是 FAILED。

為什麼這樣設計？因為在新機器、新 clone 的環境下，
`eval/results.json` 還不存在是正常狀態（還沒跑過 `python eval/run_eval.py`）。
這種情況不是「程式碼壞掉」，不應該觸發 CI 警報。

### 為什麼 CI 不需要 ANTHROPIC_API_KEY

這些 regression tests **只讀 `eval/results.json`，做數字斷言**，完全不呼叫 Claude API。

整個流程是分兩步的：
1. **手動在本機**跑 `python eval/run_eval.py`（這步需要 API key，會真的打 Claude API）
   → 產出 `eval/results.json`，commit 進 repo
2. **CI 跑** `pytest tests/ -v`（讀已存在的 JSON，不需要 API key）
   → 確認分數沒有退步

CI 的職責是「驗證結果有沒有退步」，不是「重新產生結果」，所以不需要金鑰。

#### 完整工作流程圖

```
開發者在本機                              GitHub Actions (CI)
─────────────────────────────────────     ────────────────────────────────
1. 調整了 chunking 策略（改了程式碼）
2. 手動跑：python eval/run_eval.py
   → 真的呼叫 Claude API，跑 12 題問答
   → 產出 eval/results.json（新的分數）
3. 看分數有沒有進步/退步
4. 滿意了，git add eval/results.json
   git commit -m "improve chunking"
   git push
                                          5. 偵測到 push，自動觸發
                                          6. 跑 pytest tests/ -v
                                             → 讀 repo 裡的 results.json
                                             → 斷言四個數字有沒有過閾值
                                          7. PASSED → 綠燈 ✅
```

#### 為什麼 CI 不重跑 eval？

三個實際原因：

- **費用**：每次 push 都打 Claude API 會一直花錢，每天幾十次 push 很快燒完預算
- **速度**：真實 LLM eval 要幾分鐘，CI 要快（幾十秒），開發者等不起
- **穩定性**：LLM 回答有隨機性，同題目每次分數略有差異。如果 CI 每次重跑，無法分辨是「程式碼改壞了」還是「這次 LLM 輸出不穩定」

`results.json` commit 進 repo，代表**開發者為這份結果負責**——「我看過這個分數，我確認它夠好。」CI 只幫你確認「這份你 commit 的結果，有沒有達到最低標準」。

#### `python eval/run_eval.py` 的執行時機

> 每次你覺得改動**可能影響 RAG 品質**時，在 commit 之前手動跑一次。
> 不是每次 push 都跑，只有改了 retrieval 或 generation 相關的東西才需要。

---

## 二、概念確認 Q&A

**Q1：這個專案的 `tests/test_regression.py` 做了什麼事？它有真的呼叫 Claude API 嗎？**

沒有。它讀 `eval/results.json`（一個靜態 JSON 檔），
對裡面的四個數字（recall@3、mrr、faithfulness、answer_relevancy）做 `assert` 斷言，
確認每個指標都有達到設定的閾值。
整個測試 0.03 秒完成，沒有任何網路請求。

**Q2：如果 `eval/results.json` 不存在，測試會「失敗（FAILED）」還是「跳過（SKIPPED）」？為什麼這兩個結果不一樣？**

會是 SKIPPED。因為 `eval_results` fixture 在找不到 JSON 檔時呼叫 `pytest.skip()`，
而不是讓程式拋出例外。

差別在語義：FAILED 表示「你的程式壞了」，SKIPPED 表示「這個測試的前置條件不滿足、沒有執行」。
在 CI 裡，FAILED 會阻擋 PR merge，SKIPPED 不會。
新 clone 的環境沒有 results.json 是正常的，不應該阻擋任何人的工作。

**Q3：為什麼 CI 在執行 `pytest` 時不需要 `ANTHROPIC_API_KEY`？**

因為 regression tests 讀的是 repo 裡已存在的靜態 JSON，
不會呼叫任何 LLM 或外部服務。
API key 只在「產生 results.json」那一步（`python eval/run_eval.py`）才需要，
而那一步是開發者在本機手動跑的，不是 CI 的責任。

**Q4：既然 CI 讀的是已存在的 JSON，那 `python eval/run_eval.py` 是在什麼時候跑的？為什麼 CI 不跑它？**

`eval/run_eval.py` 是**開發者在本機手動跑的**，時機是：「我改了某個影響 RAG 品質的東西，想知道效果怎樣」。跑完確認分數夠好，才把 `results.json` 一起 commit 進去。

CI 不跑它的原因有三：費用（每次 push 都打 API 很貴）、速度（LLM eval 要幾分鐘，CI 要快）、穩定性（LLM 回答有隨機性，重跑分數會飄，無法判斷是程式碼壞了還是 LLM 輸出不穩定）。

**Q5：Regression test 是 unit test 的一部分嗎？這個 Phase 為什麼只介紹 regression test？**

不是。它們是平行的測試類型（unit test 測函式邏輯、regression test 測整體品質有沒有退步）。

Phase 1 只介紹 regression test，是因為 Phase 1 的定位是「**CI 的前提確認**」，不是從頭學測試。在設定 GitHub Actions 之前，你要先有一個「機器可以自動跑、能給出明確 pass/fail 結果」的測試套件。這個專案恰好有 regression test，所以 Phase 1 就是確認它能跑。Phase 1 是驗收地基，不是蓋房子。

---

## 三、實作過程

### 環境確認

專案使用 venv，pip 指令需要指定路徑：
```bash
# 直接用 venv 裡的 pytest，不需要另外安裝
venv/bin/pytest tests/ -v
```

遇到的問題：直接打 `pip` 或 `python3 -m pip` 在這個環境下需要等較久（安裝到 global），
直接用 `venv/bin/pytest` 是最快的方式。

### 確認 eval/results.json 不在 .gitignore

```bash
cat .gitignore
# 確認沒有 eval/ 或 results.json 的規則
```

結果：`.gitignore` 裡只有 `venv/`、`.env`、`chroma_db/`、`__pycache__/`，
`eval/results.json` 是被追蹤的，符合計劃要求。

---

## 四、驗收指令輸出

```
$ venv/bin/pytest tests/ -v

============================= test session starts ==============================
platform darwin -- Python 3.12.10, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/huangshimin/Desktop/rika/面試/sideproject
collected 4 items

tests/test_regression.py::test_retrieval_recall_at_3 PASSED              [ 25%]
tests/test_regression.py::test_retrieval_mrr PASSED                      [ 50%]
tests/test_regression.py::test_ragas_faithfulness PASSED                 [ 75%]
tests/test_regression.py::test_ragas_answer_relevancy PASSED             [100%]

============================== 4 passed in 0.03s ===============================
```

### 各測試的閾值與實際分數

| 測試 | 閾值 | 實際分數 | 結果 |
|------|------|---------|------|
| recall@3 | ≥ 0.70 | 0.9167 | PASSED ✅ |
| mrr | ≥ 0.60 | 0.8083 | PASSED ✅ |
| faithfulness | ≥ 0.70 | 0.8429 | PASSED ✅ |
| answer_relevancy | ≥ 0.50 | 0.5833 | PASSED ✅ |

> answer_relevancy 閾值設 0.50（而非 0.70）的原因：
> RAGAS 的 answer_relevancy 對繁體中文有系統性低分，
> 因為它用 LLM 生成英文問題再和中文問題比對相似度，baseline 約 58%，
> 閾值設 0.50 是為了偵測「退步」而非追求絕對分數。

---

## 面試說法

> 「我在 RAG 機器人專案加了 regression test，每次改完 chunking 或 embedding 設定，
> 只要跑 pytest 就能在 0.03 秒內確認四個品質指標（recall、MRR、faithfulness、answer_relevancy）
> 沒有退步。這個測試讀的是本機 eval 跑出來的 JSON，不呼叫 Claude API，
> 所以 CI 可以直接跑而不需要管理 API key，整個 workflow 乾淨很多。」
