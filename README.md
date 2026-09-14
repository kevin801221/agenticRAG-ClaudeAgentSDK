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

### 十二個現成架構

| 架構 | 編排 | 一句話 | 出處 |
|---|---|---|---|
| Naive RAG | Linear | 查一次就答，基準線 | Lewis et al. 2020 |
| **Rewrite-Retrieve-Read** | Linear | 只在檢索**前**改寫 query | Ma et al. 2023 |
| HyDE | Linear | 拿「猜的答案」而非問題去比對 | Gao et al. 2022 |
| RAG-Fusion | Branching | 多個 query 平行查再 RRF 融合 | Query Expansion 系列 |
| **Self-Ask** | Linear | 顯式寫出後續子問題，一個一個查 | Press et al. 2022 |
| **IRCoT** | Looping | 推理**每一句**都帶動下一次檢索 | Trivedi et al. 2023 |
| CRAG | Conditional | 評分後三分支：精煉 / 改用網路 / 兩者合併 | Yan et al. 2024 |
| Self-RAG | Looping | 每輪自問四個反思問題 | Asai et al. 2024 |
| **FLARE** | Looping | 先寫草稿，沒把握的句子才去查 | Jiang et al. 2023 |
| **Search-o1** | Looping | 推理卡住才查，且先精煉再注入 | Li et al. 2025 |
| Adaptive-RAG | Conditional | 先判斷複雜度再決定花多少力氣 | Jeong et al. 2024 |
| Modular RAG | 自適應 | 全部模組給 agent 自己編排 | Gao et al. 2024 |
| **論文重點 Slide** | Linear | 讀 PDF → 產出可直接貼投影片的重點 | 實用案例，非論文方法 |

**粗體的五個是純政策架構** —— 加它們的時候一行程式碼都沒寫，只是各多了一份 `Architecture`。
這是 Modular RAG 主張最直接的證據：五篇論文，零行新程式碼。

### 什麼**沒有**收進來，為什麼

有些方法動的不是編排，而是**索引期**，那不是換一份 policy 就能做到的：

| 方法 | 它動的是什麼 | 為什麼沒收 |
|---|---|---|
| RAPTOR | 索引時遞迴分群 + 摘要，建成一棵樹 | 要重寫 `index_corpus.py`，而且建索引得呼叫 LLM |
| GraphRAG / LightRAG / HippoRAG | 索引時抽實體關係建圖 | 同上，還要一個圖資料庫 |
| Contextual Retrieval | 索引時為每個片段生成前後脈絡再嵌入 | 索引期需要 LLM，破壞「clone 下來 60 秒跑起來」 |
| Search-E1 / R²-Searcher / IG-Search | 用 RL 訓練檢索策略 | 需要訓練，不是 prompt 能複製的 |

**這件事本身就是一課**：Modular RAG 的模組不只在檢索期，也在索引期。
prompt 換得動編排，換不動索引。

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

最上方是流程圖。**預設收合成一行**（它很佔位置），行為是：

| 時機 | 行為 |
|---|---|
| 送出問題 | 自動展開 |
| 執行中 | 標題列即時顯示「第 N 步：模組名」，收著也看得到進度 |
| 跑完 | 1.8 秒後自動收回，標題列留下「完成 N 次呼叫 · X 秒」 |
| 點標題列 | 手動開關。**手動打開就會釘住**，跑完不會自動收掉 |

展開後，七個模組依 Modular RAG 階段排成五欄：

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

## 把論文 PDF 讀進來

`.pdf` 和 `.md` 一樣會被索引 —— 但切塊策略不同：PDF 沒有可靠的 heading 結構，
所以改用**頁**當邊界，而且**頁碼會留在片段裡**。

```bash
uv sync --extra pdf                    # 裝 pymupdf
bash scripts/fetch_papers.sh           # 從 arXiv 抓這套教材引用的 12 篇論文
uv run python index_corpus.py          # 重建索引
```

論文 PDF **不在 repo 裡**（別人的著作，各自有授權，這個 repo 不該替他們重新散布），
所以用腳本抓，抓下來的檔案已經在 `.gitignore`。

### 文件檢視器：可圈選、可問、可錨定

打開任何一份語料，版面會切換成閱讀模式：

| 位置 | 變成什麼 |
|---|---|
| 左欄 | 文件本身。PDF 是逐頁顯示，有 `‹ 4/16 ›` 翻頁 |
| 右欄 | **「問這份文件」** —— 一個只談這份文件的 agent（`doc_chat` 架構，`search` 一律帶 `path`） |
| 中間 | **可拖曳的分隔線**，字太小就把左邊拉寬（會記住你的設定） |

**AI Anchor**：在頁面上**拖出一個方框**（八個控制點可以縮放、整塊可以拖動），
框裡的文字就錨定到右邊，還附一張**框到什麼的縮圖**讓你確認。接著直接問 ——
agent 拿到的是「你框的內容 + 你的問題」。

用方框而不是文字選取，是因為論文常常要框的是**一張圖加它的說明**，
那本來就是一塊區域；而且 PDF 的文字層是一堆小方塊，跨欄跨圖時文字選取會亂跑。
框到純圖沒有文字時，agent 會明講「這一區讀不到文字」並主動去找附近的圖說。

回答格式是**訂死的**（一句話 / 說明 / 注意），一點一個概念、一個出處放句尾 ——
邊讀邊問要的是短而準，不是一長串把出處堆在一起的段落。

回答裡的出處是可點的，**點下去左邊直接翻到那一頁**。

> **技術細節值得講**：Chrome 內建的 PDF 檢視器是獨立的外掛程序，
> 外面的網頁碰不到它的文字選取，所以「在 PDF 上圈選」用 `<iframe src=".pdf">` 做不到。
> 這裡的作法是**伺服器把頁面算成 PNG（pymupdf，約 36 ms/頁），再用逐字座標疊一層透明文字**。
> 你看到的是真正的版面，圈選卻是原生的網頁選取 —— 而且完全離線，不需要 pdf.js。

### 兩個入口可以看到論文

**一、直接翻**：頁面最下面的「語料庫」展開，列出所有語料，
點 PDF 就在頁面上開閱讀器（也有「在新分頁開啟」）。不用先問問題。

**二、從答案的引用跳過去**：答案裡的出處是可點的，會直接跳到論文的那一頁：

```
[papers/crag.pdf#13]  ← 點下去 → 內嵌閱讀器跳到第 4 頁
```

這件事對讀論文很重要：抽出來的純文字看不到圖表，但論文的關鍵常常就在圖裡。
面板同時保留「抽出來的純文字」摺疊區 —— 那才是檢索實際比對的內容，兩者對照著看。

### 案例：論文重點 Slide

選 `論文重點 Slide` 這個架構，丟一句「把 crag 這篇論文整理成投影片重點」，它會：

1. `list_corpus` 確認有哪幾篇 → 2. 檢索摘要與結論抓骨架 →
3. 分別檢索「方法 / 數字 / 限制」並用 `grade_documents` **讀完整內文**（不只看摘要）→
4. 輸出固定格式：一句話 / 要解決的問題 / 方法步驟 / 關鍵數字表 / **限制與代價** / 一句可以講給學生聽的話

每個 bullet 都標頁碼，聽眾可以翻回原文對照。

> **它抓到過我的錯。** 我在教材裡把 CRAG 的 Ambiguous 分支寫成「改寫 query 再查一輪」，
> 跑這個架構讀原文時它主動指出：那與論文不符，Ambiguous 是「內部精煉知識 ＋ 網路結果兩者合併」。
> 查證後確實是我錯了，已修正。這就是「強制標出處」的價值 —— 錯誤會被原文抓出來。

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
corpus/              範例語料：Claude Code 參考文件（.md）+ papers/（.pdf，用腳本抓）
scripts/             fetch_papers.sh —— 從 arXiv 抓論文
notebooks/           三本教學 notebook
engines/
  agent_sdk.py       Claude Agent SDK（預設）
  litellm_loop.py    自寫的 tool loop，對照組
app.py               FastAPI + SSE
static/index.html    單檔前端，無建置
tests/               測試（27 項：檢索層 + 架構層）
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
uv run pytest                                   # 27 項（檢索層 + 架構層），不花 LLM 額度
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
