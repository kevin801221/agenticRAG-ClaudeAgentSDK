"""看得見的向量庫：把 384 維壓成兩維畫出來。

為什麼值得做：學生對「向量檢索」的想像通常是「它會找到意思相近的」，
然後遇到撈回一堆不相關的東西就以為是自己 query 寫壞了。

把整個語料庫投影出來就會看到真相 —— 這份知識庫裡，中文的 Claude Code 教材
和英文的論文 PDF 是**兩團完全分開的東西**。你用中文問一個論文裡才有的概念，
向量會把你拉去中文那一團，撈回來的片段看起來像、其實無關。

那不是 query 的問題，是**向量空間本來就長這樣**。看過一次就不會再誤會。

PCA 用 numpy 的 SVD 做，不加任何相依。
"""

from __future__ import annotations

import collections
from typing import Any

import numpy as np

# 投影一次要算整個矩陣的 SVD，語料不變就沒必要重算
_CACHE: dict[str, Any] = {}


def _vectors(ix) -> tuple[list[str], np.ndarray]:
    ids = [c.id for c in ix.chunks]
    V = np.asarray(ix.store.vectors_for(ids), dtype="float32")
    # 正規化再投影 —— 檢索用的是 cosine，不正規化的話畫出來的距離跟檢索用的距離是兩回事
    V = V / (np.linalg.norm(V, axis=1, keepdims=True) + 1e-9)
    return ids, V


def projection(ix) -> dict:
    """整個語料庫投影到 2D。

    回傳的 `explained` 一定要顯示在畫面上：兩個軸通常只解釋 20-30% 的變異，
    **這是一張 384 維的影子，不是真相**。說得不夠清楚，學生會把「圖上很近」
    當成「檢索一定撈得到」。
    """
    if not ix.has_vectors:
        return {"ok": False, "why": "這個索引沒有向量（純 BM25 模式），沒有空間可以畫"}

    key = f"{ix.built_at}:{len(ix.chunks)}"
    if _CACHE.get("key") == key:
        return _CACHE["value"]

    ids, V = _vectors(ix)
    X = V - V.mean(axis=0)
    _, S, Vt = np.linalg.svd(X, full_matrices=False)
    P = X @ Vt[:2].T

    # 縮到 [-1, 1]，前端就不用管尺度
    span = np.abs(P).max() or 1.0
    P = P / span

    by_path: dict[str, int] = {}
    points = []
    for c, (x, y) in zip(ix.chunks, P):
        by_path.setdefault(c.path, len(by_path))
        points.append({
            "id": c.id,
            "x": round(float(x), 4),
            "y": round(float(y), 4),
            "f": by_path[c.path],                       # 檔案編號，前端拿來上色
            "h": (c.heading or c.text[:40]).strip()[:60],
            "page": c.page,
        })

    value = {
        "ok": True,
        "points": points,
        "files": [p for p, _ in sorted(by_path.items(), key=lambda kv: kv[1])],
        "explained": round(float((S[:2] ** 2).sum() / (S ** 2).sum()), 4),
        "dims": int(V.shape[1]),
        "n": len(points),
    }
    _CACHE.update(key=key, value=value)
    return value


def overview(ix) -> dict:
    """數字版的體檢表。畫面上那張圖看不出來的東西放這裡。"""
    per_file = collections.Counter(c.path for c in ix.chunks)
    lens = np.array([len(c.text) for c in ix.chunks]) if ix.chunks else np.array([0])
    ctx = sum(1 for c in ix.chunks if c.context)
    out = {
        "chunks": len(ix.chunks),
        "files": len(per_file),
        "store": ix.store_kind,
        "has_vectors": ix.has_vectors,
        "built_at": ix.built_at,
        "with_context": ctx,                 # 補過脈絡的片段數（Contextual Retrieval）
        "chars": {
            "min": int(lens.min()), "p50": int(np.percentile(lens, 50)),
            "p90": int(np.percentile(lens, 90)), "max": int(lens.max()),
        },
        "per_file": [
            {"path": p, "chunks": n, "pages": sum(1 for c in ix.chunks if c.path == p and c.page)}
            for p, n in per_file.most_common()
        ],
    }
    if ix.has_vectors:
        _, V = _vectors(ix)
        out["dims"] = int(V.shape[1])
        # 平均兩兩相似度：偏高表示整個語料太同質，向量檢索會很難分辨
        sample = V[np.random.default_rng(0).choice(len(V), size=min(200, len(V)), replace=False)]
        sim = sample @ sample.T
        np.fill_diagonal(sim, np.nan)
        out["mean_similarity"] = round(float(np.nanmean(sim)), 4)
    return out


def neighbors(ix, chunk_id: str, k: int = 8) -> dict:
    """某個片段在向量空間裡的鄰居。

    用來回答「為什麼這一題會撈到那一塊」—— 點開它的鄰居，
    通常就會看到是某個不相干但用詞很像的片段把它拉進來的。
    """
    if not ix.has_vectors:
        return {"ok": False, "why": "沒有向量"}
    ids, V = _vectors(ix)
    if chunk_id not in ids:
        return {"ok": False, "why": f"沒有這個片段：{chunk_id}"}
    i = ids.index(chunk_id)
    sims = V @ V[i]
    order = np.argsort(-sims)[: k + 1]
    return {
        "ok": True,
        "of": chunk_id,
        "neighbors": [
            {"id": ids[j], "sim": round(float(sims[j]), 4),
             "heading": (ix.by_id[ids[j]].heading or "")[:60],
             "path": ix.by_id[ids[j]].path}
            for j in order if j != i
        ],
    }
