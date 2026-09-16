"""Neo4j：同一份語料的另一種看法。

向量庫看到的是「雲」—— 每個片段是空間裡的一個點，關係只有距離。
圖看到的是「骨架」—— 誰在誰後面、誰跟誰在同一個檔、哪兩塊在講同一件事。

同一批 chunk，兩種索引，回答的問題不一樣：

    向量：「跟這句話意思最像的五塊是什麼」
    圖　：「這一塊的前後文是什麼、它跨到哪些別的檔案」

這就是 GraphRAG 想解決的問題 —— 向量檢索撈回來的片段彼此是孤立的，
你拿不到「它們之間的關係」。

圖長這樣（`scripts/seed_neo4j.py` 建的）：

    (:File {path})-[:HAS_CHUNK]->(:Chunk {id, heading, page})
    (:Chunk)-[:NEXT]->(:Chunk)                  原文順序
    (:Chunk)-[:SIMILAR {score}]->(:Chunk)       向量鄰居，跨檔才連

連線設定走環境變數，沒設就當作沒有這個資料源 —— **不能因為沒裝 Neo4j 就啟動不了**。
"""

from __future__ import annotations

import os
from typing import Any

_DRIVER: Any = None


def settings() -> dict[str, str]:
    """用到才讀環境變數。

    寫成模組層級的常數會被 import 順序咬：只要有人在 load_dotenv() 之前
    先 import 到這支，設定就永遠是空的 —— 而且錯誤訊息會說「沒有設定」，
    看起來像使用者沒填，其實是載入順序的問題。
    """
    return {
        "uri": os.getenv("NEO4J_URI", ""),
        "user": os.getenv("NEO4J_USER", "neo4j"),
        "password": os.getenv("NEO4J_PASSWORD", ""),
        "database": os.getenv("NEO4J_DATABASE", "neo4j"),
    }


def configured() -> bool:
    c = settings()
    return bool(c["uri"] and c["password"])


def driver():
    """連線是延遲建立的 —— 沒人用圖的話不該有一條閒置連線掛在那裡。"""
    global _DRIVER
    if _DRIVER is None:
        if not configured():
            raise RuntimeError("沒有設定 NEO4J_URI / NEO4J_PASSWORD")
        from neo4j import GraphDatabase

        c = settings()
        _DRIVER = GraphDatabase.driver(c["uri"], auth=(c["user"], c["password"]))
    return _DRIVER


def close() -> None:
    global _DRIVER
    if _DRIVER is not None:
        _DRIVER.close()
        _DRIVER = None


def run(cypher: str, **params) -> list[dict]:
    with driver().session(database=settings()["database"]) as s:
        return [r.data() for r in s.run(cypher, **params)]


# ── 唯讀護欄 ─────────────────────────────────────────────

# 給 agent 用的那個工具只能讀。不是信任問題 —— 是 policy 寫錯一個字
# 就可能把教室的資料庫清掉，而那個錯誤要到下一堂課才會被發現。
FORBIDDEN = (
    "create", "merge", "delete", "detach", "set", "remove", "drop",
    "load csv", "call db.", "call apoc", "call dbms",
)


def read_only(cypher: str) -> tuple[bool, str]:
    low = " ".join(cypher.lower().split())
    for word in FORBIDDEN:
        if word in low:
            return False, f"這個工具只能讀，不接受 `{word}`"
    if not low.startswith(("match", "with", "unwind", "return", "profile", "explain")):
        return False, "只接受 MATCH / WITH / UNWIND / RETURN 開頭的查詢"
    return True, ""


# ── 給人看的 ─────────────────────────────────────────────


def describe() -> dict:
    """這個圖裡有什麼。前端拿它畫 schema，也給人一眼確認資料進去了沒。"""
    if not configured():
        return {"ok": False, "why": "沒有設定 NEO4J_URI / NEO4J_PASSWORD"}
    try:
        labels = run("CALL db.labels() YIELD label RETURN label ORDER BY label")
        rels = run("CALL db.relationshipTypes() YIELD relationshipType AS t RETURN t ORDER BY t")
        counts = [
            {"label": l["label"],
             "n": run(f"MATCH (n:`{l['label']}`) RETURN count(n) AS n")[0]["n"]}
            for l in labels
        ]
        rcounts = [
            {"type": r["t"],
             "n": run(f"MATCH ()-[e:`{r['t']}`]->() RETURN count(e) AS n")[0]["n"]}
            for r in rels
        ]
        cfg = settings()
        return {
            "ok": True, "uri": cfg["uri"], "database": cfg["database"],
            "labels": counts, "relationships": rcounts,
            "nodes": sum(c["n"] for c in counts),
            "edges": sum(r["n"] for r in rcounts),
        }
    except Exception as exc:  # noqa: BLE001 — 連不上要說得出為什麼
        return {"ok": False, "why": f"{type(exc).__name__}: {exc}"}


def subgraph(limit: int = 300) -> dict:
    """抓一塊子圖給前端畫。

    整個圖全部畫出來在 200 個節點以上就是一團毛球，看不出東西 ——
    所以預設只抓跨檔的 SIMILAR 邊加上它們碰到的節點。
    跨檔的相似關係才是有資訊量的那些：**同一個概念出現在兩份不同文件裡**。
    """
    if not configured():
        return {"ok": False, "why": "沒有設定 NEO4J_URI / NEO4J_PASSWORD"}
    try:
        rows = run(
            """
            MATCH (f1:File)-[:HAS_CHUNK]->(a:Chunk)-[s:SIMILAR]->(b:Chunk)<-[:HAS_CHUNK]-(f2:File)
            WHERE f1.path <> f2.path
            RETURN a.id AS a, b.id AS b, s.score AS score,
                   f1.path AS pa, f2.path AS pb,
                   a.heading AS ha, b.heading AS hb
            ORDER BY s.score DESC LIMIT $limit
            """,
            limit=limit,
        )
        nodes: dict[str, dict] = {}
        files: list[str] = []
        for r in rows:
            for nid, path, head in ((r["a"], r["pa"], r["ha"]), (r["b"], r["pb"], r["hb"])):
                if path not in files:
                    files.append(path)
                nodes.setdefault(nid, {"id": nid, "path": path, "f": files.index(path),
                                       "heading": (head or "")[:60]})
        return {
            "ok": True, "files": files,
            "nodes": list(nodes.values()),
            "edges": [{"a": r["a"], "b": r["b"], "score": round(r["score"], 3)} for r in rows],
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "why": f"{type(exc).__name__}: {exc}"}
