"""上傳文件 → 讓 agent 決定怎麼切、拿什麼去向量化 → 併進語料庫。

這支補上了「索引期也可以是 agentic 的」這一塊。

前面幾個架構（CRAG、Self-RAG…）都在**檢索期**做決定：查什麼、要不要重查。
但切塊策略其實同樣重要而且更難一次做對 —— 論文按頁切、逐字稿按講者切、
API 文件按 heading 切，用同一套規則去切全部，檢索品質就會被切法拖累。

所以這裡讓 agent 看一眼文件，自己決定：

    切法（heading / page / paragraph）、每塊多大、要不要為每塊加脈絡

**唯一不讓 agent 決定的是 embedding 模型** —— 同一個索引裡的向量必須在同一個
向量空間，混用等於全毀。可以交給 agent 的是「把什麼文字拿去嵌入」，
那才是真正影響命中率的部分。
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

import numpy as np

import index_corpus as IC
from retrieval import (
    Chunk,
    DEFAULT_EMBEDDING_MODEL,
    embed_text,
    load_encoder,
    save_index,
)

Emit = Callable[[dict], None]

PLAN_PROMPT = """你要決定一份文件該怎麼切塊，才能在 RAG 系統裡被準確檢索到。

## 文件資訊

- 檔名：{name}
- 格式：{fmt}
- 長度：約 {chars} 字元{pages}

## 內容樣本

開頭：
```
{head}
```

中段：
```
{mid}
```

## 你要輸出什麼

只輸出一個 JSON code block，不要有其他文字：

```json
{{
  "doc_type": "這是什麼類型的文件（學術論文 / API 文件 / 教學文章 / 逐字稿 / 規格書 / 其他）",
  "strategy": "heading | page | paragraph",
  "max_chars": 1200,
  "min_chars": 100,
  "context_prefix": true,
  "reason": "一到兩句話說明你為什麼這樣切"
}}
```

## 判斷依據

**strategy**
- `heading` — 文件有清楚的標題階層（markdown、技術文件）。一個小節通常就是一個完整概念，這是最好的邊界。
- `page` — PDF 且版面是排出來的（論文、投影片、掃描件）。沒有可靠的語意標記，頁是唯一穩定的邊界，而且頁碼讓引用能翻回原文。
- `paragraph` — 沒有標題也沒有頁的長文（逐字稿、純文字），只能按空行切再打包。

**max_chars**：資訊密度高的（論文、規格）切小一點（800–1000），敘事性的可以大一點（1200–1600）。
太小會切斷語意，太大會讓不相關的內容一起被檢索出來。

**context_prefix**：要不要為每一塊多寫一句「這塊在整份文件的哪個位置、在講什麼」，
再拿那句話跟內文一起去做向量化。
- 設 `true`：片段脫離上下文就看不懂時（論文的中段、只有代名詞沒有主詞的段落）。
- 設 `false`：每塊本身就完整時（FAQ、獨立條目）。設 true 會多花 LLM 呼叫。
"""

CONTEXT_PROMPT = """這些片段來自同一份文件：{name}（{doc_type}）。

文件在講什麼：
{summary}

請為每個片段寫**一句話**說明「它在整份文件的哪個位置、在講什麼」，
讓這個片段脫離上下文也看得懂。這句話會跟內文一起被向量化，用來提升檢索命中率。

規則：
- 一句話，不超過 40 字
- 寫這個片段的**定位與主題**，不要複述內容
- 好：「這段屬於方法章節，說明評估器怎麼給檢索結果打分」
- 壞：「這段說評估器會打分數然後分成三類」（那是複述）

只輸出一個 JSON code block：

```json
{{"1": "第一段的脈絡句", "2": "第二段的脈絡句"}}
```

片段：

{chunks}
"""


def _json_block(text: str) -> dict:
    """從模型回覆裡挖出 JSON。它有時會多寫一兩句話，不要因此整個失敗。"""
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    raw = m.group(1) if m else text[text.find("{") : text.rfind("}") + 1]
    return json.loads(raw)


async def _ask(prompt: str) -> str:
    """問一次，不給任何工具 —— 這裡只要模型的判斷，不需要它去查東西。"""
    from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, TextBlock, query

    out = []
    async for msg in query(
        prompt=prompt,
        options=ClaudeAgentOptions(tools=[], setting_sources=[], max_turns=1),
    ):
        if isinstance(msg, AssistantMessage):
            out += [b.text for b in msg.content if isinstance(b, TextBlock)]
    return "\n".join(out)


def _sample(path: Path) -> tuple[str, str, int, str]:
    """取開頭與中段當樣本。只看開頭會誤判 —— 論文的第一頁長得像任何東西。"""
    if path.suffix.lower() == ".pdf":
        import pymupdf

        with pymupdf.open(path) as doc:
            pages = doc.page_count
            head = IC._clean_pdf_text(doc[0].get_text())
            mid = IC._clean_pdf_text(doc[pages // 2].get_text()) if pages > 1 else ""
            total = sum(len(p.get_text()) for p in doc)
        return head[:2500], mid[:1500], total, f"，{pages} 頁"
    text = path.read_text(encoding="utf-8", errors="replace")
    half = len(text) // 2
    return text[:2500], text[half : half + 1500], len(text), ""


DEFAULT_PLAN = {
    "doc_type": "未判定",
    "strategy": "heading",
    "max_chars": 1200,
    "min_chars": 100,
    "context_prefix": False,
    "reason": "agent 判斷失敗，用預設切法",
}


async def make_plan(path: Path, emit: Emit) -> dict:
    head, mid, chars, pages = _sample(path)
    emit({"type": "step", "text": f"讀樣本：開頭 {len(head)} 字、中段 {len(mid)} 字"})

    prompt = PLAN_PROMPT.format(
        name=path.name,
        fmt=path.suffix.lstrip(".").upper() or "TXT",
        chars=f"{chars:,}",
        pages=pages,
        head=head,
        mid=mid or "（文件太短，沒有中段）",
    )
    emit({"type": "step", "text": "請 agent 判斷切塊策略…"})
    try:
        plan = {**DEFAULT_PLAN, **_json_block(await _ask(prompt))}
    except Exception as exc:  # noqa: BLE001
        emit({"type": "step", "text": f"判斷失敗（{exc}），改用預設切法"})
        plan = dict(DEFAULT_PLAN)

    if path.suffix.lower() == ".pdf" and plan["strategy"] == "heading":
        plan["strategy"] = "page"          # PDF 沒有可靠的 heading，別讓它自己走進死路
        plan["reason"] += "（PDF 無可靠 heading，改用頁切）"
    emit({"type": "plan", "plan": plan})
    return plan


def apply_plan(path: Path, rel: str, plan: dict) -> list[Chunk]:
    """照 plan 切塊。切法是資料，執行是程式 —— 跟 Architecture 同一個心法。"""
    old_max, old_min = IC.MAX_CHARS, IC.MIN_CHARS
    IC.MAX_CHARS = int(plan.get("max_chars") or old_max)
    IC.MIN_CHARS = int(plan.get("min_chars") or old_min)
    try:
        if plan["strategy"] == "page":
            return IC.chunk_pdf(path, rel)
        text = path.read_text(encoding="utf-8", errors="replace")
        if plan["strategy"] == "paragraph":
            parts = IC._split_long(re.sub(r"\n{3,}", "\n\n", text).strip())
            chunks = [
                Chunk(id=f"{rel}#{i}", path=rel, heading=f"{Path(rel).stem} ({i + 1})", text=t)
                for i, t in enumerate(parts)
            ]
            IC._link(chunks)
            return chunks
        return IC.chunk_markdown(text, rel)
    finally:
        IC.MAX_CHARS, IC.MIN_CHARS = old_max, old_min


async def add_context(chunks: list[Chunk], rel: str, plan: dict, emit: Emit) -> None:
    """為每塊加一句脈絡（Contextual Retrieval）。只影響拿去嵌入的文字，不動顯示的內容。"""
    summary = f"{plan.get('doc_type', '')}。{plan.get('reason', '')}"
    batch = 15
    for start in range(0, len(chunks), batch):
        part = chunks[start : start + batch]
        listing = "\n\n".join(
            f"[{i + 1}] （{c.heading}）\n{c.text[:600]}" for i, c in enumerate(part)
        )
        emit({
            "type": "step",
            "text": f"為片段補脈絡 {start + 1}–{start + len(part)} / {len(chunks)}",
        })
        try:
            got = _json_block(
                await _ask(CONTEXT_PROMPT.format(
                    name=rel, doc_type=plan.get("doc_type", ""), summary=summary, chunks=listing
                ))
            )
            for i, c in enumerate(part):
                c.context = str(got.get(str(i + 1), "")).strip()[:200]
        except Exception as exc:  # noqa: BLE001
            emit({"type": "step", "text": f"這批補脈絡失敗，略過（{exc}）"})


async def ingest(path: Path, rel: str, data_dir: Path, existing: list[Chunk],
                 embedding: str, emit: Emit) -> dict:
    """完整流程：規劃 → 切塊 → 補脈絡 → 向量化 → 併進語料庫。"""
    from datetime import datetime

    plan = await make_plan(path, emit)

    chunks = apply_plan(path, rel, plan)
    emit({"type": "step", "text": f"切出 {len(chunks)} 個片段（{plan['strategy']}）"})
    if not chunks:
        raise ValueError("切不出任何片段 —— 檔案可能是空的或掃描件（沒有文字層）")

    if plan.get("context_prefix"):
        await add_context(chunks, rel, plan, emit)

    merged = [c for c in existing if c.path != rel] + chunks   # 同名就覆蓋
    vectors = None
    if embedding == "local":
        emit({"type": "step", "text": f"向量化 {len(merged)} 個片段…"})
        encode = load_encoder(DEFAULT_EMBEDDING_MODEL)
        vectors = np.asarray(encode([embed_text(c) for c in merged]), dtype="float32")

    save_index(data_dir, merged, vectors, datetime.now().isoformat(timespec="seconds"))
    emit({"type": "step", "text": "索引已更新"})
    return {"plan": plan, "added": len(chunks), "total": len(merged)}
