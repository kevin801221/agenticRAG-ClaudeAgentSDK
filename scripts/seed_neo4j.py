"""把現有的索引灌成一張圖。

不引進新資料集 —— 用的就是 data/ 裡那份已經切好的 chunk。
重點是讓學生看到：**同一批片段，換一種索引方式，能回答的問題就不一樣。**

    (:File {path, chunks})-[:HAS_CHUNK]->(:Chunk {id, heading, page, text})
    (:Chunk)-[:NEXT]->(:Chunk)                原文順序（切塊時就記好的 prev/next）
    (:Chunk)-[:SIMILAR {score}]->(:Chunk)     向量鄰居，**只連跨檔的**

為什麼 SIMILAR 只連跨檔：同一份文件裡相鄰的兩塊本來就像，連起來沒有資訊量，
只會讓圖變成毛球。跨檔的相似才是有意思的那種 ——
**同一個概念出現在兩份不同文件裡**，那正是向量檢索會撈到、但你看不出關聯的東西。

用法：
    uv run python scripts/seed_neo4j.py              # 建
    uv run python scripts/seed_neo4j.py --wipe       # 先清掉舊的再建
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv()

import graph_store as G  # noqa: E402
from retrieval import load_index  # noqa: E402

SIMILAR_TOP_K = 5        # 每塊往外連幾條
SIMILAR_MIN = 0.86       # 低於這個分數不連 —— e5 的基準線就在 0.83 上下，太低會全連在一起


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wipe", action="store_true", help="先刪掉圖裡既有的 File/Chunk")
    ap.add_argument("--data", default="data")
    args = ap.parse_args()

    if not G.configured():
        sys.exit("請先在 .env 設 NEO4J_URI 與 NEO4J_PASSWORD（見 .env.example）")

    ix = load_index(Path(args.data), embedding=os.getenv("EMBEDDING", "local"))
    print(f"索引：{len(ix.chunks)} 個片段，向量 {'有' if ix.has_vectors else '沒有'}")

    if args.wipe:
        G.run("MATCH (n) WHERE n:File OR n:Chunk DETACH DELETE n")
        print("清掉舊的 File / Chunk")

    # 唯一性約束：重跑這支腳本不該產生重複節點
    G.run("CREATE CONSTRAINT chunk_id IF NOT EXISTS FOR (c:Chunk) REQUIRE c.id IS UNIQUE")
    G.run("CREATE CONSTRAINT file_path IF NOT EXISTS FOR (f:File) REQUIRE f.path IS UNIQUE")

    rows = [
        {"id": c.id, "path": c.path, "heading": c.heading or "",
         "page": c.page, "text": c.text[:1500], "nxt": c.next_id}
        for c in ix.chunks
    ]
    G.run(
        """
        UNWIND $rows AS r
        MERGE (f:File {path: r.path})
        MERGE (c:Chunk {id: r.id})
          SET c.heading = r.heading, c.page = r.page, c.text = r.text
        MERGE (f)-[:HAS_CHUNK]->(c)
        """,
        rows=rows,
    )
    G.run(
        """
        UNWIND [r IN $rows WHERE r.nxt IS NOT NULL] AS r
        MATCH (a:Chunk {id: r.id}), (b:Chunk {id: r.nxt})
        MERGE (a)-[:NEXT]->(b)
        """,
        rows=rows,
    )
    G.run("MATCH (f:File)-[:HAS_CHUNK]->(c) WITH f, count(c) AS n SET f.chunks = n")
    print(f"節點：{len(rows)} 個 Chunk + File，NEXT 邊建好")

    if not ix.has_vectors:
        print("沒有向量，跳過 SIMILAR。純 BM25 的索引只會有骨架沒有跨檔關聯。")
    else:
        ids = [c.id for c in ix.chunks]
        V = np.asarray(ix.store.vectors_for(ids), dtype="float32")
        V = V / (np.linalg.norm(V, axis=1, keepdims=True) + 1e-9)
        path_of = {c.id: c.path for c in ix.chunks}
        sims = V @ V.T
        np.fill_diagonal(sims, -1)

        pairs = []
        for i, aid in enumerate(ids):
            for j in np.argsort(-sims[i])[:SIMILAR_TOP_K * 4]:
                score = float(sims[i][j])
                if score < SIMILAR_MIN:
                    break
                bid = ids[j]
                if path_of[aid] == path_of[bid]:
                    continue              # 同檔不連 —— 相鄰本來就像，沒有資訊量
                if aid < bid:             # 無向邊只存一次
                    pairs.append({"a": aid, "b": bid, "score": round(score, 4)})
                if len([p for p in pairs if p["a"] == aid]) >= SIMILAR_TOP_K:
                    break
        seen, uniq = set(), []
        for p in pairs:
            k = (p["a"], p["b"])
            if k not in seen:
                seen.add(k)
                uniq.append(p)
        G.run(
            """
            UNWIND $pairs AS p
            MATCH (a:Chunk {id: p.a}), (b:Chunk {id: p.b})
            MERGE (a)-[s:SIMILAR]->(b) SET s.score = p.score
            """,
            pairs=uniq,
        )
        print(f"SIMILAR：{len(uniq)} 條跨檔相似邊（門檻 {SIMILAR_MIN}，每塊最多 {SIMILAR_TOP_K} 條）")

    d = G.describe()
    print(f"\n完成。節點 {d['nodes']}、關係 {d['edges']}")
    for c in d["labels"]:
        print(f"  {c['label']:10} {c['n']}")
    for r in d["relationships"]:
        print(f"  -[{r['type']}]-> {r['n']}")
    G.close()


if __name__ == "__main__":
    main()
