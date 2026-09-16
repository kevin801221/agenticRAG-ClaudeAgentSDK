"""notebook 是要發給學生的東西，這組測試盯住「不該出現在學生手上的內容」。

會需要這一組，是因為編輯器開著 notebook 時會把它記憶體裡那份**舊的**副本寫回磁碟，
悄悄蓋掉別人剛改好的東西 —— 而且 .ipynb 是一大團 JSON，肉眼看 diff 看不出來。
與其每次都靠人檢查，不如讓 pytest 直接紅給你看。
"""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
NOTEBOOKS = sorted((ROOT / "notebooks").glob("*.ipynb"))


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def text_of(nb: dict) -> str:
    return json.dumps(nb, ensure_ascii=False)


@pytest.mark.parametrize("path", NOTEBOOKS, ids=lambda p: p.name)
def test_no_absolute_home_paths(path: Path):
    """輸出裡不能有任何人的家目錄。

    學生拿到的 notebook 帶著講師機器的 /Users/某某某/... 很難看，
    而且那是不必要的個資外洩。
    """
    hits = re.findall(r"/Users/[A-Za-z0-9._-]+/", text_of(load(path)))
    # corpus 教材裡的 Write(/Users/**/.ssh/**) 是權限規則的範例字串，不是真的路徑
    real = [h for h in hits if not h.startswith("/Users/**")]
    assert not real, f"{path.name} 出現家目錄：{sorted(set(real))}"


@pytest.mark.parametrize("path", NOTEBOOKS, ids=lambda p: p.name)
def test_no_embedded_images(path: Path):
    """圖片要放 assets/ 再用相對路徑引用，不要 base64 夾帶在 .ipynb 裡。

    拖一張圖進去就會讓 notebook 從 50 KB 變成 3 MB，而且從此 git diff 讀不了。
    """
    nb = load(path)
    fat = [i for i, c in enumerate(nb["cells"]) if c.get("attachments")]
    assert not fat, (
        f"{path.name} 的第 {fat} 格夾帶了 base64 圖片。"
        "把圖存到 assets/，改用 ![說明](../assets/圖.png)"
    )
    assert len(path.read_bytes()) < 400_000, f"{path.name} 太大了（{len(path.read_bytes()) // 1024} KB）"


@pytest.mark.parametrize("path", NOTEBOOKS, ids=lambda p: p.name)
def test_every_code_cell_has_been_run(path: Path):
    """「打開就看得到結果」是這套教材的賣點之一。

    清掉輸出的 notebook 學生看不出這段到底會跑出什麼，
    而且沒跑過就等於沒驗證過 —— 曾經有一本被改成用不存在的 SDK 參數，
    因為輸出同時被清掉，所以沒人發現它打開就會炸。
    """
    nb = load(path)
    code = [c for c in nb["cells"] if c["cell_type"] == "code" and "".join(c["source"]).strip()]
    empty = [i for i, c in enumerate(code) if not c.get("outputs")]
    assert not empty, f"{path.name} 有 {len(empty)} 格沒有輸出（第 {empty} 格）—— 請重跑整本"

    errs = [o for c in code for o in c.get("outputs", []) if o.get("output_type") == "error"]
    assert not errs, f"{path.name} 的輸出裡有錯誤：{[e.get('ename') for e in errs]}"


def test_sdk_intro_keeps_the_framework_comparison():
    """這一格被編輯器的舊副本蓋掉過兩次，所以釘住它。

    「為什麼不用 LangChain」是全場一定會被問的第一題，
    第一本 notebook 沒有它，學生就得自己去翻 README。
    """
    nb = load(ROOT / "notebooks" / "01_agent_sdk_basics.ipynb")
    body = text_of(nb)
    for must in ("為什麼不用 LangChain", "LangGraph", "Deep Agents"):
        assert must in body, f"notebook 01 少了「{must}」那段比較"


@pytest.mark.parametrize("path", NOTEBOOKS, ids=lambda p: p.name)
def test_kernel_points_at_the_project_venv(path: Path):
    """四本都要記著同一個 kernel，學生打開才不會各開各的。"""
    ks = load(path)["metadata"].get("kernelspec", {})
    assert ks.get("name") == "agentic-rag", f"{path.name} 的 kernel 是 {ks.get('name')!r}"
