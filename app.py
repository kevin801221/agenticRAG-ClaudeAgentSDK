"""FastAPI：把 agent 的決策軌跡即時串到瀏覽器。

    uv run uvicorn app:app --reload
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

load_dotenv()

from engines import check_config, describe_engine, get_engine  # noqa: E402
from modules import ARCHITECTURES, BUILTIN_TOOLS, MODULES  # noqa: E402
from retrieval import load_index  # noqa: E402

HERE = Path(__file__).resolve().parent
ENGINE = os.getenv("ENGINE", "agent_sdk")

check_config(ENGINE)
INDEX = load_index(
    HERE / "data",
    embedding=os.getenv("EMBEDDING", "local"),
    model_name=os.getenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-small"),
)
RUN = get_engine(ENGINE)

app = FastAPI(title="Agentic RAG 教學示範")


@app.get("/")
async def home() -> FileResponse:
    return FileResponse(HERE / "static" / "index.html")


@app.get("/api/health")
async def health() -> dict:
    return {
        "engine": ENGINE,
        "engine_label": describe_engine(ENGINE),
        "model": os.getenv("ANTHROPIC_MODEL") or os.getenv("LLM_MODEL") or "預設",
        "chunks": len(INDEX.chunks),
        "files": len({c.path for c in INDEX.chunks}),
        "has_vectors": INDEX.has_vectors,
        "vector_store": INDEX.store_kind,
        "built_at": INDEX.built_at,
    }


CORPUS_DIR = (HERE / "corpus").resolve()


@app.get("/api/chunk")
async def chunk(id: str) -> dict:
    c = INDEX.by_id.get(id)
    if c is None:
        raise HTTPException(404, f"沒有這個片段：{id}")
    return {
        "chunk_id": c.id,
        "path": c.path,
        "heading": c.heading,
        "text": c.text,
        "page": c.page,          # 只有 PDF 有；前端拿它跳到原文那一頁
        "is_pdf": c.path.lower().endswith(".pdf"),
    }


@app.get("/api/pdf")
async def pdf(path: str) -> FileResponse:
    """把語料裡的 PDF 交給瀏覽器內建的閱讀器顯示。

    只開放 corpus/ 底下的 .pdf —— resolve 之後再比對父目錄，擋掉 ../ 這類路徑穿越。
    """
    if not path.lower().endswith(".pdf"):
        raise HTTPException(400, "只提供 PDF")
    target = (CORPUS_DIR / path).resolve()
    if CORPUS_DIR not in target.parents or not target.is_file():
        raise HTTPException(404, f"找不到 {path}")
    return FileResponse(target, media_type="application/pdf")


STAGE_ORDER = ["Indexing", "Pre-retrieval", "Retrieval", "Post-retrieval"]


@app.get("/api/pipeline")
async def pipeline() -> list[dict]:
    """模組依 Modular RAG 階段分組。前端拿它畫流程圖的骨架。

    注意這裡回的是**全部**模組，不是某個架構的 —— 前端會把架構沒用到的畫成灰的，
    讓學生一眼看出「Naive RAG 整個 Post-retrieval 階段是空的」。
    """
    grouped: dict[str, list[dict]] = {s: [] for s in STAGE_ORDER}
    for name, mod in MODULES.items():
        grouped[mod["stage"]].append(
            {"name": name, "description": mod["description"].split("。")[0] + "。", "builtin": False}
        )
    # SDK 內建工具也要畫進去 —— 學生要看得出「哪些是我們寫的、哪些是 SDK 給的」
    for name, mod in BUILTIN_TOOLS.items():
        grouped[mod["stage"]].append(
            {"name": name, "description": mod["description"].split("。")[0] + "。", "builtin": True}
        )
    return [{"stage": s, "modules": grouped[s]} for s in STAGE_ORDER]


@app.get("/api/corpus")
async def corpus() -> list[dict]:
    """語料清單，給前端做瀏覽器用。

    不用先問問題就能直接翻論文 —— 只靠「答案引用到才點得開」對讀論文太不方便。
    """
    files: dict[str, dict] = {}
    for c in INDEX.chunks:
        f = files.setdefault(
            c.path, {"path": c.path, "chunks": 0, "pages": 0, "is_pdf": c.path.lower().endswith(".pdf")}
        )
        f["chunks"] += 1
        if c.page:
            f["pages"] = max(f["pages"], c.page)
    return sorted(files.values(), key=lambda f: (not f["is_pdf"], f["path"]))


@app.get("/api/architectures")
async def architectures() -> list[dict]:
    """七個現成架構。前端做成選單，學生可以當場切換比較軌跡。"""
    return [
        {
            "key": key,
            "name": a.name,
            "paper": a.paper,
            "orchestration": a.orchestration,
            "modules": a.modules,
            "builtin_tools": a.builtin_tools,
            "policy": a.policy.strip(),
        }
        for key, a in ARCHITECTURES.items()
    ]


@app.get("/api/ask")
async def ask(q: str, arch: str = "modular") -> StreamingResponse:
    architecture = ARCHITECTURES.get(arch)
    if architecture is None:
        raise HTTPException(400, f"沒有這個架構：{arch}（可用：{list(ARCHITECTURES)}）")
    queue: asyncio.Queue = asyncio.Queue()

    def emit(event: dict) -> None:
        queue.put_nowait(event)

    async def worker() -> None:
        try:
            if not INDEX.has_vectors:
                emit({"type": "status", "text": "向量不可用，這場問答全程走純 BM25（降級模式）"})
            emit({
                "type": "status",
                "text": f"架構：{architecture.name}｜編排：{architecture.orchestration}｜"
                        f"模組：{', '.join(architecture.modules + architecture.builtin_tools)}",
            })
            await RUN(q, INDEX, emit, architecture)
        except Exception as exc:  # noqa: BLE001 — 錯誤要送到前端，不能只寫在 log
            emit({"type": "error", "text": f"{type(exc).__name__}: {exc}", "fatal": True})
        finally:
            queue.put_nowait(None)

    asyncio.create_task(worker())

    async def stream():
        while True:
            event = await queue.get()
            if event is None:
                return
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
