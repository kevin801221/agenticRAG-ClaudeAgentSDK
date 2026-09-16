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


# ── PDF 語料 ──────────────────────────────────────────────
#
# 論文是 PDF，不是 markdown。切塊策略也不同：PDF 沒有可靠的 heading 結構，
# 但有「頁」這個天然邊界，而且頁碼讓引用可以直接跳到原文那一頁。

from index_corpus import chunk_pdf


@pytest.fixture
def two_page_pdf(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    for n in (1, 2):
        page = doc.new_page()
        body = f"這是第 {n} 頁的內容。" + ("填充文字讓這一頁夠長，才不會被當成空白頁略過。" * 6)
        page.insert_textbox(pymupdf.Rect(40, 40, 550, 780), body, fontsize=11,
                            fontname="china-s")
    path = tmp_path / "paper.pdf"
    doc.save(path)
    doc.close()
    return path


def test_pdf_chunker_records_page_numbers(two_page_pdf):
    chunks = chunk_pdf(two_page_pdf, "papers/paper.pdf")

    assert chunks, "應該要切出東西"
    assert {c.page for c in chunks} == {1, 2}
    assert all(c.path == "papers/paper.pdf" for c in chunks)


def test_pdf_chunker_puts_page_in_heading(two_page_pdf):
    chunks = chunk_pdf(two_page_pdf, "papers/paper.pdf")

    assert "p.1" in chunks[0].heading
    assert chunks[0].heading.startswith("paper")


def test_pdf_chunker_links_neighbours(two_page_pdf):
    chunks = chunk_pdf(two_page_pdf, "papers/paper.pdf")

    assert chunks[0].prev_id is None
    assert chunks[-1].next_id is None
    if len(chunks) > 1:
        assert chunks[0].next_id == chunks[1].id


def test_pdf_chunker_skips_blank_pages(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    doc.new_page()                      # 全空白
    page = doc.new_page()
    page.insert_textbox(pymupdf.Rect(40, 40, 550, 780),
                        "只有這一頁有字。" * 20, fontsize=11, fontname="china-s")
    path = tmp_path / "sparse.pdf"
    doc.save(path)
    doc.close()

    chunks = chunk_pdf(path, "sparse.pdf")

    assert {c.page for c in chunks} == {2}, "空白頁不該產生片段"


def test_markdown_chunks_have_no_page(tmp_path):
    from index_corpus import chunk_markdown
    chunks = chunk_markdown("# 標題\n\n" + "內容。" * 60, "a.md")

    assert all(c.page is None for c in chunks), "markdown 沒有頁碼概念"


# ══════════ 向量庫檢視器 ══════════


@pytest.fixture
def vix(ix, tmp_path):
    """有向量的索引，但**不下載模型** —— 向量是造出來的。

    inspect_store 要測的是投影和統計的數學，不是 embedding 的品質。
    用假向量測，離線也跑得動，而且不會因為換模型就整組變紅。
    每個檔案給一個不同的中心，投影出來才該分得開。
    """
    import numpy as np

    import retrieval as R

    rng = np.random.default_rng(0)
    paths = sorted({c.path for c in ix.chunks})
    centers = {p: rng.normal(size=16) * 3 for p in paths}
    V = np.asarray(
        [centers[c.path] + rng.normal(size=16) * 0.2 for c in ix.chunks], dtype="float32"
    )
    ix.store = R.build_store("numpy", ix.chunks, V, tmp_path)
    ix.encode = lambda texts: np.asarray(
        [rng.normal(size=16) for _ in texts], dtype="float32"
    )
    import inspect_store

    inspect_store._CACHE.clear()
    yield ix
    inspect_store._CACHE.clear()


def test_projection_is_a_shadow_and_says_so(vix):
    """投影一定要回報解釋變異量。

    兩個軸通常只解釋 20-30%，不講清楚的話學生會把「圖上很近」
    當成「檢索一定撈得到」—— 那是這張圖唯一可能造成的傷害。
    """
    import inspect_store

    p = inspect_store.projection(vix)
    assert p["ok"]
    assert len(p["points"]) == len(vix.chunks)
    assert 0 < p["explained"] <= 1
    # 座標要**填滿** [-1, 1]，前端才不用管尺度。
    # 只斷言「沒超出」是不夠的 —— 那樣把縮放整段拿掉也驗不出來。
    xs = [q["x"] for q in p["points"]] + [q["y"] for q in p["points"]]
    assert max(abs(v) for v in xs) == pytest.approx(1.0, abs=1e-3)
    assert all(-1.0001 <= v <= 1.0001 for v in xs)
    # 檔案編號要對得回檔名
    assert all(0 <= q["f"] < len(p["files"]) for q in p["points"])


def test_projection_is_cached(vix):
    """算一次 SVD 就好。每次切到那一頁都重算的話，大語料會卡住。"""
    import inspect_store

    a = inspect_store.projection(vix)
    b = inspect_store.projection(vix)
    assert a is b


def test_projection_degrades_without_vectors(ix):
    """純 BM25 模式不能爆掉 —— 那是教室沒網路時的預設狀態。

    has_vectors 是唯讀 property（它看的是 store 有沒有東西），
    所以這裡做一個「假裝自己是 Index 但沒有向量」的替身，而不是去改真的那一個。
    """
    import inspect_store

    class NoVectors:
        has_vectors = False
        chunks = ix.chunks
        built_at = ix.built_at

    inspect_store._CACHE.clear()
    p = inspect_store.projection(NoVectors())
    assert not p["ok"] and "沒有向量" in p["why"]
    inspect_store._CACHE.clear()


def test_overview_reports_the_similarity_floor(vix):
    """平均相似度是個很重要的數字：e5 把什麼東西都放在 0.8 上下，
    所以「相似度 0.85」單看沒有意義。要教這件事就得先量出來。"""
    import inspect_store

    o = inspect_store.overview(vix)
    assert o["chunks"] == len(vix.chunks)
    assert o["files"] > 0
    assert o["chars"]["min"] <= o["chars"]["p50"] <= o["chars"]["max"]
    assert 0 < o["mean_similarity"] < 1
    assert o["dims"] == 16


def test_neighbors_excludes_itself_and_rejects_bad_id(vix):
    import inspect_store

    target = vix.chunks[0].id
    n = inspect_store.neighbors(vix, target, k=5)
    assert n["ok"]
    assert target not in [x["id"] for x in n["neighbors"]]
    assert n["neighbors"] == sorted(n["neighbors"], key=lambda x: -x["sim"])
    assert not inspect_store.neighbors(vix, "沒有這個片段#99")["ok"]


def test_chroma_notices_when_the_vectors_changed(tmp_path):
    """重建索引之後，chroma 一定要換成新向量。

    原本只比「筆數一樣嗎」。換 embedding 模型、或改切塊參數但筆數剛好沒變的時候，
    chroma 會安靜地繼續用舊向量 —— 檢索結果全錯，而且不會報任何錯。
    這是最難查的那一種，所以釘住它。
    """
    pytest.importorskip("chromadb")
    import numpy as np

    import retrieval as R

    chunks = [R.Chunk(id=f"x#{i}", path="x.md", heading="h", text="t") for i in range(4)]
    first = np.eye(4, 8, dtype="float32")
    second = np.roll(first, 3, axis=1)          # 筆數一樣，內容全不同

    R.build_store("chroma", chunks, first, tmp_path)
    store = R.build_store("chroma", chunks, second, tmp_path)

    got = np.asarray(store.vectors_for(["x#0"]))[0]
    assert np.allclose(got, second[0]), "chroma 還在用舊向量"
    assert store.query(second[0], k=1)[0][0] == "x#0"


def test_chroma_and_numpy_agree_after_a_rebuild(tmp_path):
    """兩種 store 換來換去，答案必須一樣 —— 這是可插拔的最低門檻。"""
    pytest.importorskip("chromadb")
    import numpy as np

    import retrieval as R

    rng = np.random.default_rng(3)
    chunks = [R.Chunk(id=f"c#{i}", path="c.md", heading="h", text="t") for i in range(12)]
    V = rng.normal(size=(12, 16)).astype("float32")
    V /= np.linalg.norm(V, axis=1, keepdims=True)

    q = V[5]
    npy = R.build_store("numpy", chunks, V, None).query(q, k=3)
    chroma = R.build_store("chroma", chunks, V, tmp_path).query(q, k=3)
    assert [i for i, _ in npy] == [i for i, _ in chroma]
