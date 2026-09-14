"""檢索層：BM25（中文斷詞）+ 向量 + RRF 融合。

這一整支不呼叫任何 LLM、不連任何 API，純函式，所以測起來快。
沒有向量時（模型載不動、教室沒網路）自動降級成純 BM25，回傳的 Hit 會標
degraded=True，讓前端可以明白告訴學生現在跑的不是完整版。
"""

from __future__ import annotations

import os
import pickle
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

import jieba
import numpy as np
from rank_bm25 import BM25Okapi

RRF_K = 60  # RRF 的平滑常數，論文預設值


@dataclass
class Chunk:
    id: str  # "corpus/01-hooks.md#7" 或 "papers/crag.pdf#3"
    path: str
    heading: str  # markdown 是 heading 路徑，PDF 是 "檔名 > p.3"
    text: str
    prev_id: str | None = None
    next_id: str | None = None
    page: int | None = None  # 只有 PDF 有。讓引用可以跳到原文那一頁


@dataclass
class Hit:
    chunk_id: str
    score: float
    rank: int
    degraded: bool = False  # True = 向量不可用時退回 BM25 的結果


# ═══════════════════════════════════════════════════════════
# 向量儲存層：numpy 與 chroma 是同一個介面的兩種實作
#
# 介面只有兩個方法，因為 RAG 對向量庫的需求其實就這麼點：
#   query(向量, k)       → [(chunk_id, cosine 相似度)]
#   vectors_for(id 清單) → 那些 id 的向量（MMR 去重要用）
#
# 換 store 不該換答案 —— tests/test_retrieval.py 有一條測試專門盯這件事。
# ═══════════════════════════════════════════════════════════


class NumpyStore:
    """整份向量放在記憶體，暴力算 cosine。

    6601 筆全掃只要 46 微秒 —— 而把問題轉成向量要 5.7 毫秒。
    也就是說檢索本身佔總時間 0.8%，這個規模下裝向量資料庫優化的是那 0.8%。
    """

    kind = "numpy"

    def __init__(self, chunks: Sequence[Chunk], vectors: np.ndarray):
        self.ids = [c.id for c in chunks]
        self.pos = {c.id: i for i, c in enumerate(chunks)}
        self.matrix = np.asarray(vectors, dtype="float32")

    def query(self, qvec: np.ndarray, k: int = 5) -> list[tuple[str, float]]:
        sims = self.matrix @ qvec          # 索引已 L2 normalize，內積即 cosine
        top = np.argsort(sims)[::-1][:k]
        return [(self.ids[i], float(sims[i])) for i in top]

    def vectors_for(self, chunk_ids: Sequence[str]) -> np.ndarray:
        rows = [self.pos[c] for c in chunk_ids if c in self.pos]
        return self.matrix[rows] if rows else np.empty((0, self.matrix.shape[1]), dtype="float32")


class ChromaStore:
    """向量交給 Chroma 管。上課示範「同一套程式碼接真的向量資料庫」用。

    幾十萬筆以上、或需要增量更新 / metadata 過濾時，才真的需要換到這邊。
    """

    kind = "chroma"

    def __init__(self, collection):
        self.collection = collection

    @classmethod
    def build(cls, chunks: Sequence[Chunk], vectors: np.ndarray, data_dir: Path | None):
        import chromadb

        client = (
            chromadb.PersistentClient(path=str(Path(data_dir) / "chroma"))
            if data_dir
            else chromadb.EphemeralClient()
        )
        col = client.get_or_create_collection("rag", metadata={"hnsw:space": "cosine"})
        # 直接灌已經算好的向量，不重新 embedding
        if col.count() != len(chunks):
            ids = [c.id for c in chunks]
            emb = np.asarray(vectors, dtype="float32").tolist()
            for i in range(0, len(ids), 2000):   # chroma 單次 upsert 有上限
                col.upsert(ids=ids[i : i + 2000], embeddings=emb[i : i + 2000])
        return cls(col)

    def query(self, qvec: np.ndarray, k: int = 5) -> list[tuple[str, float]]:
        r = self.collection.query(
            query_embeddings=[np.asarray(qvec, dtype="float32").tolist()],
            n_results=k,
            include=["distances"],
        )
        # cosine 空間下 distance = 1 - similarity
        return [(i, 1.0 - float(d)) for i, d in zip(r["ids"][0], r["distances"][0])]

    def vectors_for(self, chunk_ids: Sequence[str]) -> np.ndarray:
        r = self.collection.get(ids=list(chunk_ids), include=["embeddings"])
        got = {i: e for i, e in zip(r["ids"], r["embeddings"])}
        rows = [got[c] for c in chunk_ids if c in got]   # chroma 不保證回傳順序
        return np.asarray(rows, dtype="float32")


def build_store(name: str, chunks: Sequence[Chunk], vectors: np.ndarray, data_dir: Path | None):
    if name == "numpy":
        return NumpyStore(chunks, vectors)
    if name == "chroma":
        return ChromaStore.build(chunks, vectors, data_dir)
    raise ValueError(f"VECTOR_STORE 只能是 numpy 或 chroma，收到 {name!r}")


@dataclass
class Index:
    chunks: list[Chunk]
    by_id: dict[str, Chunk]
    order: dict[str, int]
    bm25: BM25Okapi
    store: NumpyStore | ChromaStore | None = None
    encode: Callable[[Sequence[str]], np.ndarray] | None = None
    built_at: str = ""

    @property
    def has_vectors(self) -> bool:
        return self.store is not None and self.encode is not None

    @property
    def store_kind(self) -> str:
        return self.store.kind if self.store else "none"


def tokenize(text: str) -> list[str]:
    """中文要斷詞，BM25 才有東西可比。索引與查詢必須用同一套。"""
    return [t for t in jieba.lcut(text.lower()) if t.strip()]


def build_index(
    chunks: Sequence[Chunk],
    vectors: np.ndarray | None = None,
    encode: Callable[[Sequence[str]], np.ndarray] | None = None,
    built_at: str = "",
    store=None,
) -> Index:
    """vectors 是方便用法（自動包成 NumpyStore）；要接別的向量庫就傳 store。"""
    chunks = list(chunks)
    corpus = [tokenize(f"{c.heading} {c.text}") for c in chunks]
    if store is None and vectors is not None:
        store = NumpyStore(chunks, vectors)
    return Index(
        chunks=chunks,
        by_id={c.id: c for c in chunks},
        order={c.id: i for i, c in enumerate(chunks)},
        bm25=BM25Okapi(corpus),
        store=store,
        encode=encode,
        built_at=built_at,
    )


def rrf(rankings: Sequence[Sequence[str]], k: int = RRF_K) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion：score = Σ 1/(k + rank)。

    選 RRF 不選加權相加，是因為 BM25 分數和 cosine 不同量綱，加權要調參；
    RRF 只看排名、零參數，而且同時出現在兩份榜上的自然會被推到前面。
    """
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda kv: -kv[1])


def bm25_search(ix: Index, query: str, k: int = 5) -> list[Hit]:
    scores = ix.bm25.get_scores(tokenize(query))
    top = np.argsort(scores)[::-1][:k]
    # 分數 0 代表一個詞都沒命中，回空的比回垃圾好 —— 也剛好逼 agent 自己改寫 query
    return [
        Hit(chunk_id=ix.chunks[i].id, score=float(scores[i]), rank=rank)
        for rank, i in enumerate(top)
        if scores[i] > 0
    ]


def vector_search(ix: Index, query: str, k: int = 5) -> list[Hit]:
    if not ix.has_vectors:
        return _degraded(bm25_search(ix, query, k))
    q = np.asarray(ix.encode([query])[0], dtype="float32")
    q = q / (np.linalg.norm(q) or 1.0)
    return [
        Hit(chunk_id=chunk_id, score=score, rank=rank)
        for rank, (chunk_id, score) in enumerate(ix.store.query(q, k))
    ]


def hybrid_search(ix: Index, query: str, k: int = 5) -> list[Hit]:
    if not ix.has_vectors:
        return _degraded(bm25_search(ix, query, k))
    lexical = [h.chunk_id for h in bm25_search(ix, query, k * 2)]
    semantic = [h.chunk_id for h in vector_search(ix, query, k * 2)]
    return [
        Hit(chunk_id=chunk_id, score=score, rank=rank)
        for rank, (chunk_id, score) in enumerate(rrf([lexical, semantic])[:k])
    ]


def get_chunk(ix: Index, chunk_id: str) -> Chunk:
    return ix.by_id[chunk_id]


def neighbors(ix: Index, chunk_id: str, window: int = 1) -> list[Chunk]:
    """取前後鄰居（含自己），片段被切斷時往外抓上下文用。"""
    i = ix.order[chunk_id]
    lo = max(0, i - window)
    hi = min(len(ix.chunks), i + window + 1)
    return ix.chunks[lo:hi]


def _degraded(hits: list[Hit]) -> list[Hit]:
    return [replace(h, degraded=True) for h in hits]


# ── 落檔與載入 ────────────────────────────────────────────


def save_index(data_dir: Path, chunks: Sequence[Chunk], vectors: np.ndarray | None, built_at: str) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    with (data_dir / "index.pkl").open("wb") as f:
        pickle.dump({"chunks": list(chunks), "built_at": built_at}, f)
    if vectors is not None:
        np.save(data_dir / "vectors.npy", vectors)
    else:
        (data_dir / "vectors.npy").unlink(missing_ok=True)


DEFAULT_EMBEDDING_MODEL = "intfloat/multilingual-e5-small"


def load_index(data_dir: Path, embedding: str = "local", model_name: str = "") -> Index:
    index_file = data_dir / "index.pkl"
    if not index_file.exists():
        raise FileNotFoundError(
            f"找不到索引 {index_file}\n請先執行：uv run python index_corpus.py"
        )
    with index_file.open("rb") as f:
        payload = pickle.load(f)

    store, encode = None, None
    vectors_file = data_dir / "vectors.npy"
    if embedding == "local" and vectors_file.exists():
        try:
            encode = load_encoder(model_name or os.getenv("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL))
            vectors = np.load(vectors_file)
            # vectors.npy 永遠是原始資料；chroma 只是另一種放法，第一次會從它灌進去
            store = build_store(
                os.getenv("VECTOR_STORE", "numpy"), payload["chunks"], vectors, data_dir
            )
        except Exception as exc:  # 載不動就降級，不要讓整堂課停在這裡
            print(f"[warn] 向量層啟用失敗，降級為純 BM25：{exc}")
            store, encode = None, None

    return build_index(payload["chunks"], store=store, encode=encode, built_at=payload["built_at"])


def load_encoder(model_name: str) -> Callable[[Sequence[str]], np.ndarray]:
    """本地 embedding。Mac 預設走 MPS，沒有就 CPU。"""
    import torch
    from sentence_transformers import SentenceTransformer

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    try:
        model = SentenceTransformer(model_name, device=device)
    except Exception as exc:  # MPS 偶爾會出事，掉回 CPU 也比整個降級成 BM25 好
        print(f"[warn] {device} 載入失敗（{exc}），改用 CPU")
        model = SentenceTransformer(model_name, device="cpu")

    def encode(texts: Sequence[str]) -> np.ndarray:
        return model.encode(
            list(texts),
            normalize_embeddings=True,
            show_progress_bar=False,
            batch_size=32,
        )

    return encode
