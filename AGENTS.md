# AGENTS.md — agenticRAG-ClaudeAgentSDK

給接手這個子專案的 AI 看的。人類看 `README.md`。

## 這是什麼

Codex 公開課的教學專案：**教學生用 Codex Agent SDK 組合出各種 Agentic RAG 架構**
（CRAG / Self-RAG / Adaptive-RAG / HyDE / RAG-Fusion / Modular RAG）。

主張：這些架構不是各自獨立的系統，是同一組模組的不同編排。
模組 = `@tool`，編排 = system prompt，架構 = `modules.py` 的 `Architecture`。

主要教材是 `notebooks/`（四本），網頁 `app.py` 是現場 demo 用的殼 ——
兩者共用同一份 `modules.py`。

語料是 `corpus/`（內附的 Codex 參考文件，10 檔 / 41 片段）。
要換語料用 `index_corpus.py --root <資料夾>`，不用改程式碼。

## 不要破壞的三件事

**一、不要把檢索策略寫成 if/else。**
`modules.py` 只提供能力，選 bm25 還是 vector、要不要重查，全部由模型決定。
`grade_documents` 的評分也是模型自己打的，工具只負責把內文交回去。
把任何一段判斷邏輯搬進 Python，整個專案的教學主旨就沒了 —— 它會退化成 pipeline RAG。

**一之二、架構是資料不是程式碼。**
新增一個 RAG 架構 = 寫一份 `Architecture`（模組清單 + policy 字串），
**不要**為了某個架構去改 engine 或加 if 分支。這是整套教材的主張，破壞它等於破壞課程。

**二、不要打破 engine 邊界。**
`modules.py` 與 SSE 事件格式是契約，`engines/` 是可替換實作。
換 engine 不該動到 `modules.py` / `retrieval.py` / `static/index.html`。

**三、不要拿掉降級路徑。**
embedding 載不動時自動退回純 BM25，是現場教學的保命機制，不是防禦性程式碼。

## 慣例

- Python 一律 `uv`，禁止 pip
- 跑 ML 模型預設 MPS 不是 CUDA
- commit 用繁中、簡潔、不加 AI 署名

## 常見任務

**加一個新模組（工具）**：寫個 `xxx(ix, ...)` 函式，登記進 `modules.py` 的 `MODULES`。
兩個 engine、網頁、notebook 全部自動吃到。

**加一個新架構**：在 `modules.py` 建一個 `Architecture` 並登記進 `ARCHITECTURES`。
網頁選單與 notebook 會自動出現，不用改任何其他檔案。

**要用 SDK 內建工具**（WebSearch 等）：在 `Architecture.builtin_tools` 列出來，
並登記進 `modules.BUILTIN_TOOLS`（流程圖要用）。**`tools=arch.builtin_tools` 是白名單語意**——
沒列出來的內建工具全部關閉，所以預設 agent 碰不到 Bash / Write / Read。

⚠️ 任何會引入**知識庫以外**來源的工具，policy 都必須要求出處分開標
（知識庫 `[檔案.md#12]` vs 外部 `[web: 站名 - 網址]`），否則使用者分不出哪句可信。

**改 agent 行為**：改該架構的 `policy` 字串，不要改 engine 程式碼。

**換語料**：`index_corpus.py --root <你的資料夾>`，不用改程式碼。
只有要調整掃描規則（例如排除某些子目錄）才動 `INCLUDE_GLOBS` / `EXCLUDE_PARTS`。

**加一種向量庫**：實作 `query(qvec, k)` 與 `vectors_for(ids)` 兩個方法，
登記進 `retrieval.build_store()`。介面只有這兩個方法是刻意的 —— RAG 對向量庫的需求就這麼點。
加完務必讓 `test_chroma_store_agrees_with_numpy_store` 那組測試也涵蓋它：**換 store 不該換答案**。

**驗證還能跑**：`uv run pytest`（70 項，不花額度）。
notebook 有專屬那一組（`tests/test_notebooks.py`）：擋家目錄外洩、擋 base64 夾帶圖、
擋沒跑過就送出的 notebook —— 編輯器把舊副本蓋回去時，靠它紅給你看。
`tests/test_architectures.py` 專門盯架構層 —— 它存在的理由是：改壞 `modules.py`
（例如語法錯誤、policy 引用了不存在的模組）不會被檢索層的測試抓到。加新架構務必讓它跑過。

**PDF 語料**：`.pdf` 依頁切塊，`Chunk.page` 帶頁碼，網頁點引用會開內嵌閱讀器跳到那一頁。
論文本身不進 repo，用 `scripts/fetch_papers.sh` 抓。

## 已知取捨

- 預設不用向量資料庫：在一份 6601 片段的語料上量過，numpy 0.089 ms vs chroma 0.399 ms，
  這個規模 chroma 反而慢 4.5 倍。`VECTOR_STORE=chroma` 可切過去（教學用），
  但不要改預設值 —— 那張效能對照表本身就是教材
- 內附的 `corpus/` 只有 41 片段，刻意保持小：clone 下來就能跑、repo 不會肥。
  要展示規模效應請用 `--root` 指向大一點的資料夾
- 不做對話歷史：每次提問獨立，多輪會讓軌跡面板難教
- litellm engine 的軌跡較簡略：拿不到結構化 thinking，靠 prompt 要求模型寫理由補

## 後來長出來的東西（改之前先看一眼）

| 檔案 | 做什麼 | 動它要注意 |
|---|---|---|
| `architect.py` | 聊出架構 / 幫忙寫 policy / 把 policy 反推成圖 | 三個 system prompt 都要求「只能用登記過的模組」，別放寬 |
| `providers.py` | 換 LLM 供應商（記憶體，不寫 .env） | `env_overlay()` 一定要把沒用到的變數清成空字串 |
| `mcp_registry.py` | 接外部 MCP server | 連不上就不准存；headers/env 回前端前要遮 |
| `graph_store.py` | Neo4j（選用） | 給 agent 的 Cypher 有唯讀護欄，不要為了方便拿掉 |
| `inspect_store.py` | 向量庫體檢 + 2D 投影 | 投影一定要回報解釋變異量，那是防止誤解的唯一手段 |
| `traces.py` | 軌跡錄影與重播 | 重播餵回原本的 `handle()`，不要寫第二套渲染 |

## 三條界線

1. **沒接的資料源不能讓系統掛掉。** 沒設 `NEO4J_URI` 就當作沒有那一格，其他照常跑。
2. **語意色不要換。** 琥珀=正在動作、綠=完成、紅=折返、藍=SDK 內建 —— 那是教學訊號。
3. **前端不要引入外部資源。** 教室可能沒網路，CDN 抓不到就破版。圖示走 `static/icons.svg`。
