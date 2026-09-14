# 用 Claude Agent SDK 組合 Agentic RAG 架構

教學專案。核心主張一句話：

> **CRAG、Self-RAG、Adaptive-RAG、HyDE、RAG-Fusion 不是五個系統，是同一組模組的五種編排。**
> 在 Claude Agent SDK 裡，換架構不是改程式碼，是換一份 `Architecture`。

**背後的 LLM 預設走 Claude 訂閱的 OAuth —— 不需要 API key、不產生 API 帳單。**
不想用 Claude 也行：換一行 `.env` 就能接 OpenAI / Gemini / DeepSeek / 本地 Ollama。

---

## 60 秒跑起來

```bash
git clone https://github.com/kevin801221/agenticRAG-ClaudeAgentSDK.git
cd agenticRAG-ClaudeAgentSDK
cp .env.example .env

uv sync --extra embeddings              # 裝相依（含本地 embedding 套件）
uv run python index_corpus.py           # 建索引（第一次會下載約 100MB 的 e5-small）

uv run jupyter lab notebooks/           # 教學主體
uv run uvicorn app:app --reload         # 或看網頁 demo：http://localhost:8000
```

教室沒網路 / 不想下載模型：`uv run python index_corpus.py --no-vectors`（純 BM25，秒建，功能完整）。

### 認證：本機 `claude` 已登入的話，什麼都不用設

Agent SDK 底層 spawn 的是 Claude Code CLI —— **CLI 讀什麼憑證，它就用什麼**。

| 接法 | 怎麼設 | 費用 |
|---|---|---|
| 本機已登入 Claude Code | 什麼都不用設 | 訂閱額度 |
| **OAuth token（推薦）** | `claude setup-token` → `CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat...` | 訂閱額度，**無 API 帳單** |
| Anthropic 相容端點 | `ANTHROPIC_BASE_URL` + `ANTHROPIC_AUTH_TOKEN` + `ANTHROPIC_MODEL` | 該 provider 計費 |
| Anthropic 官方 API | `ANTHROPIC_API_KEY` | 官方計費 |

第三種可接 DeepSeek、Kimi、GLM、OpenRouter，或自架 LiteLLM proxy 再轉往任何模型。
**四種情況下程式碼完全相同**，只有環境變數不同。

---

## 三本 Notebook（都已執行過，打開就看得到結果）

| Notebook | 內容 | 時長 | 花額度嗎 |
|---|---|---|---|
| `01_agent_sdk_basics.ipynb` | Agent SDK 入門：認證、`query()`、`@tool`、hooks 看見 agent 在想什麼 | 40 分 | 少量 |
| `02_compose_architectures.ipynb` | ⭐ 實跑 Naive / RAG-Fusion / HyDE / CRAG / Self-RAG / Adaptive，最後自己組一個 | 80 分 | 會 |
| `03_retrieval_internals.ipynb` | 檢索層內部：中文斷詞、三種查法對比、RRF 手算、MMR、要不要裝向量資料庫 | 30 分 | **零 LLM 呼叫** |

---

## 核心概念

```
       模組（能力）= @tool                    編排（政策）= system prompt
  ┌───────────────────────────┐        ┌──────────────────────────┐
  │ Indexing                  │        │ Linear      固定順序跑完   │
  │   list_corpus             │        │ Conditional 依判斷走分支   │
  │ Pre-retrieval             │   ×    │ Branching   展開多路再合併 │
  │   multi_search hyde_search│        │ Looping     生成→批判→重來 │
  │ Retrieval                 │        └──────────────────────────┘
  │   search  WebSearch(SDK)  │
  │ Post-retrieval            │                   ‖
  │   grade_documents         │                   ▼
  │   expand  diversify       │           Architecture（一個具名架構）
  └───────────────────────────┘
```

| Modular RAG 概念 | Claude Agent SDK 裡是什麼 |
|---|---|
| 模組 module | 一個 `@tool` |
| 編排 orchestration | `system_prompt` 裡的流程規則 |
| 架構 architecture | 模組清單 + 編排規則 → `modules.py` 的 `Architecture` |

### 七個現成架構

| 架構 | 編排 | 關鍵模組 | 出處 |
|---|---|---|---|
| Naive RAG | Linear | search | Lewis et al. 2020 |
| RAG-Fusion | Branching | multi_search | Query Expansion 系列 |
| HyDE | Linear（前置轉換） | hyde_search | Gao et al. 2022 |
| CRAG | Conditional（三分支 + web） | grade_documents + WebSearch | Yan et al. 2024 |
| Self-RAG | Looping | grade + 反思政策 | Asai et al. 2024 |
| Adaptive-RAG | Conditional（複雜度路由） | 分類 → 三條路 | Jeong et al. 2024 |
| Modular RAG | 自適應 | 全部 | Gao et al. 2024 |

**新增一個架構不用寫程式碼**，寫一份 `Architecture` 就好：

```python
MY_ARCH = M.Architecture(
    name="Rewrite-Retrieve-Read",
    paper="Ma et al. 2023",
    orchestration="Linear（Pre-retrieval 改寫）",
    modules=["search"],
    policy="先把問題改寫成文件作者會用的說法，再檢索，然後作答。不要評估、不要重試。",
)
run = await M.arun(MY_ARCH, "那個會擋東西的功能怎麼設？", ix)
```

---

## 網頁 demo：會跟著跑的流程圖

```bash
uv run uvicorn app:app --reload
```

最上方是流程圖，七個模組依 Modular RAG 階段排成五欄：

| 視覺 | 意思 |
|---|---|
| 琥珀行進虛線框 + 光暈 | 這個模組**正在執行** |
| 綠框 + 右上角數字 | 跑過了，數字是**執行次數** |
| 整欄底色亮起 | 現在在哪個階段 |
| 弧線 + 飛行光點 | 資料流從上一個模組走到下一個 |
| **從圖底掃過的紅色弧線 +「折返」** | **退回前一個階段 —— CRAG 自我修正的那一刻** |
| 灰掉的虛線框 | 這個架構**沒有**給它這個模組 |
| 藍框 + `SDK` 標記 | SDK 內建工具（WebSearch），不是這個專案寫的 |

**這張圖先教架構，才演過程。** 選單切到 Naive RAG → 整個 Post-retrieval 欄暗掉，
學生一眼看出它為什麼不可能自我修正。

---

## 換成你自己的知識庫

`corpus/` 裡是一份自給自足的 Claude Code 參考文件（10 個 `.md` / 41 個片段），
讓你 clone 下來就能跑。要換成自己的：

```bash
uv run python index_corpus.py --root ~/我的文件資料夾
```

只要裡面是 `.md` 就行。切塊是按 markdown heading 切的，
所以文件的標題結構越清楚，檢索品質越好。

---

## 檔案

```
modules.py        ⭐ 模組庫 + Architecture + 七個現成架構 + arun()
retrieval.py         BM25(jieba) + 向量(e5-small/MPS) + RRF + 可插拔向量 store
index_corpus.py      切塊建索引（按 markdown heading 切，保留前後鄰居）
corpus/              範例語料：Claude Code 參考文件
notebooks/           三本教學 notebook
engines/
  agent_sdk.py       Claude Agent SDK（預設）
  litellm_loop.py    自寫的 tool loop，對照組
app.py               FastAPI + SSE
static/index.html    單檔前端，無建置
tests/               檢索層測試（16 項）
```

`app.py` 和 notebook 用的是**同一份** `modules.py` —— 網頁就是 notebook 02 的其中一格加了畫面。

## 向量儲存層也可插拔

```bash
VECTOR_STORE=numpy    # 預設：向量放記憶體，暴力算 cosine
VECTOR_STORE=chroma   # 交給 Chroma 管（uv sync --extra chroma）
```

切換不用重建索引 —— `vectors.npy` 永遠是原始資料，chroma 第一次啟動會自己從它灌進去。

我在一份 6601 片段的語料上量過（同一台 Mac、同一個查詢）：

| store | 純檢索 | 含 query embedding | 磁碟 |
|---|---|---|---|
| numpy | **0.089 ms** | 5.23 ms | 9.7 MB |
| chroma | 0.399 ms | 5.02 ms | 16 MB |

**這個規模下 chroma 反而慢 4.5 倍**（HNSW 的索引開銷還賺不回來），
而且不管用哪個，**95% 的時間都花在把問題轉成向量**，不是檢索。
兩者答案完全一致，有一條測試專門盯這件事。

> 十萬筆以上、需要增量更新、或需要 metadata 過濾，才真的需要向量資料庫。
> 在那之前它只是多一個要跑、要維護的服務。**先量再裝。**

## 測試

```bash
uv run pytest                                   # 檢索層 16 項，不花 LLM 額度
```

## 降級行為

embedding 載不動、沒網路、MPS 出問題 —— 自動退回純 BM25 並在畫面標明降級，功能完整。
**一堂課不能因為一個模型下載失敗就上不下去。**

⚠️ HyDE 與 MMR 在降級模式下效果會打折，因為它們本質上需要向量。

---

## 參考文獻

- Modular RAG — Gao et al. 2024, [arXiv:2407.21059](https://arxiv.org/abs/2407.21059)
- CRAG — Yan et al. 2024, [arXiv:2401.15884](https://arxiv.org/abs/2401.15884)
- Self-RAG — Asai et al. 2024, ICLR
- Adaptive-RAG — Jeong et al. 2024, NAACL
- HyDE — Gao et al. 2022, [arXiv:2212.10496](https://arxiv.org/abs/2212.10496)
- [Claude Agent SDK 官方文件](https://code.claude.com/docs/en/agent-sdk)

---

## 授權

MIT — 隨意使用、修改、再散布，教學或商用都可以，保留著作權聲明即可。
