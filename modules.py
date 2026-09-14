"""Modular RAG 模組庫 —— 所有 RAG 架構都是這些模組的不同編排。

Gao et al. 2024《Modular RAG》的主張：CRAG、Self-RAG、Adaptive-RAG 這些名字
聽起來各自獨立，其實是同一組模組（Pre-retrieval / Retrieval / Post-retrieval）
用不同的編排流程（Linear / Conditional / Branching / Looping）串起來而已。

這支檔案就是把那個主張做成可執行的東西：
    模組  = 給 agent 的工具（能力）
    編排  = 寫進 system prompt 的規則（政策）
    架構  = 模組清單 + 編排規則   ← Architecture dataclass

換架構不是改程式碼，是換一份 Architecture。

配套 notebook：notebooks/02_compose_architectures.ipynb
"""

from __future__ import annotations

import inspect
import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from retrieval import Index, bm25_search, get_chunk, hybrid_search, neighbors, rrf, vector_search

SNIPPET = 240
PROJECT_DIR = Path(__file__).resolve().parent


# ═══════════════════════════════════════════════════════════
# 模組庫：依 Modular RAG 的階段分類
# ═══════════════════════════════════════════════════════════


def _hits_to_results(ix: Index, hits) -> list[dict]:
    out = []
    for h in hits:
        c = get_chunk(ix, h.chunk_id)
        out.append(
            {
                "chunk_id": c.id,
                "path": c.path,
                "heading": c.heading,
                "snippet": c.text[:SNIPPET] + ("…" if len(c.text) > SNIPPET else ""),
                "score": round(h.score, 4),
            }
        )
    return out


# ── Retrieval 階段 ─────────────────────────────────────────


def search(ix: Index, query: str, method: str = "hybrid", k: int = 5, path: str = "") -> dict:
    """[Retrieval] 基本檢索。method 由模型自己選，這一行就是 Router。

    path 可選：只在某一份文件裡找。做「針對這份文件問答」時用，
    避免答案混進其他文件的內容 —— 使用者面前開著 A 文件，你引用 B 文件會很怪。
    """
    searchers = {"bm25": bm25_search, "vector": vector_search, "hybrid": hybrid_search}
    fn = searchers.get(method)
    if fn is None:
        return {"error": f"method 只能是 {list(searchers)}，收到 {method!r}"}
    if path:
        # 先多撈一些再過濾，才不會因為別的文件佔滿名額而回空的
        hits = [h for h in fn(ix, query, k=k * 8) if get_chunk(ix, h.chunk_id).path == path][:k]
    else:
        hits = fn(ix, query, k=k)
    out = {"query": query, "method": method, "results": _hits_to_results(ix, hits)}
    if path:
        out["scoped_to"] = path
    if not out["results"]:
        out["hint"] = "一個詞都沒命中。換文件裡可能出現的術語，或改用 vector / hybrid。"
    if hits and hits[0].degraded:
        out["degraded"] = "向量不可用，實際是用 BM25 跑的"
    return out


# ── Pre-retrieval 階段：檢索「之前」動手腳 ──────────────────


def multi_search(ix: Index, queries: list[str], method: str = "hybrid", k: int = 5) -> dict:
    """[Pre-retrieval] RAG-Fusion：一次丟多個改寫過的 query，用 RRF 融合結果。

    單一 query 的用詞偏好會決定命中什麼。丟 3-5 個不同角度的問法，
    同時出現在多份榜上的片段自然浮上來 —— 這比單查一次穩很多。
    """
    if not queries:
        return {"error": "queries 不能是空的"}
    searchers = {"bm25": bm25_search, "vector": vector_search, "hybrid": hybrid_search}
    fn = searchers.get(method, hybrid_search)

    rankings, per_query = [], {}
    for q in queries:
        hits = fn(ix, q, k=k * 2)
        rankings.append([h.chunk_id for h in hits])
        per_query[q] = len(hits)

    fused = rrf(rankings)[:k]
    return {
        "queries": queries,
        "per_query_hits": per_query,
        "fusion": "RRF",
        "results": [
            {
                "chunk_id": cid,
                "path": get_chunk(ix, cid).path,
                "heading": get_chunk(ix, cid).heading,
                "snippet": get_chunk(ix, cid).text[:SNIPPET],
                "rrf_score": round(score, 5),
            }
            for cid, score in fused
        ],
    }


def hyde_search(ix: Index, hypothetical_answer: str, k: int = 5) -> dict:
    """[Pre-retrieval] HyDE：不要拿問題去比對，拿你「猜的答案」去比對。

    問題和答案的語意分佈不一樣 —— 問句短、抽象；文件是陳述句、具體。
    先請模型憑空寫一段「答案看起來會長這樣」，再拿那段去做向量檢索，
    比對的就是陳述句對陳述句，命中率通常明顯提升。

    注意這裡「假答案」可能整段是錯的 —— 沒關係，我們要的是它的用詞與句式。
    """
    hits = vector_search(ix, hypothetical_answer, k=k)
    return {
        "hypothetical_answer": hypothetical_answer[:200],
        "note": "用假設答案而非原問題做檢索（HyDE）",
        "results": _hits_to_results(ix, hits),
        "degraded": "向量不可用，退回 BM25（HyDE 在純 BM25 下效果會打折）"
        if hits and hits[0].degraded
        else None,
    }


# ── Post-retrieval 階段：檢索「之後」動手腳 ─────────────────


def grade_documents(ix: Index, question: str, chunk_ids: list[str]) -> dict:
    """[Post-retrieval] CRAG 的 evaluator：取回完整內文讓模型自評。

    這個工具自己一分都不打 —— 分數由模型判斷。

    也刻意不回傳「接下來該怎麼做」：那是編排，屬於 Architecture 的 policy。
    工具回傳值裡夾指示，模型會（正確地）把它當成來路不明的指令而警戒，
    答案裡就會多出一句「我沒有照它執行」的雜訊。**工具回資料，policy 給指示。**
    「夠不夠回答這個問題」是語意判斷，不是數值判斷：
    cosine 0.8 可能完全沒用，0.4 可能正中紅心。
    把評分寫成 Python 的那一刻，整套就退化回 pipeline RAG 了。
    """
    missing = [c for c in chunk_ids if c not in ix.by_id]
    if missing:
        return {"error": f"這些 chunk_id 不存在：{missing}", "hint": "id 必須來自檢索結果"}
    return {
        "question": question,
        "rubric": "2 = 直接回答了問題；1 = 相關但不完整；0 = 無關",
        "chunks": [
            {
                "chunk_id": cid,
                "path": get_chunk(ix, cid).path,
                "heading": get_chunk(ix, cid).heading,
                "text": get_chunk(ix, cid).text,
            }
            for cid in chunk_ids
        ],

    }


def expand(ix: Index, chunk_id: str, window: int = 1) -> dict:
    """[Post-retrieval] context enrichment：沿文件順序往前後抓鄰居。

    切塊一定會切斷語意。片段提到「見下節」「如下表」而內容不在手上時用它。
    這是最便宜的 graph 擴展，不必真的建知識圖譜。
    """
    if chunk_id not in ix.by_id:
        return {"error": f"chunk_id 不存在：{chunk_id}"}
    around = neighbors(ix, chunk_id, window=window)
    return {
        "center": chunk_id,
        "chunks": [
            {"chunk_id": c.id, "path": c.path, "heading": c.heading, "text": c.text}
            for c in around
        ],
    }


def diversify(ix: Index, chunk_ids: list[str], k: int = 5, lambda_: float = 0.7) -> dict:
    """[Post-retrieval] MMR：在相關性和多樣性之間取平衡。

    檢索結果常常是同一段話的五個變體 —— 相關度都很高，但資訊量等於一則。
    MMR 每次挑「跟問題夠相關、且跟已選的夠不一樣」的那一個。
    lambda 越大越重視相關性，越小越重視多樣性。
    """
    if not ix.has_vectors:
        return {
            "selected": chunk_ids[:k],
            "note": "向量不可用，MMR 退化成原順序截斷",
            "degraded": True,
        }
    valid = [c for c in chunk_ids if c in ix.order]
    if not valid:
        return {"error": "沒有一個 chunk_id 有效"}

    vecs = ix.store.vectors_for(valid)   # numpy 或 chroma 都走這個介面
    query_vec = vecs.mean(axis=0)  # 用候選集的重心當代表
    relevance = vecs @ query_vec

    selected: list[int] = []
    remaining = list(range(len(valid)))
    while remaining and len(selected) < k:
        if not selected:
            best = int(np.argmax(relevance[remaining]))
        else:
            sims = vecs[remaining] @ vecs[selected].T  # 跟已選的相似度
            mmr = lambda_ * relevance[remaining] - (1 - lambda_) * sims.max(axis=1)
            best = int(np.argmax(mmr))
        selected.append(remaining.pop(best))

    return {
        "selected": [valid[i] for i in selected],
        "lambda": lambda_,
        "note": f"從 {len(valid)} 個候選用 MMR 挑出 {len(selected)} 個",
    }


# ── Indexing 階段（唯讀檢視，給 Adaptive 路由判斷用）────────


def list_corpus(ix: Index) -> dict:
    """[Indexing] 看知識庫涵蓋什麼 —— 路由決策的依據。"""
    counts: dict[str, int] = {}
    for c in ix.chunks:
        counts[c.path] = counts.get(c.path, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])
    return {
        "total_chunks": len(ix.chunks),
        "total_files": len(counts),
        "has_vectors": ix.has_vectors,
        "files": [{"path": p, "chunks": n} for p, n in ranked[:50]],
    }


# ═══════════════════════════════════════════════════════════
# 模組註冊表
# ═══════════════════════════════════════════════════════════

MODULES: dict[str, dict[str, Any]] = {
    "list_corpus": {
        "stage": "Indexing",
        "fn": list_corpus,
        "description": "列出知識庫有哪些檔案、各有幾個片段。判斷問題是否在範圍內、該往哪找時用。",
        "schema": {"type": "object", "properties": {}, "required": []},
    },
    "search": {
        "stage": "Retrieval",
        "fn": search,
        "description": (
            "檢索知識庫。method 自己選：bm25（關鍵字精確，查術語/指令/檔名最準）、"
            "vector（語意相似，使用者用自己的話描述時用）、hybrid（RRF 融合，不確定就用這個）。"
            "回空陣列代表用詞跟文件對不上，換個說法再試。"
        ),
        "schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "method": {"type": "string", "enum": ["bm25", "vector", "hybrid"]},
                "k": {"type": "integer", "description": "預設 5"},
                "path": {
                    "type": "string",
                    "description": "只在這一份文件裡找（例如 papers/crag.pdf）。留空就是全部語料。",
                },
            },
            "required": ["query", "method"],
        },
    },
    "multi_search": {
        "stage": "Pre-retrieval",
        "fn": multi_search,
        "description": (
            "RAG-Fusion：一次送多個不同角度的 query，結果用 RRF 融合。"
            "問題可以有很多種問法、或包含多個子問題時用，比單查一次穩。建議 3-5 個。"
        ),
        "schema": {
            "type": "object",
            "properties": {
                "queries": {"type": "array", "items": {"type": "string"}},
                "method": {"type": "string", "enum": ["bm25", "vector", "hybrid"]},
                "k": {"type": "integer"},
            },
            "required": ["queries"],
        },
    },
    "hyde_search": {
        "stage": "Pre-retrieval",
        "fn": hyde_search,
        "description": (
            "HyDE：先自己寫一段「答案大概長這樣」的假設文字，拿那段去做向量檢索。"
            "假答案內容錯沒關係，要的是它的用詞與句式跟真文件對得上。"
            "使用者問得抽象、或你猜得到答案的寫法時特別有效。"
        ),
        "schema": {
            "type": "object",
            "properties": {
                "hypothetical_answer": {
                    "type": "string",
                    "description": "你憑空寫的假設答案，寫得像文件裡的陳述句，2-4 句",
                },
                "k": {"type": "integer"},
            },
            "required": ["hypothetical_answer"],
        },
    },
    "grade_documents": {
        "stage": "Post-retrieval",
        "fn": grade_documents,
        "description": (
            "取回片段的完整內文，讓你評估夠不夠回答問題。這個工具不會幫你打分，"
            "分數由你自己判斷後寫在回覆裡。多數不合格就不要硬答。"
        ),
        "schema": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "chunk_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["question", "chunk_ids"],
        },
    },
    "expand": {
        "stage": "Post-retrieval",
        "fn": expand,
        "description": "取某片段在原文中的前後鄰居。片段被切斷、或提到「見下節」時用。",
        "schema": {
            "type": "object",
            "properties": {
                "chunk_id": {"type": "string"},
                "window": {"type": "integer", "description": "前後各取幾塊，預設 1"},
            },
            "required": ["chunk_id"],
        },
    },
    "diversify": {
        "stage": "Post-retrieval",
        "fn": diversify,
        "description": (
            "MMR 去重：從一堆候選片段裡挑出「相關且彼此不重複」的子集。"
            "檢索結果看起來都在講同一件事時用它，避免 context 被同一段話的變體塞滿。"
        ),
        "schema": {
            "type": "object",
            "properties": {
                "chunk_ids": {"type": "array", "items": {"type": "string"}},
                "k": {"type": "integer"},
                "lambda_": {"type": "number", "description": "0-1，越大越重相關性，預設 0.7"},
            },
            "required": ["chunk_ids"],
        },
    },
}


# SDK 內建工具：不是我們寫的，執行在 Anthropic 那端，但 hook 一樣攔得到，
# 所以軌跡與流程圖上照樣看得見它。
BUILTIN_TOOLS: dict[str, dict[str, str]] = {
    "WebSearch": {
        "stage": "Retrieval",
        "description": "SDK 內建：知識庫查不到時上網找。CRAG 的 INCORRECT 分支用。",
    },
}


def run_module(name: str, args: dict, ix: Index) -> dict:
    """所有模組的唯一執行入口。錯誤回傳而不拋出 —— 讓模型自己看到並修正。"""
    mod = MODULES.get(name)
    if mod is None:
        return {"error": f"沒有這個模組：{name}", "hint": f"可用的是 {list(MODULES)}"}
    try:
        return mod["fn"](ix, **args)
    except TypeError as exc:
        return {"error": f"參數不對：{exc}", "hint": "對照 schema 檢查參數名稱與型別"}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


BUILTIN_NOTE = """# {name} 是 Claude Agent SDK 的內建工具，不是這個專案寫的。
#
# 啟用方式就一行 —— 在 Architecture 上宣告：
#
#     CRAG = Architecture(
#         ...,
#         builtin_tools=["WebSearch"],   # ← 這裡
#     )
#
# 然後 build_options() 會把它交給 SDK：
#
#     ClaudeAgentOptions(
#         tools=arch.builtin_tools,      # 只開架構明確要的內建工具，其餘全關
#         allowed_tools=[...] + arch.builtin_tools,
#     )
#
# 內建工具由 Anthropic 那端執行，所以你看不到它的原始碼 ——
# 但 PreToolUse hook 一樣攔得到，軌跡上照樣看得見它查了什麼。
"""


def module_source(name: str) -> str:
    """模組的實際原始碼。notebook 裡可以直接印出來看，永遠跟跑的東西一致。"""
    mod = MODULES.get(name)
    if mod:
        return inspect.getsource(mod["fn"])
    if name in BUILTIN_TOOLS:
        return BUILTIN_NOTE.format(name=name)
    return f"# 找不到模組 {name}"


# ═══════════════════════════════════════════════════════════
# 架構 = 模組清單 + 編排規則
# ═══════════════════════════════════════════════════════════

BASE_POLICY = """你是一個檢索問答助理，只能根據知識庫回答問題。

**每次呼叫工具前，先用一句話說明你為什麼這樣做。** 不要只說「我來搜尋」，
要講判斷依據（例如「這題問的是具體指令，關鍵字比語意準，用 bm25」）。

**答案裡每個事實都要標出處**，格式是把片段 id 放進方括號：[CLAUDE.md#12]。
知識庫查不到就直說查不到，不要用自己的背景知識補。

用繁體中文，直接講結論，有指令就把指令貼出來。"""


@dataclass
class Architecture:
    """一個 RAG 架構 = 用哪些模組 + 怎麼編排它們。

    這個 dataclass 就是整套教材的核心主張：CRAG 和 Self-RAG 的差別不在程式碼，
    在 policy 那段字串裡。
    """

    name: str
    paper: str  # 出處
    orchestration: str  # Linear / Conditional / Branching / Looping
    modules: list[str]  # 用到哪些模組
    policy: str  # 這個架構的編排規則
    builtin_tools: list[str] = field(default_factory=list)  # SDK 內建工具，如 WebSearch
    max_turns: int = 12

    def system_prompt(self) -> str:
        return f"{BASE_POLICY}\n\n## 這次採用的流程：{self.name}\n\n{self.policy.strip()}"

    def summary(self) -> str:
        stages = sorted({MODULES[m]["stage"] for m in self.modules if m in MODULES})
        tools = self.modules + [f"{t}(SDK 內建)" for t in self.builtin_tools]
        return (
            f"{self.name}  [{self.orchestration}]\n"
            f"  出處：{self.paper}\n"
            f"  階段：{' → '.join(stages)}\n"
            f"  模組：{', '.join(tools)}"
        )


# ── 六個現成架構 ───────────────────────────────────────────

NAIVE = Architecture(
    name="Naive RAG",
    paper="Lewis et al. 2020（原始 RAG）",
    orchestration="Linear",
    modules=["search"],
    policy="""檢索一次，然後根據結果作答。

不要重試、不要改寫 query、不要評估品質 —— 就查一次。
這是基準線，用來對照後面幾種架構好在哪。""",
    max_turns=4,
)

RAG_FUSION = Architecture(
    name="RAG-Fusion（多查詢）",
    paper="Rackauckas 2024 / Query Expansion 系列",
    orchestration="Branching",
    modules=["multi_search"],
    policy="""把使用者的問題改寫成 3-5 個不同角度的問法，一次用 multi_search 送出去。

改寫要真的不一樣：換術語、換抽象層級、拆成子問題、用文件作者可能的寫法。
RRF 會把同時出現在多份榜上的片段推到前面 —— 這就是多查詢的價值。

拿到融合結果就作答，不要再多查。""",
    max_turns=5,
)

HYDE = Architecture(
    name="HyDE",
    paper="Gao et al. 2022《Precise Zero-Shot Dense Retrieval without Relevance Labels》",
    orchestration="Linear（Pre-retrieval 轉換）",
    modules=["hyde_search", "search"],
    policy="""先憑空寫一段「如果文件裡有答案，它大概會這樣寫」的假設文字（2-4 句，
寫成陳述句，用該領域會用的術語），拿它呼叫 hyde_search。

你寫的假答案內容可能完全錯 —— 沒關係，我們要的是句式和用詞跟真文件對得上。

如果 hyde_search 結果不理想，再用 search 補一次關鍵字檢索。""",
    max_turns=6,
)

CRAG = Architecture(
    name="CRAG（Corrective RAG）",
    paper="Yan et al. 2024《Corrective Retrieval Augmented Generation》",
    orchestration="Conditional（三分支 + web fallback）",
    modules=["search", "grade_documents", "expand"],
    builtin_tools=["WebSearch"],   # 論文的 INCORRECT 分支就是 fallback 到網路搜尋
    policy="""照 CRAG 的三分支流程走：

1. 先用 search 檢索**知識庫**。
2. 用 grade_documents 取回完整內文，逐塊給 0-2 分。
3. 依整體信心度走分支（照論文的定義，別搞混）：
   - **CORRECT**（多數 2 分）→ **不要整段照抄**。先把內文拆成小段、丟掉跟問題無關的、
     再重組成精煉的知識片段，然後作答。這一步叫 decompose-then-recompose，
     是這篇論文最核心的貢獻 —— 因為就算文件相關，裡面也有大量無關段落。
     片段被切斷就用 expand 補。
   - **INCORRECT**（多數 0 分）→ **丟掉**這批檢索結果，改用 WebSearch 上網找。
     論文的做法是把問題改寫成關鍵字查詢再送去搜尋。
   - **AMBIGUOUS**（介於中間、判斷不了）→ **兩邊都用**：精煉後的內部知識
     ＋ WebSearch 的外部結果，合併後作答。這是「不確定時不賭單邊」的保守做法。

**WebSearch 的三條規矩**（很重要，這是可信度的分水嶺）：

- 只在走到 INCORRECT 分支時用。知識庫有答案就不要上網 —— 內部文件才是這個系統的權威來源。
- 網路來源和知識庫來源**必須分開標**：
  知識庫用 `[CLAUDE.md#12]`，網路用 `[web: 網站名 - 完整網址]`。
- 答案開頭要有一句話說明「這題知識庫沒有，以下來自網路」，不要混在一起讓使用者分不出來。

每次分支判斷都要說出你選了哪一支、為什麼。""",
    max_turns=16,
)

SELF_RAG = Architecture(
    name="Self-RAG",
    paper="Asai et al. 2024《Self-RAG: Learning to Retrieve, Generate and Critique》",
    orchestration="Looping（自我反思迴圈）",
    modules=["search", "grade_documents", "expand", "diversify"],
    policy="""Self-RAG 的精神是「每一步都先問自己要不要做、做完再批判一次」。
論文用特殊 token 訓練模型輸出這些判斷，我們改成讓你明講出來。

每一輪都依序回答這四個反思問題，並把答案寫出來：

1. **需要檢索嗎？** 這題如果知識庫沒有就答不了 → 檢索。（純語言任務可以不檢索）
2. **檢索到的相關嗎？** 用 grade_documents 判斷。不相關就改寫 query 重來。
3. **我的草稿有被檢索內容支撐嗎？** 逐句檢查。沒有出處的句子刪掉或重查。
4. **這樣回答對使用者有用嗎？** 不夠完整就再補一輪。

候選片段看起來在重複講同一件事時，用 diversify 去重。
最多循環三輪，第三輪還不滿意就如實說明限制。""",
    max_turns=16,
)

ADAPTIVE = Architecture(
    name="Adaptive-RAG",
    paper="Jeong et al. 2024《Adaptive-RAG: Learning to Adapt Retrieval-Augmented LLMs》",
    orchestration="Conditional（複雜度路由）",
    modules=["list_corpus", "search", "multi_search", "grade_documents", "expand"],
    policy="""先判斷問題複雜度，再決定花多少力氣 —— 簡單問題用複雜流程是浪費成本與延遲。

**第一步：分類（一定要明講你選了哪一類、為什麼）**

- **A 類｜不需檢索**：純語言任務（翻譯、改寫、格式轉換），或問題明顯超出知識庫範圍。
  → 不檢索，直接回答或直接說明超出範圍。不確定範圍就先 list_corpus 看一眼。
- **B 類｜單步檢索**：單一事實查詢，一次檢索就能答。
  → search 一次 → 作答。
- **C 類｜多步檢索**：需要比較、綜合多個來源、或有前後依賴的多跳問題。
  → multi_search 或連續多次 search → grade_documents 驗證 → 必要時 expand → 作答。

論文用一個訓練過的小分類器做這件事，延遲和成本都更低；
我們用你自己的判斷，好處是不用訓練、壞處是分類本身也要花一次推論。
這個取捨要在你的說明裡點出來。""",
    max_turns=14,
)

MODULAR_DIY = Architecture(
    name="Modular RAG（自由組合）",
    paper="Gao et al. 2024《Modular RAG: Transforming RAG Systems into LEGO-like Frameworks》",
    orchestration="Adaptive（由你決定）",
    modules=list(MODULES),
    builtin_tools=["WebSearch"],
    policy="""所有模組都給你，編排方式你自己決定。

開始之前先說出你的計畫：要用哪些模組、什麼順序、為什麼這樣排。
執行過程中如果發現計畫不對，明講你要改成什麼、為什麼改。

知識庫查不到時可以用 WebSearch 上網，但網路來源要標成 `[web: 網站名 - 網址]`，
和知識庫的 `[檔案.md#12]` 分開，並明講哪些內容來自外部。

可用的編排型態：
- **Linear**：固定順序跑完
- **Conditional**：依判斷結果走不同分支（CRAG 那種）
- **Branching**：同時展開多路再合併（RAG-Fusion 那種）
- **Looping**：檢索→生成→批判→再檢索（Self-RAG 那種）

沒有標準答案，但你要能說明為什麼這個問題適合你選的編排。""",
    max_turns=16,
)

# ── 以下五個是「純政策」架構：沒有新增任何模組，只是換一套編排規則 ──
# 五篇論文、零行新程式碼。這是 Modular RAG 主張最直接的證據。

REWRITE_RETRIEVE_READ = Architecture(
    name="Rewrite-Retrieve-Read",
    paper="Ma et al. 2023《Query Rewriting for Retrieval-Augmented LLMs》arXiv:2305.14283",
    orchestration="Linear（Pre-retrieval 改寫）",
    modules=["search"],
    policy="""照 Rewrite → Retrieve → Read 三步走，只在檢索**之前**下功夫：

1. **Rewrite**：把使用者的問題改寫成「文件作者可能會用的說法」。
   明確寫出改寫前後，並說明你換掉了哪些詞、為什麼。
   使用者說的是需求語言，文件寫的是實作語言 —— 這中間的落差就是檢索失敗的主因。
2. **Retrieve**：用改寫後的 query 做一次 search。
3. **Read**：根據結果作答。

不要評估、不要重試。這個架構刻意只做前置改寫，
用來對照 CRAG 那種「在檢索之後補救」的做法 —— 兩者可以疊加，但先分開理解。""",
    max_turns=6,
)

SELF_ASK = Architecture(
    name="Self-Ask",
    paper="Press et al. 2022《Measuring and Narrowing the Compositionality Gap》arXiv:2210.03350",
    orchestration="Linear（顯式問題分解）",
    modules=["search"],
    policy="""Self-Ask 的核心觀察：模型知道所有子事實，卻答錯需要組合它們的問題（compositionality gap）。
解法是**逼它把子問題明講出來**，一個一個查。

嚴格照這個格式跑，每一步都要寫出來：

```
是否需要後續問題：是
後續問題：<子問題 1>
中間答案：<用 search 查到的答案>
後續問題：<子問題 2>
中間答案：<用 search 查到的答案>
所以最終答案是：<組合出來的答案>
```

規則：

- **一次只問一個子問題**，查到答案再問下一個。不要一口氣列完所有子問題。
- 下一個子問題可以依賴上一個的中間答案 —— 這就是它比一次性分解強的地方。
- 如果第一步就判斷不需要分解，寫「是否需要後續問題：否」然後直接查、直接答。
- 中間答案一樣要標出處。""",
    max_turns=14,
)

IRCOT = Architecture(
    name="IRCoT（交錯檢索與推理）",
    paper="Trivedi et al. 2023《Interleaving Retrieval with Chain-of-Thought Reasoning》arXiv:2212.10509",
    orchestration="Looping（推理與檢索交錯）",
    modules=["search", "expand"],
    policy="""IRCoT 和 Self-Ask 的差別很細但很重要：
Self-Ask 分解的是**問題**，IRCoT 讓**推理的每一句話**都去帶動下一次檢索。

流程是一個小迴圈，每輪做兩件事：

1. **推理一步**：根據目前手上的所有片段，寫出思路的**下一句**（只寫一句，不要一口氣寫完）。
2. **用那句話去檢索**：把剛寫的那句當成 query 呼叫 search —— 不是用原問題，是用你剛推出來的那句。

重複到你的推理鏈自然收斂到答案為止。每輪都要寫出「這一句推理」和「因此我要查什麼」。

為什麼有效：多跳問題的第二跳關鍵字，往往只有在推完第一跳之後才知道。
用原問題查一百次也查不到第二跳需要的東西。

片段被切斷時用 expand 補上下文。最多跑六輪，收斂不了就如實說明卡在哪一跳。""",
    max_turns=16,
)

FLARE = Architecture(
    name="FLARE（前瞻式主動檢索）",
    paper="Jiang et al. 2023《Active Retrieval Augmented Generation》arXiv:2305.06983",
    orchestration="Looping（依信心觸發檢索）",
    modules=["search", "grade_documents"],
    policy="""前面每個架構都是「先檢索、再生成」。FLARE 反過來：**先生成，沒把握的地方才去檢索**。

流程：

1. **先寫草稿**：不查任何東西，直接把答案寫出來（就算你不確定）。
2. **標出沒把握的句子**：逐句檢視，把你「其實在猜」的句子明確列出來，並說明為什麼沒把握
   （具體數字？專有名詞？版本號？流程細節？）。
3. **只針對那些句子檢索**：把每個沒把握的句子當成 query 呼叫 search ——
   用**句子本身**當查詢，不是用原問題。
4. **改寫**：用檢索結果修正那些句子。查不到的就刪掉，或明講「知識庫沒有這項」。
5. 如果改寫後又產生新的不確定句子，再跑一輪。最多兩輪。

省成本的地方在這裡：**有把握的部分完全不花檢索成本**。
代價是你得先相信模型「知道自己不知道」—— 這個假設不是永遠成立，
所以最後要用 grade_documents 驗一次關鍵片段，避免它對自己太有信心。""",
    max_turns=14,
)

SEARCH_O1 = Architecture(
    name="Search-o1",
    paper="Li et al. 2025《Search-o1: Agentic Search-Enhanced Large Reasoning Models》arXiv:2501.05366",
    orchestration="Looping（推理中斷點檢索 + 文件精煉）",
    modules=["search", "grade_documents", "expand"],
    builtin_tools=["WebSearch"],
    policy="""Search-o1 是為「長推理模型」設計的：讓它**在推理途中卡住的那一刻**才去查，
而且查回來的東西**先精煉再放進推理鏈**。

兩個機制要分開做：

**一、在不確定點觸發檢索**

正常往下推理，一旦遇到「我不確定這裡」的知識缺口，就**停下來明講**：

> [知識缺口] 我需要知道 X 才能繼續，因為 Y。

然後才去 search。不要一開始就把所有能查的都查一遍 —— 那是浪費，
也會讓不相關的片段污染後面的推理。

**二、Reason-in-Documents：先精煉再注入**

這是 Search-o1 最關鍵的一步，也是最常被略過的一步。
檢索回來的原文**不要直接塞進推理鏈**，先用 grade_documents 讀完整內文，然後：

1. 只抽出「跟目前這個知識缺口有關」的部分
2. 壓縮成一到三句話
3. 明講這段精煉內容從哪個片段來

**只把精煉後的那幾句放進推理鏈。** 原因是長推理最怕上下文被雜訊稀釋 ——
直接注入整段原文會讓後面的推理跑偏。

知識庫真的沒有的時候才用 WebSearch，網路來源要標成 `[web: 站名 - 網址]`。""",
    max_turns=18,
)

PAPER_SLIDES = Architecture(
    name="論文重點 Slide",
    paper="不是論文方法，是一個實用案例：把 PDF 讀成可直接上投影片的重點",
    orchestration="Linear（定位 → 逐節精讀 → 產出投影片大綱）",
    modules=["list_corpus", "search", "grade_documents", "expand"],
    policy="""你的任務不是回答問題，是**把一篇論文整理成可以直接貼進投影片的重點**。

## 流程

1. **定位**：用 list_corpus 看知識庫裡有哪些 PDF，確認使用者指的是哪一篇。
   名字對不上就問，不要猜。
2. **抓骨架**：先檢索這篇的摘要與結論（query 用 abstract / conclusion / we propose 這類詞），
   建立整體理解。
3. **逐節精讀**：針對下面每一格分別檢索，並用 grade_documents 讀完整內文。
   **不要只看檢索摘要就下筆** —— 論文的關鍵數字常常在被截斷的那半段。
   片段被切斷就用 expand 往前後補。
4. **產出**：照下面的格式輸出。

## 輸出格式（嚴格照這個）

### 一句話
用一句話說完這篇在幹嘛。不要超過 40 字，不要用「本文提出一種基於…的方法」這種句型。

### 它要解決的問題
2-3 個 bullet。講清楚**沒有這篇之前，大家卡在哪裡**。

### 方法：怎麼做的
3-5 個 bullet，照執行順序寫。每個 bullet 要是**具體動作**，不是抽象名詞。

- 壞例子：「引入了一個輕量級評估模組」
- 好例子：「檢索完先用一個 T5-large 評估器給每份文件打分，分數落在三個區間走三條不同的路」

### 關鍵數字
表格。只放**能支撐主張的數字**，不要抄整張實驗表。

| 指標 | 數字 | 對照組 |
|---|---|---|

沒有明確數字就寫「論文未給出可比較的數字」，不要編。

### 限制與代價
2-3 個 bullet。**這格最重要，也最多人略過。** 包含：
額外的延遲或成本、需要訓練嗎、在什麼情況下會失效、作者自己承認的限制。

### 一句可以講給學生聽的話
一句話，白話、有記憶點、可以直接唸出來。

## 兩條硬規則

**每個 bullet 後面都要標頁碼**，格式 `[papers/檔名.pdf#片段編號]`。
聽眾要能翻回原文對照，沒有出處的重點在投影片上沒有價值。

**論文沒寫的不要寫。** 你對這篇的背景知識可能是對的，但那不是這篇的貢獻。
只寫檢索得到、而且你讀過完整內文的內容。""",
    max_turns=20,
)



DOC_CHAT = Architecture(
    name="文件問答（限定目前開啟的文件）",
    paper="實用案例：使用者面前開著一份文件，就只談這份",
    orchestration="Conditional（先看圈選、必要時才檢索）",
    modules=["search", "expand", "grade_documents"],
    policy="""使用者正在讀一份文件，你只回答**關於這份文件**的問題。

每次訊息開頭會附上：

```
【目前開啟】<檔案路徑>
【使用者圈選】<他在頁面上框起來的內容，可能沒有>
```

## 怎麼查

**一、search 一律帶 `path` 參數**，值就是「目前開啟」的那個路徑。
不要去查別的文件 —— 使用者面前開著 A，你引用 B 會讓他找不到你在說什麼。

**二、有圈選內容時，那就是問題的主體。** 先針對那一段回答。
只有在「光看這段不夠」時才 search 補上下文，並說明你為什麼需要補。

**三、圈選內容是空的或只有零碎文字** → 他多半框到圖或表格。
直接說「這一區我讀不到文字（可能是圖）」，然後**主動去 search 附近的圖說**
（試 Figure、Table、caption 這類詞），用圖說回答，並請他確認是不是問這張。

**四、這份文件裡沒有的就說沒有。** 不要用背景知識補、不要查別的文件。
超出範圍就說「這超出這份文件，要我改查整個知識庫嗎？」

## 回答格式（嚴格照這個，不要自由發揮）

```
### 一句話
<先給結論。一到兩句，不超過 50 字。>

### 說明
- <一點一個概念，一到兩句寫完> [出處]
- <下一點> [出處]

### 注意
- <限制、例外、容易誤解的地方> [出處]
```

**規則：**

| 規則 | 說明 |
|---|---|
| 「說明」最多 5 點 | 超過表示你在倒資料，不是在回答 |
| 一點只講一個概念 | 一個 bullet 裡出現「而且」「另外」就該拆成兩點 |
| 一點一個出處，放句尾 | **不要連續堆兩三個出處**，那會讓句子沒辦法讀 |
| 有數字就寫數字 | 「效果提升很多」是廢話，「準確率 +7.0%」才有用 |
| 「注意」沒有就整段不要寫 | 不要為了湊格式寫廢話 |

**不要做的事：**

- 不要重複使用者的問題當開場
- 不要寫「根據我檢索到的資料」「這份文件提到」這類鋪陳，直接講內容
- 不要在「一句話」裡塞出處，那一行要乾淨好唸
- 不要把整段原文抄過來當答案，用自己的話講，原文放出處讓他自己翻

使用者是邊讀邊問，**短而準**比完整重要。""",
    max_turns=10,
)


ARCHITECTURES: dict[str, Architecture] = {
    # 基準線
    "naive": NAIVE,
    # Pre-retrieval：在檢索「之前」動手腳
    "rewrite": REWRITE_RETRIEVE_READ,
    "hyde": HYDE,
    "rag_fusion": RAG_FUSION,
    # 問題分解 / 多跳
    "self_ask": SELF_ASK,
    "ircot": IRCOT,
    # Post-retrieval：在檢索「之後」補救
    "crag": CRAG,
    "self_rag": SELF_RAG,
    # 依需要才檢索
    "flare": FLARE,
    "search_o1": SEARCH_O1,
    "adaptive": ADAPTIVE,


    # 全部給你自己組
    "modular": MODULAR_DIY,
    # 實用案例
    "paper_slides": PAPER_SLIDES,
    "doc_chat": DOC_CHAT,
}


# ═══════════════════════════════════════════════════════════
# 用 Claude Agent SDK 把架構跑起來
# ═══════════════════════════════════════════════════════════


def build_mcp_server(arch: Architecture, ix: Index):
    """把架構用到的模組包成 in-process MCP server 交給 SDK。

    關鍵：不同架構拿到的工具清單不同 —— Naive RAG 只有 search，
    連「評估檢索品質」的能力都沒有，所以它結構上不可能自我修正。
    """
    from claude_agent_sdk import create_sdk_mcp_server, tool

    def make_handler(module_name: str):
        async def handler(args: dict) -> dict:
            result = run_module(module_name, args, ix)
            return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}

        return handler

    sdk_tools = [
        tool(name, MODULES[name]["description"], MODULES[name]["schema"])(make_handler(name))
        for name in arch.modules
        if name in MODULES
    ]
    return create_sdk_mcp_server("ragmod", "1.0.0", sdk_tools)


def build_options(arch: Architecture, ix: Index, on_event: Callable[[dict], None] | None = None):
    """把 Architecture 翻譯成 ClaudeAgentOptions。

    這個函式是整套的樞紐：換架構 = 換這裡吃到的 Architecture，
    SDK 呼叫方式一個字都不用改。
    """
    from claude_agent_sdk import ClaudeAgentOptions, HookMatcher

    step = {"n": 0}
    # 模型會平行發多個工具呼叫，所以結果要用 tool_use_id 對回去，
    # 不能用「最後一個步驟」—— 不然兩個平行結果會疊在同一張軌跡卡上。
    step_of: dict[str, int] = {}

    def _id(data, fallback):
        return data.get("tool_use_id") or fallback or ""

    async def on_pre_tool(data, tool_use_id, context):
        step["n"] += 1
        name = data["tool_name"].rsplit("__", 1)[-1]
        step_of[_id(data, tool_use_id)] = step["n"]
        if on_event:
            on_event(
                {
                    "type": "tool_call",
                    "step": step["n"],
                    "tool": name,
                    "args": data["tool_input"],
                    "source": module_source(name),
                }
            )
        return {}

    async def on_post_tool(data, tool_use_id, context):
        if on_event:
            on_event(
                {
                    "type": "tool_result",
                    "step": step_of.get(_id(data, tool_use_id), step["n"]),
                    "tool": data["tool_name"].rsplit("__", 1)[-1],
                    "summary": summarize(data.get("tool_response")),
                }
            )
        return {}

    allowed = [f"mcp__ragmod__{m}" for m in arch.modules if m in MODULES] + arch.builtin_tools

    return (
        ClaudeAgentOptions(
            tools=arch.builtin_tools,  # 只開架構明確要的內建工具，其餘全關
            mcp_servers={"ragmod": build_mcp_server(arch, ix)},
            strict_mcp_config=True,
            allowed_tools=allowed,
            setting_sources=[],
            system_prompt=arch.system_prompt(),
            max_turns=arch.max_turns,
            permission_mode="bypassPermissions",
            cwd=str(PROJECT_DIR),
            hooks={
                "PreToolUse": [HookMatcher(hooks=[on_pre_tool])],
                "PostToolUse": [HookMatcher(hooks=[on_post_tool])],
            },
        ),
        step,
    )


@dataclass
class Run:
    """一次執行的結果，方便在 notebook 裡比較不同架構。"""

    architecture: str
    question: str
    answer: str
    tool_calls: list[dict]
    reasoning: list[str]
    elapsed_s: float

    @property
    def n_calls(self) -> int:
        return len(self.tool_calls)

    @property
    def citations(self) -> list[str]:
        import re

        return sorted(set(re.findall(r"\[([^\[\]\s]+#\d+)\]", self.answer)))

    def trace(self) -> str:
        lines = [f"── {self.architecture} · {self.n_calls} 次呼叫 · {self.elapsed_s:.1f}s ──"]
        for c in self.tool_calls:
            args = json.dumps(c["args"], ensure_ascii=False)
            lines.append(f"  [{c['step']}] {c['tool']}({args[:100]})")
            if c.get("summary"):
                lines.append(f"       → {c['summary']}")
        return "\n".join(lines)


async def arun(arch: Architecture, question: str, ix: Index, verbose: bool = True) -> Run:
    """跑一個架構，回傳可比較的結果。notebook 裡直接 await。"""
    from claude_agent_sdk import AssistantMessage, ClaudeSDKClient, ResultMessage, TextBlock

    calls: list[dict] = []
    reasoning: list[str] = []

    def on_event(ev: dict) -> None:
        if ev["type"] == "tool_call":
            calls.append(ev)
            if verbose:
                args = json.dumps(ev["args"], ensure_ascii=False)
                print(f"  [{ev['step']}] {ev['tool']}({args[:110]})")
        elif ev["type"] == "tool_result":
            if calls:
                calls[-1]["summary"] = ev["summary"]
            if verbose:
                print(f"       → {ev['summary']}")

    options, _ = build_options(arch, ix, on_event)
    started = time.time()
    pending: str | None = None

    async with ClaudeSDKClient(options=options) as client:
        await client.query(question)
        async for msg in client.receive_response():
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock) and block.text.strip():
                        if pending:
                            reasoning.append(pending)
                            if verbose:
                                print(f"  · {pending[:150]}")
                        pending = block.text.strip()
            elif isinstance(msg, ResultMessage):
                break

    return Run(
        architecture=arch.name,
        question=question,
        answer=pending or "（沒有產生答案）",
        tool_calls=calls,
        reasoning=reasoning,
        elapsed_s=time.time() - started,
    )


def summarize(response: Any) -> str:
    """工具回傳 → 一行摘要。"""
    blocks = response.get("content") if isinstance(response, dict) else response
    payload = response
    if isinstance(blocks, list) and blocks and isinstance(blocks[0], dict):
        try:
            payload = json.loads(blocks[0].get("text", "{}"))
        except json.JSONDecodeError:
            return str(blocks[0].get("text", ""))[:160]
    if isinstance(payload, str):                 # WebSearch 回傳的是一段文字
        return f"網路結果 {len(payload)} 字"
    if not isinstance(payload, dict):
        return str(payload)[:160]
    if "error" in payload:
        return f"失敗：{payload['error']}"
    if "results" in payload:
        n = len(payload["results"])
        extra = "（降級 BM25）" if payload.get("degraded") else ""
        return f"{n} 筆{extra}"
    if "selected" in payload:
        return f"MMR 選出 {len(payload['selected'])} 筆"
    if "chunks" in payload:
        return f"取回 {len(payload['chunks'])} 塊完整內文"
    if "total_chunks" in payload:
        return f"{payload['total_chunks']} 片段 / {payload['total_files']} 檔案"
    return "完成"


def compare(runs: Sequence[Run]) -> str:
    """並排比較多個架構跑同一題的結果。"""
    rows = [("架構", "工具呼叫", "耗時", "出處數", "答案長度")]
    rows += [
        (r.architecture, str(r.n_calls), f"{r.elapsed_s:.1f}s", str(len(r.citations)), f"{len(r.answer)} 字")
        for r in runs
    ]
    widths = [max(len(str(row[i])) for row in rows) for i in range(len(rows[0]))]
    out = []
    for i, row in enumerate(rows):
        out.append("  ".join(str(c).ljust(w) for c, w in zip(row, widths)))
        if i == 0:
            out.append("  ".join("─" * w for w in widths))
    return "\n".join(out)
