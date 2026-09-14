"""檢索層與切塊器的測試。

這層完全不碰 LLM，所以測起來快又穩。agent 那層不寫自動化測試
（會花時間也花額度），改用 README 的 smoke 指令。
"""

import pytest

from index_corpus import chunk_markdown
from retrieval import (
    Chunk,
    bm25_search,
    build_index,
    hybrid_search,
    neighbors,
    rrf,
    vector_search,
)

# 中文語料，每段都刻意超過 100 字避免觸發「過短併入下一塊」規則
CORPUS = [
    Chunk(
        id="a.md#0",
        path="a.md",
        heading="Hooks 心智模型",
        text=(
            "PreToolUse hook 會在工具真正執行之前攔截下來，"
            "腳本只要 exit 2 就能把這次呼叫擋掉，並把 stderr 的內容回傳給模型當作理由。"
            "guard-secrets.sh 就是用這招擋住寫入 .env 與 credentials.json 這類敏感檔案。"
        ),
        prev_id=None,
        next_id="a.md#1",
    ),
    Chunk(
        id="a.md#1",
        path="a.md",
        heading="Hooks 心智模型 > 啟用方式",
        text=(
            "hook 設定寫在 settings.json 的 hooks 欄位裡，依事件名稱分組，"
            "每一組可以掛多支腳本。改完設定要重開 session 才會生效，"
            "這是現場教學最常卡住的地方，記得提醒學生。"
        ),
        prev_id="a.md#0",
        next_id="b.md#0",
    ),
    Chunk(
        id="b.md#0",
        path="b.md",
        heading="Flutter 冥想 App",
        text=(
            "這個案例用三個 Claude 實例平行開發一款冥想應用程式，"
            "分別負責後端資料、閱讀器介面與呼吸動畫，"
            "先凍結規格與 API 契約再開工，最後合併驗收。"
        ),
        prev_id="a.md#1",
        next_id=None,
    ),
]


@pytest.fixture
def ix():
    """沒有向量的索引 —— 也就是降級模式。"""
    return build_index(CORPUS)


# ── 切塊器 ────────────────────────────────────────────────


def _long(seed: str) -> str:
    """產生一段超過 100 字、但不到 1200 字的內文。"""
    return (seed + "，這句話是用來把段落撐過最小長度門檻的填充內容。") * 5


def test_chunker_builds_full_heading_path():
    md = f"# 主標題\n\n{_long('第一段')}\n\n## 子標題\n\n{_long('第二段')}\n"

    chunks = chunk_markdown(md, "a.md")

    assert chunks[0].heading == "主標題"
    assert chunks[1].heading == "主標題 > 子標題"


def test_chunker_merges_short_section_into_next():
    md = f"# 太短了\n\n只有幾個字。\n\n## 正常段落\n\n{_long('內容')}\n"

    chunks = chunk_markdown(md, "a.md")

    assert len(chunks) == 1
    assert "只有幾個字" in chunks[0].text
    assert "內容" in chunks[0].text


def test_chunker_splits_oversized_section_into_parts():
    body = "\n\n".join(_long(f"第{i}段") for i in range(12))  # 遠超過 1200 字
    md = f"# 很長的一節\n\n{body}\n"

    chunks = chunk_markdown(md, "a.md")

    assert len(chunks) > 1
    assert all(len(c.text) <= 1200 for c in chunks)
    assert chunks[0].heading.endswith("(part 1)")
    assert chunks[1].heading.endswith("(part 2)")


def test_chunker_links_neighbours_in_order():
    md = f"# 一\n\n{_long('甲')}\n\n# 二\n\n{_long('乙')}\n\n# 三\n\n{_long('丙')}\n"

    chunks = chunk_markdown(md, "a.md")

    assert chunks[0].prev_id is None
    assert chunks[0].next_id == chunks[1].id
    assert chunks[1].prev_id == chunks[0].id
    assert chunks[-1].next_id is None


# ── RRF 融合 ──────────────────────────────────────────────


def test_rrf_ranks_items_appearing_in_both_lists_first():
    fused = rrf([["x", "y", "z"], ["z", "x", "w"]])

    ids = [chunk_id for chunk_id, _ in fused]
    assert ids[0] == "x"  # 兩份都在前段
    assert ids.index("z") < ids.index("y")  # 兩份都上榜 > 只上榜一次


# ── 檢索 ──────────────────────────────────────────────────


def test_bm25_search_finds_chinese_match(ix):
    hits = bm25_search(ix, "冥想 App 平行開發", k=1)

    assert hits[0].chunk_id == "b.md#0"


def test_vector_search_falls_back_to_bm25_when_index_has_no_vectors(ix):
    hits = vector_search(ix, "hook 怎麼擋住寫入 .env", k=2)

    assert hits, "降級時仍然要回得出結果"
    assert all(h.degraded for h in hits)


def test_hybrid_search_falls_back_to_bm25_when_index_has_no_vectors(ix):
    hits = hybrid_search(ix, "hook 怎麼擋住寫入 .env", k=2)

    assert hits[0].chunk_id == "a.md#0"
    assert all(h.degraded for h in hits)


def test_hybrid_search_fuses_both_rankings_when_vectors_present():
    import numpy as np

    # 造三個正交向量，讓查詢向量明確指向 b.md#0
    vectors = np.eye(3, dtype="float32")

    def fake_encode(texts):
        return np.array([[0.0, 0.0, 1.0]] * len(texts), dtype="float32")

    ix = build_index(CORPUS, vectors=vectors, encode=fake_encode)
    hits = hybrid_search(ix, "任意查詢", k=3)

    assert not any(h.degraded for h in hits)
    assert hits[0].chunk_id == "b.md#0"


# ── 鄰居擴展 ──────────────────────────────────────────────


def test_neighbors_returns_surrounding_chunks_in_document_order(ix):
    got = neighbors(ix, "a.md#1", window=1)

    assert [c.id for c in got] == ["a.md#0", "a.md#1", "b.md#0"]


def test_neighbors_clamps_at_document_edges(ix):
    got = neighbors(ix, "a.md#0", window=1)

    assert [c.id for c in got] == ["a.md#0", "a.md#1"]


# ── 向量儲存層可插拔 ──────────────────────────────────────
#
# numpy 與 chroma 是同一個介面的兩種實作。教學重點：換 store 不該換答案。

import numpy as np
import pytest

from retrieval import NumpyStore, build_store


@pytest.fixture
def vectors():
    """三個相似度**互不相同**的單位向量。

    不要用 np.eye() —— 正交向量對查詢的相似度全是 0.0，排序變成平手，
    而平手時各家向量庫的 tie-break 不一樣，測出來的是實作細節不是行為。
    """
    return np.array([[1.0, 0.0, 0.0],
                     [0.6, 0.0, 0.8],
                     [0.0, 0.0, 1.0]], dtype="float32")


def test_numpy_store_ranks_by_cosine(vectors):
    store = NumpyStore(CORPUS, vectors)

    hits = store.query(np.array([0.0, 0.0, 1.0], dtype="float32"), k=3)

    assert hits[0][0] == "b.md#0"          # 第三個 chunk
    assert hits[0][1] == pytest.approx(1.0)


def test_numpy_store_returns_vectors_in_requested_order(vectors):
    store = NumpyStore(CORPUS, vectors)

    got = store.vectors_for(["b.md#0", "a.md#0"])

    assert np.allclose(got[0], [0, 0, 1])
    assert np.allclose(got[1], [1, 0, 0])


def test_unknown_store_name_is_rejected(vectors):
    with pytest.raises(ValueError, match="VECTOR_STORE"):
        build_store("redis", CORPUS, vectors, data_dir=None)


def test_chroma_store_agrees_with_numpy_store(vectors, tmp_path):
    """同一組向量、同一個查詢，兩種 store 必須給出同樣的排序。"""
    chroma = pytest.importorskip("chromadb")  # noqa: F841

    q = np.array([0.0, 0.0, 1.0], dtype="float32")
    numpy_hits = build_store("numpy", CORPUS, vectors, data_dir=None).query(q, k=3)
    chroma_hits = build_store("chroma", CORPUS, vectors, data_dir=tmp_path).query(q, k=3)

    assert [h[0] for h in chroma_hits] == [h[0] for h in numpy_hits]
    assert chroma_hits[0][1] == pytest.approx(numpy_hits[0][1], abs=1e-4)


def test_chroma_store_returns_vectors_in_requested_order(vectors, tmp_path):
    pytest.importorskip("chromadb")
    store = build_store("chroma", CORPUS, vectors, data_dir=tmp_path)

    got = store.vectors_for(["b.md#0", "a.md#0"])

    assert np.allclose(got[0], [0, 0, 1], atol=1e-5)
    assert np.allclose(got[1], [1, 0, 0], atol=1e-5)
