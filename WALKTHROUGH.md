# Agentic RAG Walkthrough — 從 Claude Agent SDK 到十四個 RAG 架構

> **對象**：知道 RAG 在做什麼，但被 CRAG / Self-RAG / Adaptive-RAG 一堆論文名字嚇到的人
> **形式**：自學。跟著做，每一步都會跑出東西
> **時長**：核心 3 小時（Step 0–5）＋ 延伸 2 小時（Step 6–9）
> **產出**：一套跑得動的系統、十四個現成架構、以及「自己組第十五個」的能力
> **核心方法**：不逐篇講論文。先把 RAG 拆成七個模組，然後讓你看到**同一組模組換個編排就是另一篇論文**
>
> 這份是**跟著做**的路線圖。要現場帶課的講稿在 `docs/walkthroughs/agentic_rag_walkthrough.md`（母 repo）。

---

## 開場（5 分鐘）：先打掉一個迷思

大部分人以為 CRAG、Self-RAG、Adaptive-RAG 是三套不同的系統，要各學一次。

不是。它們用的是**同一組能力**，差別只在「什麼時候用哪一個」。

| | 是什麼 | 在這個專案裡長什麼樣 |
|---|---|---|
| 模組 module | 一個能力 | 一個 `@tool` 函式 |
| 編排 orchestration | 什麼時候用哪個能力 | `system_prompt` 裡的一段文字 |
| 架構 architecture | 模組清單 ＋ 編排 | `modules.py` 裡的一個 `Architecture` |

> **教學金句**：「你不是要學五種 RAG，你是要學一種積木 —— 然後知道那五篇論文各自是怎麼拼的。」

所以**新增一個架構 = 寫一份資料，不是寫程式**。這句話是整份文件的主線，
後面每一步都在證明它。

---

## 📁 你會碰到的檔案

```
agentic-rag-workshop/
├── modules.py        ⭐ 七個模組 + Architecture + 十四個架構     ← 全場主角
├── retrieval.py         BM25(jieba) + 向量 + RRF + MMR（純函式，零 LLM）
├── index_corpus.py      切塊建索引（.md 按 heading、.pdf 按頁）
├── ingest.py            上傳文件 → agent 決定怎麼切（Step 7）
├── architect.py         聊出一份架構 / 幫你寫 policy / policy 反推成圖
├── providers.py         換 LLM 供應商（Step 9）
├── mcp_registry.py      接別人的 MCP server（Step 9）
├── traces.py            軌跡錄影與重播（Step 8）
├── notebooks/           四本，主教材
├── app.py + static/     網頁：流程圖、文件工作台、/studio 畫布
└── tests/               45 項，不花 LLM 額度
```

**notebook 是主教材，網頁是看得見的版本。** 兩邊共用同一份 `modules.py` ——
網頁其實就是 notebook 02 的其中一格加了畫面。

---

## Step 0 ⚙️：跑起來（15 分鐘）

```bash
git clone https://github.com/kevin801221/agenticRAG-ClaudeAgentSDK.git
cd agenticRAG-ClaudeAgentSDK
cp .env.example .env

uv sync --all-extras                     # 含 embedding、chroma、PDF
uv run python index_corpus.py            # 第一次會下載約 100MB 的 e5-small

./scripts/setup_kernel.sh                # 註冊 Jupyter kernel（要跑 notebook 就一定要這步）
```

**沒網路或不想等**：`uv run python index_corpus.py --no-vectors`
（純 BM25，秒建，功能完整，只是 HyDE 那類向量檢索會降級）。

### ⚠️ 跑 notebook 之前：kernel 一定要選對

這是全場第一名的卡點，而且錯誤訊息完全不會提到 kernel。

**notebook 能不能 `import modules`，跟你「開哪個資料夾」無關，
只跟「kernel 用的是哪一支 python」有關。**

**兩個編輯器的選單長得不一樣，別找錯東西：**

| | 選單上會顯示 | 選哪個 |
|---|---|---|
| **VS Code** | 依**路徑**列出它找到的環境 | `Python .venv/bin/python`（寫著 `.venv` 的那個就對了） |
| **Jupyter Lab** | 依**名字**列出註冊過的 kernel | `agentic-rag (.venv, Python 3.13)` |

VS Code **不會**顯示 `agentic-rag` 這個名字 —— 它有自己的環境探索，
直接把 `.venv` 當成一個叫 `Python` 的選項列出來。**看到 `.venv/bin/python` 就是對的**，
不用去找那個名字。（`scripts/setup_kernel.sh` 註冊的名字是給 Jupyter Lab 用的。）

怎麼確認真的對了：跑第一格，它會印出 `sys.executable`。
只要結尾是 `agentic-rag-workshop/.venv/bin/python`，就沒事了。

| 症狀 | 原因 | 處理 |
|---|---|---|
| `ModuleNotFoundError: modules` | kernel 是別的 python | 看 `sys.executable` 是不是專案的 `.venv` |
| VS Code 選單裡找不到 `agentic-rag` | **正常**，VS Code 只認路徑不認名字 | 選 `.venv/bin/python` 那個就對了 |
| Jupyter Lab 說找不到 kernel | 還沒跑 `setup_kernel.sh` | 跑它 |
| VS Code 自己建了 `notebooks/.venv` | 它自作聰明 | **刪掉那個資料夾**，再重選 |
| 選單裡一堆長得很像的 Python | 認路徑不要認名字 | 要 `<專案>/.venv/bin/python` |

```bash
uv run jupyter kernelspec list     # 確認它指到專案的 .venv
```

⚠️ 這台機器上如果有**兩份**這個專案（例如舊的內部版），
確認你開的是 clone 下來的那一份 —— 兩份各有自己的 `.venv`，開錯就全錯。

### 認證：本機 `claude` 登入過的話，`.env` 可以完全空白

Agent SDK 底層 spawn 的是 Claude Code CLI ——
**CLI 讀什麼憑證，你的 agent 就讀什麼憑證**。

| 接法 | 怎麼設 | 費用 |
|---|---|---|
| 本機已登入 Claude Code | 什麼都不用設 | 訂閱額度 |
| **OAuth token（推薦）** | `claude setup-token` → `CLAUDE_CODE_OAUTH_TOKEN=` | 訂閱額度，**無 API 帳單** |
| Anthropic 相容端點 | `ANTHROPIC_BASE_URL` + `ANTHROPIC_AUTH_TOKEN` + `ANTHROPIC_MODEL` | 該 provider 計費 |
| Anthropic 官方 API | `ANTHROPIC_API_KEY` | 官方計費 |

> **教學金句**：「四種接法的**程式碼一個字都不一樣**，差別只在環境變數。
> 這件事會在 Step 9 再被用一次。」

### 先跑一題確認活著

```bash
uv run uvicorn app:app --reload      # http://localhost:8000
```

問「hook 要怎麼擋住寫入 .env？」，上面的流程圖會一格一格亮。**先看到它會動，再回頭看它為什麼會動。**

---

## Step 1 🧠：Agent SDK 只有四樣東西（40 分鐘）

📓 `notebooks/01_agent_sdk_basics.ipynb`

先分清楚三個常被搞混的東西：

| | 誰跑 agent loop | 能用什麼工具 |
|---|---|---|
| **Claude API**（`anthropic`） | **你自己寫 while 迴圈** | 你定義的 |
| **Tool Runner**（`client.beta.messages.tool_runner`） | SDK | 你定義的 |
| **Claude Agent SDK**（`claude-agent-sdk`） ← 這本用的 | SDK | 內建 Read/Write/Bash/WebSearch ＋ 你的 MCP 工具 |

整份專案只用到四樣東西：

```python
# ① query() —— 問一句，串流拿回來
async for msg in query(prompt="...", options=ClaudeAgentOptions(tools=[], max_turns=1)):
    ...

# ② @tool —— 把 Python 函式變成模型看得懂的能力
@tool("roll_dice", "擲一顆骰子。sides 是面數，預設 6。",
      {"type": "object", "properties": {"sides": {"type": "integer"}}, "required": []})
async def roll_dice(args): ...

# ③ ClaudeAgentOptions —— 這次准他用什麼、行為規則是什麼
ClaudeAgentOptions(
    tools=[],                                  # 內建工具全關
    mcp_servers={"demo": dice_server},         # 掛自己的工具
    allowed_tools=["mcp__demo__roll_dice"],    # 白名單，免人工確認
    system_prompt="...",                       # ← 編排寫在這裡
)

# ④ hooks —— 打開黑盒子，看見它每一步在做什麼
HookMatcher(hooks=[on_pre_tool])
```

### 兩個一定要知道的坑

| 坑 | 真相 |
|---|---|
| `tools=[]` 以為是「不給工具」 | 它只關**內建**工具（Read/Write/Bash…）。你自己的 MCP 工具走 `mcp_servers`，兩者獨立 |
| 以為 `allowed_tools` 是權限控制 | 它是**自動放行名單**，不是防火牆。真正的門是 `tools` 和 `mcp_servers` |

> **教學金句**：「`tools=[]` 加 `setting_sources=[]` 才是乾淨沙盒。
> 少了第二個，它會把你專案的 CLAUDE.md 和 hooks 一起吃進去。」

**做完這步你應該能**：寫一個有自訂工具、而且印得出完整調用軌跡的 agent。

---

## Step 2 🛠：把 RAG 拆成七個模組（20 分鐘）

打開 `modules.py`。七個模組，依 Modular RAG 的階段分類：

| 階段 | 模組 | 做什麼 |
|---|---|---|
| Indexing | `list_corpus` | 列出知識庫有哪些檔案、各有幾個片段 |
| Pre-retrieval | `multi_search` | RAG-Fusion：一次送多個角度的 query，結果用 RRF 融合 |
| Pre-retrieval | `hyde_search` | HyDE：先寫一段假設答案，拿它去做向量檢索 |
| Retrieval | `search` | 基本檢索。`method` 由**模型自己選** bm25 / vector / hybrid |
| Post-retrieval | `grade_documents` | 取回片段的**完整內文**，讓模型自己評估夠不夠 |
| Post-retrieval | `expand` | 取某片段在原文中的前後鄰居 |
| Post-retrieval | `diversify` | MMR 去重：挑出「相關且彼此不重複」的子集 |

加上 SDK 內建的 `WebSearch`（知識庫查不到時上網找）。

### 這一步最重要的一件事：工具只回資料，不下指令

看 `grade_documents` —— 它叫「評分文件」，但**它自己不打分**。
它只是把完整內文取回來交給模型。

```python
# ✅ 工具回傳的長這樣
{"chunks": [{"id": "01-hooks.md#3", "text": "……完整內文……"}]}

# ❌ 絕對不要變成這樣
{"chunks": [...], "next_step": "如果多數低於 1 分就改寫 query 重查"}
```

第二種寫法我踩過。agent 跑完直接在軌跡上說：
「工具回傳的內容尾端夾帶了一段指示文字…我沒有照它執行。」

> **教學金句**：「**工具給能力，policy 給政策。** 判斷邏輯一旦搬進 Python，
> 整個專案就退化成寫死的 pipeline，agentic 三個字就沒了。」

---

## Step 3 📝：架構 = 模組清單 + policy（20 分鐘）

```python
@dataclass
class Architecture:
    name: str
    paper: str                 # 出處
    orchestration: str         # Linear / Conditional / Branching / Looping
    modules: list[str]         # 給它哪些能力
    policy: str                # ← 差別全在這裡
    builtin_tools: list[str] = field(default_factory=list)
    mcp_tools: list[str] = field(default_factory=list)
    max_turns: int = 12
```

`build_options()` 把它翻成 `ClaudeAgentOptions`。**整個專案只有這一個函式碰 SDK。**

### 現場做一次這件事，主線就立住了

把 Naive RAG 和 CRAG 的欄位並排印出來：

```python
import modules as M
for k in ("naive", "crag"):
    a = M.ARCHITECTURES[k]
    print(a.name, "|", a.orchestration, "|", a.modules)
```

```
Naive RAG            | Linear      | ['search']
CRAG（Corrective RAG）| Conditional | ['search', 'grade_documents', 'expand'] + WebSearch
```

**Naive RAG 連「評估檢索品質」的能力都沒有 —— 所以它結構上不可能自我修正。**
不是它笨，是你沒給它那隻手。

> **教學金句**：「換架構不改程式碼。你改的是一份資料 ——
> 一個清單加一段字串。」

---

## Step 4 🔍：一個一個把論文組出來 ⭐ 最重要的一步（80 分鐘）

📓 `notebooks/02_compose_architectures.ipynb`

十四個架構，全部只差在那三個欄位：

| 架構 | 論文 | 編排 | 模組 | 關鍵那一句 policy |
|---|---|---|---|---|
| **Naive RAG** | Lewis 2020 | Linear | `search` | 「不要重試、不要改寫 query、不要評估品質 —— 就查一次。」 |
| **Rewrite-Retrieve-Read** | Ma 2023 | Linear | `search` | 檢索**前**先把口語問題改寫成文件用語，只改一次 |
| **HyDE** | Gao 2022 | Linear | `hyde_search` `search` | 「先寫一段假答案 —— 內容錯沒關係，我們要的是**句式和用詞**跟真文件對得上」 |
| **RAG-Fusion** | Rackauckas 2024 | Branching | `multi_search` | 3–5 個**真的不一樣**的問法，RRF 把同時上榜的推到前面 |
| **Self-Ask** | Press 2022 | Linear | `search` | 明確寫出「後續問題是什麼」，一個一個查 |
| **IRCoT** | Trivedi 2023 | Looping | `search` `expand` | 想一步查一步，**交錯**進行 |
| **CRAG** | Yan 2024 | Conditional | `search` `grade_documents` `expand` `WebSearch` | 三分支：Correct 精煉／Incorrect **丟掉**改上網／Ambiguous 兩邊都用 |
| **Self-RAG** | Asai 2024 | Looping | 加 `diversify` | 每輪回答四個反思問題：要不要檢索／相關嗎／有出處撐嗎／答到了嗎 |
| **FLARE** | Jiang 2023 | Looping | `search` `grade_documents` | 先寫草稿，**只有沒把握的句子**才去查 |
| **Search-o1** | Li 2025 | Looping | 加 `WebSearch` | 推理到卡住的那一刻才檢索，檢索完先精煉再回到推理 |
| **Adaptive-RAG** | Jeong 2024 | Conditional | 五個模組 | 先分類 A/B/C 複雜度，再決定花多少力氣 |
| **Modular RAG** | Gao 2024 | Adaptive | 全部八個 | 沒有固定流程，由模型自己組 |
| `paper_slides` | — 實用案例 | Linear | 四個 | 把 PDF 讀成可直接上投影片的重點 |
| `doc_chat` | — 實用案例 | Conditional | 三個 | 使用者面前開著一份文件，就只談這份 |

### 怎麼跑

```python
run = await M.arun(M.ARCHITECTURES["crag"], "那個會擋東西的功能怎麼設？", ix)
print(run.n_calls, "次呼叫", run.elapsed_s, "秒")
```

### 建議的順序與看點

1. **Naive** 先跑，當基準線。記住它的呼叫次數和耗時。
2. **HyDE** —— 這個最容易「看到差別」。故意用口語問題（「那個會擋東西的功能」），
   Naive 會撈不到，HyDE 因為先寫了一段用術語的假答案就撈得到。
   **沒建向量索引的話 HyDE 會很爛** —— 那也值得看一次，它會退回 BM25。
3. **CRAG** —— 看它評分完走哪一支。問一題知識庫沒有的（例如「2026 年溫布頓男單冠軍是誰？」），
   它會走 Incorrect 分支去 `WebSearch`。
4. **Self-RAG** —— 會跑 60–90 秒。**那個慢就是教材**：自我反思是有代價的。
5. **Adaptive** —— 同一個架構問簡單題和複雜題，看它自己選了 A / B / C 哪一類。

> **教學金句**：「CRAG 的 Ambiguous 是**兩邊都用**，不是『改寫重查』。
> 這個我一開始寫錯，是我自己的系統讀論文 PDF 時抓出來的。」

**做完這步你應該能**：看著任何一篇 RAG 論文的流程圖，說出它要哪些模組、policy 怎麼寫。

---

## Step 5 ✅：驗證 —— 沒有量過就不算改進（20 分鐘）

網頁上勾「並排比較」，同一題同時跑兩三個架構。實際跑出來的一張表：

| 架構 | 模組呼叫 | 耗時 | 出處 | 答案長度 |
|---|---|---|---|---|
| Naive RAG | 1 | 28.9 s | 8 | 1985 字 |
| 多路查＋評分（自己組的） | 3 | 56.3 s | **0** | 2388 字 |
| 白話對齊檢索（agent 組的） | 3 | 59.3 s | 5 | 2000 字 |

**這一題 Naive RAG 贏。** 一次查完、快一倍、出處最多。

中間那個「出處 0」不是它在憑記憶答 —— 點開看，它其實有查到東西，
只是自己發明了 `[來源: 檔名 / 章節]` 這種寫法，前端認的是 `[檔名#編號]`，
所以整排出處變成死字、點不開。**根因是那份 policy 沒規定出處格式。**

> **教學金句**：「呼叫次數多不代表比較好 —— 它代表在自我修正，也代表更慢更貴。
> 出處 0 個要先看清楚是憑記憶答，還是格式寫錯 —— 兩種都很常見。」

---

## Step 6 🧰：自己組第十五個（30 分鐘）

三種做法。後兩種會存成 `architectures/*.json` 進選單；第一種在 notebook 裡直接跑。

### A. 手寫（notebook 裡最快）

```python
我的架構 = M.Architecture(
    name="客服知識庫用",
    paper="自己組的",
    orchestration="Conditional",
    modules=["search", "grade_documents"],
    policy="""先用 search 查一次。用 grade_documents 讀完整內文逐塊給 0-2 分。
多數低於 1 分就改寫 query 再查一輪，兩輪都不行就明講知識庫沒有，不要用背景知識補。
答案裡每個事實都要標出處，格式是把片段 id 放進方括號：[CLAUDE.md#12]。""",
)

run = await M.arun(我的架構, "hook 要怎麼擋住寫入 .env？", ix)
```

**不用登記、不用改任何檔案就能跑。** 想讓它出現在網頁選單，
就照 `architectures/README.md` 的格式存一份 JSON 進去，重開服務即可。

### B. 跟 agent 聊（主畫面「讓 agent 幫我組一個」）

它會問最多五個問題，每個都附「為什麼問這個」——
答錯的代價／問題型態／使用者用不用術語／延遲能忍多少／查不到怎麼辦。
問完吐一份 JSON，按「存起來並套用」就進選單。

### C. 畫布（`/studio`）

拖模組、拉連線、線上寫條件。**但這一頁最重要的是標題列那句話**：

> **這張圖不會被執行。被執行的是右邊那段 policy —— 圖只是幫你把它想清楚。**

這是跟 LangGraph 最大的差別：

| | LangGraph | 這套 |
|---|---|---|
| 圖是什麼 | **就是程式**，edge 決定控制流 | **草稿**，交出去的是模組清單 + 一段 prompt |
| 誰決定下一步 | 你寫的 `add_conditional_edges` | agent 自己，依 policy 判斷 |
| 改流程要 | 改圖、重新 compile | 改那段字 |
| 代價 | 沒想到的分支就走不到 | 判斷準則寫不清楚它就亂走 |

畫布會把你畫的圖**編譯成文字**放在 policy 上面 —— 看不懂那段文字，
就表示這張圖其實沒說清楚任何事。反過來，「從現有架構開始」載入 CRAG 時，
它會把 CRAG 的 policy **讀成一張圖**再畫出來，論文那三個分支一條不漏。

> **教學金句**：「圖可以編譯成 policy，policy 也可以反推回圖 —— 因為它們講的是同一件事。
> 但被執行的永遠是文字那一份。」

**畫布上只放一顆 `WebSearch` 也跑得動**，沒寫 policy 也能按「試跑」——
它會拿「這張圖的意思」代跑，並在軌跡上告訴你代跑的是什麼。

---

## Step 7 📤：索引期也可以是 agentic 的（40 分鐘・延伸）

前面六步講的都是**檢索期**的決策。但「文件怎麼切」同樣是決策，
而且切錯的話後面所有架構都救不回來。

把檔案拖到網頁上任何地方 → agent 會：

1. 讀開頭和中間各一段，**自己判斷**這是什麼文件、該怎麼切（`ingest.make_plan`）
2. 決定要不要**補脈絡**（Contextual Retrieval：每個片段前面加一句「這段在講什麼」，
   只進 embedding 不進顯示）
3. 切完併進語料庫，**只向量化新片段**

### 一件刻意不交給 agent 決定的事

**embedding 模型不能換。** 換了就要重算全部向量，不然新舊片段在不同的向量空間裡，
算出來的相似度是垃圾。這種「全域一致性」的決定不該交給逐份文件的判斷。

> **教學金句**：「agent 可以決定這一份怎麼切，不能決定全庫用哪個 embedding ——
> 前者是局部判斷，後者是全域契約。」

---

## Step 8 🎬：讓上課不靠網路也不靠額度（15 分鐘・延伸）

現場問一題要等 30–90 秒。那段時間你只能尬聊，而且每次跑出來的軌跡都不一樣、
講稿對不上；額度用完或教室沒網路，整堂課就停在那裡。

所以**每次問答都會自動錄下完整事件流**，按「重播」挑一份放回去 ——
**不呼叫 LLM，秒開**。

| 控制 | 什麼時候用 |
|---|---|
| 壓縮等待（預設） | 60 秒的軌跡 10 秒播完，順序與節奏都在 |
| 原速 | 要讓人體感「它真的想了這麼久」 |
| **下一步** | 講到哪停到哪 —— 現場最常用的就是這顆 |
| 釘選 | 備課時挑一份最漂亮的釘住，不會被自動清掉 |

實作只有一句話：**重播餵的是同一組事件，所以直接呼叫原本的 `handle()`。**

> **教學金句**：「重播不是錄影 —— 錄影只能看，重播是把同一批事件餵回同一個渲染函式。
> 所以它不可能跟實跑長得不一樣。」

---

## Step 9 🔌：模組的第三種來源，跟換掉整個後端模型（30 分鐘・延伸）

📓 `notebooks/04_mcp_and_providers.ipynb`（純程式碼版，不開網頁）

### 我們自己就是一個 MCP server

`modules.py` 的 `build_mcp_server()` 最後一行：

```python
return create_sdk_mcp_server("ragmod", "1.0.0", sdk_tools)
```

**那七個模組從第一天就是包成一個叫 `ragmod` 的 MCP server 餵給 SDK 的。**
所以接別人的 MCP server 不是外掛：

```
mcp__ragmod__search             ← 你自己寫的 @tool
WebSearch                       ← SDK 內建，Anthropic 那端執行
mcp__context7__query-docs       ← 別人的 MCP server
```

**在 policy 裡它們都只是一個名字。**

| 來源 | 看得到原始碼嗎 | 誰執行 | 在 `Architecture` 裡 |
|---|---|---|---|
| 本地 `@tool` | 看得到 | 你的機器 | `modules` |
| SDK 內建 | 看不到 | Anthropic | `builtin_tools` |
| 外部 MCP | 只知道介面 | 那個 server | `mcp_tools` |

`/studio` 左下「＋ 接一個 MCP server」可以**一鍵匯入你 Claude Code 已經裝好的**
（讀 `~/.claude.json`）。連不上就不給存 —— 存一個死的 server，
下次跑不動時你只會以為是自己的 policy 寫壞了。

⚠️ **外部來源的出處必須跟知識庫分開標**（`[mcp: 工具名]` vs `[檔名#編號]`）。
只要架構有 `mcp_tools`，這條規則會自動加進 system prompt。
混在一起比沒有出處更危險，因為它看起來很可信。

### 換供應商：點一下，不用重開

還記得 Step 0 那句「四種接法程式碼一個字都不一樣」嗎？現在用它。

`ClaudeAgentOptions.env` 是**每次 spawn 才疊上去**的，所以可以每一次呼叫都換一個供應商。
Studio 頂上「模型：…」點下去：OAuth 訂閱／Anthropic API Key／
**Anthropic 相容端點（DeepSeek、Kimi、GLM、LiteLLM 一鍵帶入）**／Bedrock／Vertex。

填的 token **只留在記憶體**，不寫進 `.env`。

⚠️ **「試連看看」一定要按。** base URL 打錯的話 **CLI 不會報錯，它會安靜地一直重試**，
問答那邊就只是轉圈圈 —— 第一反應永遠是「我 policy 是不是寫壞了」，然後找錯地方。

> **教學金句**：「換掉整個後端模型，改的是環境變數，不是你的架構。
> 你的架構本來就不知道它背後是誰。」

---

## 卡點對照表 ⭐

| 卡點 | 真實原因 | 處理 |
|---|---|---|
| `ModuleNotFoundError: modules` | notebook 的工作目錄在 `notebooks/` | 跑第一格（會自動 `chdir("..")`） |
| `ModuleNotFoundError: modules` | kernel 選錯了，跟開哪個資料夾無關 | 跑 `./scripts/setup_kernel.sh`，選 `agentic-rag (.venv, Python 3.13)` |
| VS Code 說找不到套件 | 它自己在 `notebooks/` 建了一個空 venv | 刪掉 `notebooks/.venv`，再選上面那個 kernel |
| 啟動說找不到索引 | 還沒建 | `uv run python index_corpus.py --no-vectors` |
| 第一次跑很久沒反應 | 在下載 embedding 模型（約 100MB） | 沒網路就一律先 `--no-vectors` |
| HyDE 效果很差 | 沒有向量索引，退回 BM25 了 | 重建索引（不加 `--no-vectors`） |
| Self-RAG 跑 90 秒以上 | Looping 編排本來就慢 | 正常。調低 `max_turns` 或改用 CRAG |
| 每個架構跑出來都差不多 | 問題太簡單，分不出差異 | 用刻意口語化 / 超出語料範圍的問題 |
| agent 沒照 policy 的分支走 | policy 寫得像建議不像規則 | 用「**一定要**」「**先…再…**」祈使句，並要它明講選了哪支 |
| 設了 `tools=[]` 但 MCP 工具也不見 | 誤會 —— `tools` 只管內建工具 | MCP 工具走 `mcp_servers`，兩者獨立 |
| `allowed_tools` 寫了還是被擋 | 忘記 `mcp__<server>__` 前綴 | 用完整名稱 |
| 答案的出處點不開 | policy 沒規定格式，模型自己發明了一種 | policy 裡把 `[檔名#編號]` 寫死 |
| 換了供應商，問答一直轉圈圈 | base URL 或模型名錯了，CLI 不會報錯 | 按「試連看看」；120 秒後系統也會自己說 |
| MCP server 存不進去 | 連不上的一律不給存 | 錯誤訊息是真的，多半是指令不在 PATH 或網址錯字 |
| 上傳 PDF 切出 0 個片段 | 掃描件，沒有文字層 | 先 OCR 再上傳 |
| 改了架構但行為沒變 | notebook 那格沒重跑 | 重跑該格 |

---

## 私房筆記

**節奏**：Step 4 給滿 80 分鐘不要趕，那是全場的重心。Step 1 如果聽眾偏產品/企劃，
四樣東西只講 `@tool` 和 `system_prompt` 就好。

**故意踩三個坑**（比口頭講有效十倍）：

1. Step 1 先不寫 `tools=[]`，讓 agent 真的去跑 Bash，再加上去。
2. Step 4 的 HyDE 先用純 BM25 跑，爛給大家看，再建向量重跑。
3. Step 9 把 base URL 改成 `http://127.0.0.1:9`，按「試連看看」看它吐錯誤，再還原。

**驗收全場有沒有效的關鍵**：Step 6 學生只要寫一份 `Architecture`，
**不用碰任何程式碼**就能組出新架構。做得到就是懂了。

**不同角色的重點**：
- 後端／ML：Step 2–4（模組邊界、policy 怎麼寫）
- 產品／企劃：Step 5–6（怎麼驗證、怎麼跟 agent 聊出架構）
- 平台／IT：Step 9（換供應商、MCP 授權邊界）

---

## 一句話總結

> **模組是能力，policy 是編排，架構是資料 —— 所以「加一個新的 RAG 架構」
> 應該是寫一份 JSON，不是寫一個新系統。**

---

## 進階閱讀

- 🔗 [Modular RAG（Gao et al. 2024）](https://arxiv.org/abs/2407.21059) —— 這套的理論骨架
- 🔗 [CRAG（Yan et al. 2024）](https://arxiv.org/abs/2401.15884) —— 三分支，注意 Ambiguous 的定義
- 🔗 [Self-RAG（Asai et al. 2024）](https://arxiv.org/abs/2310.11511) —— 反思式檢索
- 🔗 [Adaptive-RAG（Jeong et al. 2024）](https://arxiv.org/abs/2403.14403) —— 複雜度路由
- 🔗 [Contextual Retrieval（Anthropic）](https://www.anthropic.com/news/contextual-retrieval) —— Step 7 的補脈絡
- 🔗 [Claude Agent SDK 文件](https://docs.claude.com/en/api/agent-sdk/overview)
- 🔗 `scripts/fetch_papers.sh` 會把上面這些論文抓進 `corpus/papers/`，
  然後你可以用 `paper_slides` 架構請系統自己讀它們

---

_Last updated: 2026-09-15_
_Maintainer: Kevin_
_配套教材：`README.md`（功能參考）+ `notebooks/`（主教材）+ `architectures/README.md`（架構格式）_
_講師現場帶課的逐字稿：母 repo 的 `docs/walkthroughs/agentic_rag_walkthrough.md`_
