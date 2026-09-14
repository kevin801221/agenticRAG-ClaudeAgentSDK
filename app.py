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
from fastapi.responses import FileResponse, Response, StreamingResponse

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


def _corpus_pdf(path: str) -> Path:
    """把使用者給的相對路徑解析成 corpus/ 底下的實體 PDF。

    只開放 corpus/ 底下的 .pdf —— resolve 之後比對父目錄，擋掉 ../ 這類路徑穿越。
    """
    if not path.lower().endswith(".pdf"):
        raise HTTPException(400, "只提供 PDF")
    target = (CORPUS_DIR / path).resolve()
    if CORPUS_DIR not in target.parents or not target.is_file():
        raise HTTPException(404, f"找不到 {path}")
    return target


@app.get("/api/pdf")
async def pdf(path: str) -> FileResponse:
    """原始 PDF 檔（給「在新分頁開啟」用）。"""
    return FileResponse(_corpus_pdf(path), media_type="application/pdf")


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


@app.get("/api/page")
async def page_image(path: str, page: int) -> Response:
    """把 PDF 的某一頁算成 PNG。

    為什麼不直接用瀏覽器內建的 PDF 檢視器：那是獨立的外掛程序，
    外面的網頁碰不到它的文字選取，做不了「圈選問 AI」。
    改成「頁面圖片 + 透明文字層」之後，選取就是原生的網頁選取。
    """
    target = _corpus_pdf(path)
    import pymupdf

    with pymupdf.open(target) as doc:
        if not 1 <= page <= doc.page_count:
            raise HTTPException(404, f"{path} 沒有第 {page} 頁（共 {doc.page_count} 頁）")
        png = doc[page - 1].get_pixmap(dpi=110).tobytes("png")
    return Response(png, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=3600"})


@app.get("/api/words")
async def page_words(path: str, page: int) -> dict:
    """那一頁每個詞的座標（PDF point 為單位）。前端拿它疊出可選取的文字層。"""
    target = _corpus_pdf(path)
    import pymupdf

    with pymupdf.open(target) as doc:
        if not 1 <= page <= doc.page_count:
            raise HTTPException(404, f"{path} 沒有第 {page} 頁")
        pg = doc[page - 1]
        words = [
            {"x": round(w[0], 1), "y": round(w[1], 1),
             "w": round(w[2] - w[0], 1), "h": round(w[3] - w[1], 1),
             "t": w[4], "line": w[6]}
            for w in pg.get_text("words")
        ]
        return {"page": page, "pages": doc.page_count,
                "width": round(pg.rect.width, 1), "height": round(pg.rect.height, 1),
                "words": words}


@app.get("/api/doc")
async def doc_text(path: str) -> dict:
    """非 PDF 的語料，把整份文字按片段回傳，前端一樣可以圈選。"""
    chunks = [c for c in INDEX.chunks if c.path == path]
    if not chunks:
        raise HTTPException(404, f"語料裡沒有 {path}")
    return {
        "path": path,
        "chunks": [{"chunk_id": c.id, "heading": c.heading, "text": c.text} for c in chunks],
    }


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
async def ask(q: str, arch: str = "modular", scope: str = "", selection: str = "") -> StreamingResponse:
    architecture = ARCHITECTURES.get(arch)
    if architecture is None:
        raise HTTPException(400, f"沒有這個架構：{arch}（可用：{list(ARCHITECTURES)}）")

    # 文件問答：把「現在開著哪份文件」「使用者圈選了什麼」放進問題本身。
    # 放進 prompt 而不是偷偷塞進 system，是為了讓學生在軌跡上看得到 agent 收到什麼。
    question = q
    if scope:
        head = f"【目前開啟】{scope}\n"
        if selection.strip():
            head += f"【使用者圈選】\n{selection.strip()[:2000]}\n"
        question = head + "\n" + q
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
            await RUN(question, INDEX, emit, architecture)
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
