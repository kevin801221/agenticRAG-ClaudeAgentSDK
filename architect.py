"""架構師：透過對話問出你的使用情境，然後產出一份 Architecture。

這是 Adaptive-RAG 的「選型」升一層 ——
Adaptive 是替**一個問題**選路線，架構師是替**一個使用情境**選架構。

能做得這麼小，是因為 `Architecture` 本來就是資料（模組清單 + policy 字串）。
架構師不需要「生成程式碼」，它只要吐出一份 JSON。

產出的架構可以立刻用並排比較驗證 —— 建議與驗證在同一個畫面完成。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from modules import BUILTIN_TOOLS, MODULES, Architecture

CUSTOM_DIR = Path(__file__).resolve().parent / "architectures"

SYSTEM = """你是 RAG 架構顧問。你的工作是問出對方的使用情境，然後設計一份適合的檢索架構。

## 你可以用的模組（只能用這些）

{modules}

SDK 內建工具（選用）：{builtin}

## 可用的編排型態

- **Linear** 固定順序跑完
- **Conditional** 依判斷結果走不同分支
- **Branching** 同時展開多路再合併
- **Looping** 生成 → 批判 → 再檢索

## 怎麼進行

**一次只問一個問題。最多問五個。** 每個問題要附一句「為什麼要問這個」——
對方多半不知道這件事會影響架構，你要讓他知道。

該問到的東西（依重要性）：

1. **答錯的代價** —— 內部工具答錯沒人死，對客戶講錯數字會出事。這決定要不要自我修正。
2. **問題型態** —— 單一事實 / 需要比較綜合 / 多跳推理 / 開放式。這決定要不要分解與多輪。
3. **使用者怎麼問** —— 用內部術語，還是用自己的話？決定要不要前置改寫或 HyDE。
4. **延遲與成本能忍多少** —— 願意等 60 秒還是要 3 秒內？決定迴圈上限與要不要路由。
5. **知識庫沒有答案時該怎麼辦** —— 老實說沒有 / 上網查 / 可以用模型的背景知識？

已經知道的不要再問。對方講得夠清楚就直接進入產出。

## 產出

蒐集夠了就輸出 **一段說明 + 一個 JSON code block**，格式如下：

```json
{{
  "name": "給這個架構的名字（繁中，會顯示在選單上）",
  "orchestration": "Linear | Conditional | Branching | Looping（可加括號說明）",
  "modules": ["search", "grade_documents"],
  "builtin_tools": [],
  "max_turns": 12,
  "policy": "給執行 agent 的編排規則，用繁體中文寫，要具體到它照著做就能跑。",
  "why": "兩三句話說明你為什麼這樣設計，對應到對方講的哪些條件。"
}}
```

**policy 是這份架構的靈魂**，要寫得像流程說明而不是形容詞：

- 壞：「謹慎地檢索並確保答案正確」
- 好：「先用 search 查一次。用 grade_documents 讀完整內文逐塊給 0-2 分。
  多數低於 1 分就改寫 query 再查一輪，兩輪都不行就明講知識庫沒有，不要用背景知識補。」

policy 裡要包含：什麼時候用哪個模組、判斷條件是什麼、失敗了怎麼辦、答案要怎麼標出處。

**出處格式一定要寫死成 `[片段id]`**，例如 `[02-permissions.md#0]`。
這不是風格問題 —— 前端靠這個格式把出處變成可以點開原文的按鈕，
自己發明成 `[來源: 檔名 / 章節]` 就點不動了，使用者也就查不了證。

## 兩條硬規則

**不要發明不存在的模組。** 只能用上面列出的那些。
**不要為了看起來厲害就堆模組。** 對方只需要查一次就好，就給他 Naive ——
多一個模組就多一份延遲與成本，那是真金白銀。
"""


def system_prompt() -> str:
    mods = "\n".join(
        f"- `{n}`（{m['stage']}）{m['description'].split('。')[0]}。" for n, m in MODULES.items()
    )
    return SYSTEM.format(modules=mods, builtin="、".join(f"`{b}`" for b in BUILTIN_TOOLS) or "無")


def _json_block(text: str) -> dict | None:
    for m in re.finditer(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S):
        try:
            got = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        if "modules" in got and "policy" in got:
            return got
    return None


async def turn(history: list[dict]) -> dict:
    """跑一輪對話。

    history 是完整的對話紀錄，每次都整份送回去 —— 無狀態。
    這樣做不只實作簡單，也讓學生看得到 agent 每一輪收到什麼，
    藏在 server session 裡就又變成黑盒子了。
    """
    from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, TextBlock, query

    convo = "\n\n".join(
        f"{'使用者' if m['role'] == 'user' else '你'}：{m['text']}" for m in history
    )
    prompt = f"{convo}\n\n（接著回應。如果資訊夠了就直接產出架構。）"

    out = []
    async for msg in query(
        prompt=prompt,
        options=ClaudeAgentOptions(
            tools=[], setting_sources=[], system_prompt=system_prompt(), max_turns=1
        ),
    ):
        if isinstance(msg, AssistantMessage):
            out += [b.text for b in msg.content if isinstance(b, TextBlock)]

    reply = "\n".join(out).strip()
    return {"reply": reply, "architecture": _json_block(reply)}


POLICY_SYSTEM = """你是 RAG 架構顧問。使用者已經自己選好要用哪些模組，你只要寫 policy。

## 他選的模組

{picked}

## 為什麼只寫 policy

模組決定「有什麼能力」，policy 決定「什麼時候用、怎麼判斷、失敗了怎麼辦」。
同一組模組配不同 policy 會是完全不同的架構 —— 所以 policy 才是這份架構的本體。

## 怎麼寫

寫得像流程說明，不要寫形容詞：

- 壞：「謹慎地檢索並確保答案正確」
- 好：「先用 search 查一次。用 grade_documents 讀完整內文逐塊給 0-2 分。
  多數低於 1 分就改寫 query 再查一輪，兩輪都不行就明講知識庫沒有，不要用背景知識補。」

要包含：什麼時候用哪個模組、判斷條件、失敗了怎麼辦、答案要怎麼標出處。

**出處格式一定要寫死成 `[片段id]`**，例如 `[02-permissions.md#0]` ——
前端靠這個格式把出處變成可以點開原文的按鈕，自己發明成 `[來源: 檔名 / 章節]` 就點不動了。
**只能用上面列出的模組**，一個都不能多。每一個都要在 policy 裡出現 ——
如果某個模組你想不到什麼時候該用，那就直接說它不該被選進來。

## 輸出

只輸出一個 JSON code block，不要別的：

```json
{{
  "policy": "……",
  "orchestration": "Linear | Conditional | Branching | Looping（可加括號說明）",
  "why": "兩三句話說明這樣編排的理由，以及這組模組有沒有哪裡怪怪的。"
}}
```
"""


async def write_policy(modules: list[str], builtin: list[str], note: str = "") -> dict:
    """使用者拖完模組，agent 補上 policy。

    這是拖拉式組裝的關鍵一步 —— 拖拉只給你「有哪些模組」，
    真正決定行為的是 policy。少了這一步，拖出來的每個架構跑起來都一樣。
    """
    from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, TextBlock, query

    known = {**MODULES, **BUILTIN_TOOLS}
    picked = "\n".join(
        f"- `{n}`（{known[n]['stage']}）{known[n]['description'].split('。')[0]}。"
        for n in modules + builtin if n in known
    ) or "（沒選任何模組）"

    prompt = (note.strip() or "照這組模組寫一份 policy。") + "\n\n（只輸出 JSON code block。）"
    out = []
    async for msg in query(
        prompt=prompt,
        options=ClaudeAgentOptions(
            tools=[], setting_sources=[],
            system_prompt=POLICY_SYSTEM.format(picked=picked), max_turns=1,
        ),
    ):
        if isinstance(msg, AssistantMessage):
            out += [b.text for b in msg.content if isinstance(b, TextBlock)]

    reply = "\n".join(out).strip()
    for m in re.finditer(r"```(?:json)?\s*(\{.*?\})\s*```", reply, re.S):
        try:
            got = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        if "policy" in got:
            return got
    return {"policy": reply, "orchestration": "", "why": ""}


GRAPH_SYSTEM = """你的工作是把一段 RAG 編排規則（policy）**讀成一張流程圖**。

policy 才是真正被執行的東西，圖只是它的視覺化 —— 所以你不可以自己發明流程，
只能把 policy 裡已經寫的東西畫出來。policy 沒講的分支就不要畫。

## 可以用的節點

- `__start__` 問題進來（一定有，而且只有一個）
- `__answer__` 產生答案（一定有，而且只有一個）
- 以下模組（只能用這些，一個都不能多）：
{picked}

## 輸出

只輸出一個 JSON code block：

```json
{{
  "edges": [
    {{"from": "__start__", "to": "search", "label": ""}},
    {{"from": "search", "to": "grade_documents", "label": ""}},
    {{"from": "grade_documents", "to": "__answer__", "label": "有夠好的片段"}},
    {{"from": "grade_documents", "to": "search", "label": "多數不合格，最多重來兩輪"}}
  ]
}}
```

規則：

- `label` 寫**判斷條件**，照 policy 的原文寫，不要自己換句話說。無條件的邊留空字串。
- 同一個節點有多條出邊時，每一條都要有 label —— 沒有條件的分支等於沒說清楚。
- policy 裡如果有「不合格就重查」這種回頭的描述，就畫一條指回去的邊（折返）。
- 每個模組都要至少出現一次。如果某個模組在 policy 裡根本沒被提到，
  還是把它畫成從 `__start__` 進不去的孤立節點 —— 那是 policy 的問題，不要幫它補。
"""


async def graph_from_policy(policy: str, modules: list[str], builtin: list[str],
                            mcp: list[str]) -> dict:
    """policy -> 圖。

    這是 Studio 那條「圖編譯成 policy」的反方向。會需要它，是因為十四個現成架構
    都是先有 policy 才有圖 —— 載進畫布時如果不接線，使用者只會看到一堆散落的方塊，
    以為東西壞了。自己猜一條直線又是假的，所以交給模型去讀那段 policy。
    """
    from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, TextBlock, query

    known = {**MODULES, **BUILTIN_TOOLS}
    names = list(modules) + list(builtin) + list(mcp)
    picked = "\n".join(
        f"- `{n}`" + (f"（{known[n]['stage']}）{known[n]['description'].split('。')[0]}。"
                      if n in known else "（外部 MCP 工具）")
        for n in names
    ) or "（沒有模組）"

    out = []
    async for msg in query(
        prompt=f"這是 policy：\n\n{policy.strip()}\n\n（把它畫成圖，只輸出 JSON code block。）",
        options=ClaudeAgentOptions(
            tools=[], setting_sources=[], max_turns=1,
            system_prompt=GRAPH_SYSTEM.format(picked=picked),
        ),
    ):
        if isinstance(msg, AssistantMessage):
            out += [b.text for b in msg.content if isinstance(b, TextBlock)]

    reply = "\n".join(out).strip()
    ok = set(names) | {"__start__", "__answer__"}
    for m in re.finditer(r"```(?:json)?\s*(\{.*?\})\s*```", reply, re.S):
        try:
            got = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        edges = [
            {"from": e["from"], "to": e["to"], "label": str(e.get("label") or "")}
            for e in (got.get("edges") or [])
            if isinstance(e, dict) and e.get("from") in ok and e.get("to") in ok
        ]
        if edges:
            return {"edges": edges}
    return {"edges": []}


def validate(spec: dict) -> tuple[bool, str]:
    """存之前檢查一遍 —— agent 有時會發明不存在的模組。"""
    if not str(spec.get("name", "")).strip():
        return False, "沒有名字"
    if not str(spec.get("policy", "")).strip():
        return False, "沒有 policy，那等於沒有編排"
    mods = spec.get("modules") or []
    if not isinstance(mods, list) or not mods:
        return False, "modules 是空的"
    unknown = [m for m in mods if m not in MODULES]
    if unknown:
        return False, f"用了不存在的模組：{unknown}"
    bad = [b for b in (spec.get("builtin_tools") or []) if b not in BUILTIN_TOOLS]
    if bad:
        return False, f"用了未登記的內建工具：{bad}"
    # MCP 工具要真的連得上才准存 —— 存一個連不上的架構，學生會以為是自己弄壞的
    import mcp_registry

    live = {t["name"] for t in mcp_registry.all_tools()}
    ghost = [t for t in (spec.get("mcp_tools") or []) if t not in live]
    if ghost:
        return False, f"這些 MCP 工具現在連不上：{ghost}"
    return True, ""


def to_architecture(spec: dict) -> Architecture:
    return Architecture(
        name=spec["name"].strip(),
        paper=spec.get("why", "由架構師依使用情境設計").strip()[:300],
        orchestration=str(spec.get("orchestration") or "Adaptive").strip(),
        modules=list(spec["modules"]),
        policy=spec["policy"].strip(),
        builtin_tools=list(spec.get("builtin_tools") or []),
        mcp_tools=list(spec.get("mcp_tools") or []),
        max_turns=int(spec.get("max_turns") or 12),
    )


def slug(name: str) -> str:
    """從名字做出檔名。

    只留 ASCII 會把全中文的名字洗成空字串（第一版就踩到了），
    所以中文字也留著 —— 檔名帶中文在 macOS / Linux 都沒問題，而且好認。
    真的一個字都留不下來才退回雜湊。
    """
    import hashlib

    base = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "-", name).strip("-")[:32]
    return "custom_" + (base or hashlib.sha1(name.encode()).hexdigest()[:8])


def save(spec: dict) -> str:
    """存成 JSON。存檔案而不是記憶體，重開才還在 —— 而且可以進 git 分享。"""
    CUSTOM_DIR.mkdir(exist_ok=True)
    key = slug(spec["name"])
    f = CUSTOM_DIR / f"{key}.json"
    # 同名但內容不同就加序號，不要默默蓋掉別人存的
    n = 2
    while f.is_file() and json.loads(f.read_text(encoding="utf-8")).get("policy") != spec.get("policy"):
        key = f"{slug(spec['name'])}-{n}"
        f = CUSTOM_DIR / f"{key}.json"
        n += 1
    f.write_text(json.dumps(spec, ensure_ascii=False, indent=1), encoding="utf-8")
    if spec.get("graph"):
        GRAPHS[key] = spec["graph"]
    return key


# 畫布上的節點座標與連線。它不是 Architecture 的一部分 —— Architecture 只有
# 模組清單和 policy，圖純粹是給人看的草稿。所以分開放，不要污染那個 dataclass。
GRAPHS: dict[str, dict] = {}


def load_all() -> dict[str, Architecture]:
    """載入所有自訂架構。壞掉的跳過，不要讓一個爛檔案擋住整個啟動。"""
    out: dict[str, Architecture] = {}
    if not CUSTOM_DIR.is_dir():
        return out
    for f in sorted(CUSTOM_DIR.glob("*.json")):
        try:
            spec = json.loads(f.read_text(encoding="utf-8"))
            ok, why = validate(spec)
            if not ok:
                print(f"[warn] 跳過 {f.name}：{why}")
                continue
            out[f.stem] = to_architecture(spec)
            if spec.get("graph"):
                GRAPHS[f.stem] = spec["graph"]
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] 跳過 {f.name}：{exc}")
    return out


def delete(key: str) -> bool:
    f = CUSTOM_DIR / f"{key}.json"
    if not f.is_file():
        return False
    f.unlink()
    return True
