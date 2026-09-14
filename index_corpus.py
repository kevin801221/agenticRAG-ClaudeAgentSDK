"""把教材 .md 切塊建索引。

切塊用 markdown 的 heading 當天然邊界，因為技術文件的一個小節通常就是一個
完整概念 —— 比固定長度切法漂亮太多，而且 heading 路徑本身就是很好的檢索訊號。

    uv run python index_corpus.py                 # 掃內附的 corpus/
    uv run python index_corpus.py --root ~/docs   # 換成你自己的資料夾
    uv run python index_corpus.py --no-vectors    # 只建 BM25，不下載模型

corpus/ 裡是一份自給自足的 Claude Code 參考文件，讓你 clone 下來就能跑。
要換成自己的知識庫，用 --root 指過去就好 —— 只要裡面是 .md 就行。
"""

from __future__ import annotations

import argparse
import os
import re
import time
from datetime import datetime
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

from retrieval import Chunk, load_encoder, save_index

MAX_CHARS = 1200  # 超過就拆
MIN_CHARS = 100  # 不到就併進下一塊
HEADING_RE = re.compile(r"^(#{1,4})\s+(.+?)\s*$")

# 預設掃 --root 底下所有 .md。換成自己的知識庫不用改這裡，用 --root 指過去即可。
INCLUDE_GLOBS = ["**/*.md"]
EXCLUDE_PARTS = {".git", "node_modules", ".venv", "__pycache__", "data", ".claude",
                 ".ipynb_checkpoints", "site-packages"}


# ── 切塊 ──────────────────────────────────────────────────


def chunk_markdown(text: str, path: str) -> list[Chunk]:
    sections = _merge_short(_split_by_heading(text, fallback=path))

    pieces: list[tuple[str, str]] = []
    for heading, body in sections:
        parts = _split_long(body)
        if len(parts) == 1:
            pieces.append((heading, parts[0]))
        else:
            pieces.extend(
                (f"{heading} (part {n})", part) for n, part in enumerate(parts, 1)
            )

    chunks = [
        Chunk(id=f"{path}#{i}", path=path, heading=heading, text=body)
        for i, (heading, body) in enumerate(pieces)
    ]
    for i, c in enumerate(chunks):
        c.prev_id = chunks[i - 1].id if i else None
        c.next_id = chunks[i + 1].id if i + 1 < len(chunks) else None
    return chunks


def _split_by_heading(text: str, fallback: str) -> list[tuple[str, str]]:
    """依 heading 切段，每段帶著完整的 heading 路徑。"""
    sections: list[tuple[str, str]] = []
    stack: list[tuple[int, str]] = []  # (level, title)
    heading = fallback
    buf: list[str] = []
    in_fence = False

    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        m = None if in_fence else HEADING_RE.match(line)
        if not m:
            buf.append(line)
            continue

        body = "\n".join(buf).strip()
        if body:
            sections.append((heading, body))
        buf = []

        level, title = len(m.group(1)), m.group(2).strip()
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        heading = " > ".join(t for _, t in stack)

    body = "\n".join(buf).strip()
    if body:
        sections.append((heading, body))
    return sections


def _merge_short(sections: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """太短的段落自己站不住，併進下一段（最後一段則併回前一段）。"""
    out: list[tuple[str, str]] = []
    carry: list[str] = []

    for heading, body in sections:
        if len(body) < MIN_CHARS:
            carry.append(body)
            continue
        if carry:
            body = "\n\n".join([*carry, body])
            carry = []
        out.append((heading, body))

    if carry:
        merged = "\n\n".join(carry)
        if out:
            out[-1] = (out[-1][0], f"{out[-1][1]}\n\n{merged}")
        else:
            out.append((sections[-1][0], merged))
    return out


def _split_long(body: str) -> list[str]:
    """太長的段落依空行貪婪打包，單一段落本身就超長就硬切。"""
    if len(body) <= MAX_CHARS:
        return [body]

    packed: list[str] = []
    cur = ""
    for para in re.split(r"\n\s*\n", body):
        if cur and len(cur) + len(para) + 2 > MAX_CHARS:
            packed.append(cur)
            cur = para
        else:
            cur = f"{cur}\n\n{para}" if cur else para
    if cur:
        packed.append(cur)

    out: list[str] = []
    for part in packed:
        while len(part) > MAX_CHARS:
            out.append(part[:MAX_CHARS])
            part = part[MAX_CHARS:]
        if part:
            out.append(part)
    return out


# ── 掃檔 ──────────────────────────────────────────────────


def collect_files(root: Path) -> list[Path]:
    seen: set[Path] = set()
    for pattern in INCLUDE_GLOBS:
        for p in root.glob(pattern):
            if p.is_file() and not EXCLUDE_PARTS & set(p.relative_to(root).parts):
                seen.add(p)
    return sorted(seen)


def build_chunks(root: Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    for f in collect_files(root):
        rel = str(f.relative_to(root))
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        chunks.extend(chunk_markdown(text, rel))
    return chunks


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser(description="把教材 .md 切塊建索引")
    ap.add_argument(
        "--root",
        default=str(Path(__file__).resolve().parent / "corpus"),
        help="語料資料夾，預設是內附的 corpus/",
    )
    ap.add_argument("--no-vectors", action="store_true", help="只建 BM25，不下載 embedding 模型")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    started = time.time()

    chunks = build_chunks(root)
    if not chunks:
        raise SystemExit(f"在 {root} 底下沒掃到任何 .md，檢查 --root 是否正確")

    vectors = None
    if not args.no_vectors and os.getenv("EMBEDDING", "local") != "none":
        model_name = os.getenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-small")
        try:
            print(f"載入 embedding 模型 {model_name}（第一次會下載，約 100MB）…")
            encode = load_encoder(model_name)
            vectors = np.asarray(
                encode([f"{c.heading}\n{c.text}" for c in chunks]), dtype="float32"
            )
        except Exception as exc:
            print(f"[warn] embedding 失敗，改建純 BM25 索引：{exc}")
            vectors = None

    data_dir = Path(__file__).resolve().parent / "data"
    built_at = datetime.now().isoformat(timespec="seconds")
    save_index(data_dir, chunks, vectors, built_at)

    files = len({c.path for c in chunks})
    print(
        f"完成：{len(chunks)} chunks / {files} 檔案 / {time.time() - started:.1f}s / "
        f"{'含向量' if vectors is not None else '純 BM25（降級）'}"
    )


if __name__ == "__main__":
    main()
