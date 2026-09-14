"""FastAPI：把 agent 的決策軌跡即時串到瀏覽器。

    uv run uvicorn app:app --reload
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Body, FastAPI, HTTPException, UploadFile
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


# ══════════ 上傳 → agent 決定怎麼切 → 併進語料庫 ══════════

UPLOAD_DIR = CORPUS_DIR / "uploads"
ALLOWED_SUFFIX = {".md", ".txt", ".pdf"}
MAX_UPLOAD = 40 * 1024 * 1024


def _safe_name(name: str) -> str:
    """只取檔名本身，並把路徑分隔與控制字元擋掉。"""
    base = Path(name or "").name
    base = re.sub(r"[\x00-\x1f/\\]", "", base).strip() or "untitled"
    return base[:120]


@app.post("/api/upload")
async def upload(file: UploadFile) -> dict:
    """先把檔案收下來。真正的切塊與索引在 /api/ingest，因為那要串流進度。"""
    name = _safe_name(file.filename)
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED_SUFFIX:
        raise HTTPException(400, f"只收 {'、'.join(sorted(ALLOWED_SUFFIX))}，收到 {suffix or '沒有副檔名'}")

    raw = await file.read()
    if not raw:
        raise HTTPException(400, "檔案是空的")
    if len(raw) > MAX_UPLOAD:
        raise HTTPException(400, f"檔案太大（{len(raw) / 1e6:.1f} MB），上限 {MAX_UPLOAD // 10**6} MB")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target = UPLOAD_DIR / name
    target.write_bytes(raw)
    rel = f"uploads/{name}"
    return {"path": rel, "bytes": len(raw), "replaced": any(c.path == rel for c in INDEX.chunks)}


@app.get("/api/ingest")
async def ingest_doc(path: str) -> StreamingResponse:
    """讓 agent 看一眼文件、決定切塊策略，然後切、嵌入、併進索引。

    用 SSE 串流是為了讓學生看得到 agent 在判斷什麼 ——
    索引期的決策跟檢索期一樣值得攤開。
    """
    import ingest as ING

    target = (CORPUS_DIR / path).resolve()
    if CORPUS_DIR not in target.parents or not target.is_file():
        raise HTTPException(404, f"找不到 {path}")

    queue: asyncio.Queue = asyncio.Queue()

    def emit(event: dict) -> None:
        queue.put_nowait(event)

    async def worker() -> None:
        global INDEX
        try:
            result = await ING.ingest(
                target, path, HERE / "data", list(INDEX.chunks),
                os.getenv("EMBEDDING", "local"), emit,
            )
            # 重新載入，讓新片段立刻可以被檢索到
            INDEX = load_index(
                HERE / "data",
                embedding=os.getenv("EMBEDDING", "local"),
                model_name=os.getenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-small"),
            )
            emit({"type": "done", **result, "chunks": len(INDEX.chunks),
                  "files": len({c.path for c in INDEX.chunks})})
        except Exception as exc:  # noqa: BLE001
            emit({"type": "error", "text": f"{type(exc).__name__}: {exc}"})
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
        stream(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ══════════ 筆記本 ══════════
#
# 存在伺服器而不是瀏覽器 localStorage，因為這些筆記的用途是「之後變成教材」——
# 要能匯出、能進 git、能在別台機器打開。

NOTES_DIR = HERE / "notes"
NOTES_FILE = NOTES_DIR / "notes.json"
NOTES_IMG = NOTES_DIR / "images"


def _load_notes() -> list[dict]:
    if not NOTES_FILE.exists():
        return []
    try:
        return json.loads(NOTES_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def _save_notes(notes: list[dict]) -> None:
    NOTES_DIR.mkdir(exist_ok=True)
    NOTES_FILE.write_text(json.dumps(notes, ensure_ascii=False, indent=1), encoding="utf-8")


@app.get("/api/notes")
async def list_notes() -> list[dict]:
    return _load_notes()


@app.post("/api/notes")
async def add_note(note: dict = Body(...)) -> dict:
    """存一則問答。image 是錨定區域的截圖（dataURL），可有可無。"""
    if not (note.get("question") or "").strip() or not (note.get("answer") or "").strip():
        raise HTTPException(400, "問題與答案都不能是空的")

    nid = uuid.uuid4().hex[:10]
    image_file = ""
    data_url = note.get("image") or ""
    if data_url.startswith("data:image/png;base64,"):
        raw = base64.b64decode(data_url.split(",", 1)[1])
        if len(raw) > 4_000_000:
            raise HTTPException(400, "截圖太大")
        NOTES_IMG.mkdir(parents=True, exist_ok=True)
        image_file = f"images/{nid}.png"
        (NOTES_DIR / image_file).write_bytes(raw)

    entry = {
        "id": nid,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "question": note["question"].strip(),
        "answer": note["answer"].strip(),
        "anchor": (note.get("anchor") or "").strip(),
        "source": note.get("source") or "",
        "arch": note.get("arch") or "",
        "citations": note.get("citations") or [],
        "image": image_file,
    }
    notes = _load_notes()
    notes.insert(0, entry)          # 新的放最前面
    _save_notes(notes)
    return entry


@app.delete("/api/notes/{note_id}")
async def delete_note(note_id: str) -> dict:
    notes = _load_notes()
    keep = [n for n in notes if n["id"] != note_id]
    if len(keep) == len(notes):
        raise HTTPException(404, f"沒有這則筆記：{note_id}")
    gone = next(n for n in notes if n["id"] == note_id)
    if gone.get("image"):
        (NOTES_DIR / gone["image"]).unlink(missing_ok=True)
    _save_notes(keep)
    return {"deleted": note_id, "left": len(keep)}


@app.get("/api/notes/image/{note_id}")
async def note_image(note_id: str) -> FileResponse:
    """筆記的框選截圖。存成檔案而不是把 base64 塞在 notes.json 裡，
    是因為那個 JSON 之後還要給人讀、給 git 看 diff。"""
    note = next((n for n in _load_notes() if n["id"] == note_id), None)
    if not note or not note.get("image"):
        raise HTTPException(404, f"這則筆記沒有截圖：{note_id}")
    target = (NOTES_DIR / note["image"]).resolve()
    if NOTES_DIR.resolve() not in target.parents or not target.is_file():
        raise HTTPException(404, "截圖檔不見了")
    return FileResponse(target, media_type="image/png")


@app.get("/api/notes/export")
async def export_notes() -> Response:
    """匯出成 Markdown —— 這些筆記的終點是教材，所以要能直接貼。"""
    notes = _load_notes()
    lines = [
        "# Agentic RAG 筆記",
        "",
        f"共 {len(notes)} 則 · 匯出於 {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
    ]
    for i, n in enumerate(reversed(notes), 1):      # 匯出照時間正序比較好讀
        lines += [f"## {i}. {n['question']}", ""]
        meta = [n["created_at"]]
        if n["source"]:
            meta.append(n["source"])
        if n["arch"]:
            meta.append(n["arch"])
        lines += ["> " + " ｜ ".join(meta), ""]
        if n.get("image"):
            lines += [f"![錨定區域]({n['image']})", ""]
        if n["anchor"]:
            lines += ["**錨定內容**", ""]
            lines += ["> " + ln for ln in n["anchor"].splitlines()] + [""]
        lines += [n["answer"], "", "---", ""]

    md = "\n".join(lines)
    return Response(
        md,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="agentic-rag-notes.md"'},
    )


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
