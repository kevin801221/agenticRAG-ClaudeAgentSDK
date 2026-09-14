"""軌跡存檔與重播。

上課現場問一題要等 30–90 秒。那段時間你只能尬聊，而且每次跑出來的軌跡都不一樣，
講稿對不上；額度用完或教室沒網路就整堂課停擺。

所以把每次執行的完整事件流存下來，之後不呼叫 LLM 就能重播：
挑一次最漂亮的存著，每次上課都放那個。

重播用的是**同一組事件**，所以前端不需要第二套渲染邏輯 —— 把事件餵回原本的
handle() 就好。這也保證你重播看到的跟當初真的跑出來的一模一樣。
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

TRACE_DIR = Path(__file__).resolve().parent / "traces"
KEEP_UNPINNED = 50          # 釘選的不算在內


class Recorder:
    """把一次執行的事件流錄下來，附上相對時間。"""

    def __init__(self, mode: str, question: str, archs: list[str]):
        self.mode = mode
        self.question = question
        self.archs = archs
        self.t0 = time.monotonic()
        self.events: list[dict] = []

    def add(self, event: dict) -> None:
        # 存相對毫秒而不是絕對時間 —— 重播時才好按原節奏播，也不會洩漏什麼時候跑的
        self.events.append({**event, "t": int((time.monotonic() - self.t0) * 1000)})

    def save(self) -> dict | None:
        if not self.events:
            return None
        TRACE_DIR.mkdir(exist_ok=True)
        tid = time.strftime("%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]

        answers = [e for e in self.events if e.get("type") == "answer"]
        calls = sum(1 for e in self.events if e.get("type") == "tool_call")
        meta = {
            "id": tid,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "mode": self.mode,
            "question": self.question[:300],
            "archs": self.archs,
            "calls": calls,
            "ms": self.events[-1]["t"],
            "preview": (answers[0]["text"][:160] if answers else ""),
            "pinned": False,
        }
        (TRACE_DIR / f"{tid}.json").write_text(
            json.dumps({**meta, "events": self.events}, ensure_ascii=False), encoding="utf-8"
        )
        prune()
        return meta


def _read(f: Path) -> dict | None:
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def listing() -> list[dict]:
    """只回中繼資料，不回事件 —— 清單不需要把幾百個事件也送過去。"""
    out = []
    if not TRACE_DIR.is_dir():
        return out
    for f in TRACE_DIR.glob("*.json"):
        d = _read(f)
        if d:
            out.append({k: v for k, v in d.items() if k != "events"})
    return sorted(out, key=lambda d: d["id"], reverse=True)


def load(tid: str) -> dict | None:
    f = TRACE_DIR / f"{_safe(tid)}.json"
    return _read(f) if f.is_file() else None


def pin(tid: str, value: bool) -> bool:
    """釘選的不會被自動清掉 —— 上課要用的那幾份要保得住。"""
    f = TRACE_DIR / f"{_safe(tid)}.json"
    d = _read(f) if f.is_file() else None
    if not d:
        return False
    d["pinned"] = value
    f.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return True


def delete(tid: str) -> bool:
    f = TRACE_DIR / f"{_safe(tid)}.json"
    if not f.is_file():
        return False
    f.unlink()
    return True


def prune() -> int:
    """只留最近 N 筆未釘選的。每次問答都錄，不清會無限長大。"""
    items = [d for d in listing() if not d.get("pinned")]
    gone = 0
    for d in items[KEEP_UNPINNED:]:
        if delete(d["id"]):
            gone += 1
    return gone


def _safe(tid: str) -> str:
    """id 是我們自己產的，但它會從網址進來，還是擋一下路徑穿越。"""
    return "".join(c for c in tid if c.isalnum() or c == "-")[:40]
