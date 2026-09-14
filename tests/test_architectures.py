"""架構層的煙霧測試。

存在的理由很實際：這個專案的架構是「資料」，很容易改壞卻沒人發現 ——
`tests/test_retrieval.py` 只碰檢索層，完全不 import modules.py，
所以 modules.py 就算語法壞掉也照樣全綠。這支就是來堵這個洞的。

不呼叫 LLM，跑起來不用一秒。
"""

import pytest

import modules as M
from retrieval import Chunk, build_index


@pytest.fixture
def ix():
    chunks = [
        Chunk(id="a.md#0", path="a.md", heading="標題", text="內容" * 60,
              prev_id=None, next_id="a.md#1"),
        Chunk(id="a.md#1", path="a.md", heading="標題 > 小節", text="更多內容" * 60,
              prev_id="a.md#0", next_id=None),
    ]
    return build_index(chunks)


def test_every_architecture_builds_valid_sdk_options(ix):
    """每個架構都要能翻譯成合法的 ClaudeAgentOptions。"""
    for key, arch in M.ARCHITECTURES.items():
        options, step = M.build_options(arch, ix, lambda e: None)

        assert arch.name in options.system_prompt, f"{key}: system prompt 沒帶到架構名"
        assert options.max_turns == arch.max_turns, f"{key}: max_turns 沒帶到"
        assert options.tools == arch.builtin_tools, f"{key}: 內建工具沒關乾淨"
        assert step["n"] == 0


def test_allowed_tools_covers_every_declared_module(ix):
    """架構宣告的每個模組都要出現在 allowed_tools，否則模型叫不動它。"""
    for key, arch in M.ARCHITECTURES.items():
        options, _ = M.build_options(arch, ix, lambda e: None)
        for m in arch.modules:
            assert f"mcp__ragmod__{m}" in options.allowed_tools, f"{key}: {m} 沒被允許"
        for t in arch.builtin_tools:
            assert t in options.allowed_tools, f"{key}: 內建工具 {t} 沒被允許"


def test_architectures_only_reference_real_modules():
    """policy 寫錯模組名字是最容易犯的錯，而且要等真的跑起來才會發現。"""
    for key, arch in M.ARCHITECTURES.items():
        unknown = [m for m in arch.modules if m not in M.MODULES]
        assert not unknown, f"{key} 用了不存在的模組：{unknown}"
        unknown_builtin = [t for t in arch.builtin_tools if t not in M.BUILTIN_TOOLS]
        assert not unknown_builtin, f"{key} 用了未登記的內建工具：{unknown_builtin}"


def test_every_architecture_has_a_real_policy():
    # 門檻壓在 40 字：只要抓「空的 / 佔位字串」就好。
    # Naive RAG 的 policy 只有 68 字是**刻意的** —— 基準線的重點就是「什麼都不做」，
    # 拿字數當品質指標會誤殺它。
    for key, arch in M.ARCHITECTURES.items():
        assert len(arch.policy.strip()) > 40, f"{key}: policy 太短，等於沒有編排"
        assert arch.paper, f"{key}: 沒有標出處"
        assert arch.orchestration, f"{key}: 沒有標編排型態"


def test_module_source_works_for_everything():
    """軌跡面板要顯示原始碼，任何模組都不能回 fallback 字串。"""
    for name in M.MODULES:
        assert M.module_source(name).lstrip().startswith("def "), name
    for name in M.BUILTIN_TOOLS:
        assert "內建工具" in M.module_source(name), name


def test_unknown_module_is_rejected_not_crashed(ix):
    result = M.run_module("nope", {}, ix)

    assert "error" in result and "nope" in result["error"]


def test_every_module_has_a_stage_and_description():
    """組裝台從 /api/pipeline 拿階段來分車道，architect.write_policy 也靠 stage 描述模組。
    少一個 stage，前端就會有個拖不進任何車道的孤兒 chip、後端會 KeyError。"""
    for name, mod in {**M.MODULES, **M.BUILTIN_TOOLS}.items():
        assert mod.get("stage") in M.STAGE_ORDER, f"{name} 的 stage 不對：{mod.get('stage')}"
        assert mod.get("description", "").strip(), f"{name} 沒有描述"


def test_mcp_tools_reach_allowed_tools_and_only_their_servers(ix):
    """外部 MCP 工具要進 allowed_tools，而且只有**被用到**的 server 會被掛上去。

    掛了沒用到的 server 有兩個代價：連線成本（stdio 要開行程），
    以及偷偷擴大授權 —— agent 看得到一堆這個架構沒打算給它的工具。
    """
    arch = M.Architecture(
        name="接 MCP 的架構", paper="測試", orchestration="Conditional",
        modules=["search"], policy="查不到就問外部。" * 5,
        mcp_tools=["mcp__somewhere__lookup"],
    )
    opts, _ = M.build_options(arch, ix)
    assert "mcp__somewhere__lookup" in opts.allowed_tools
    assert "mcp__ragmod__search" in opts.allowed_tools
    # 沒登記的 server 連不上，所以不會出現在 mcp_servers，但工具名仍在白名單裡 ——
    # 這是刻意的：白名單是架構的宣告，能不能連上是執行期的事
    assert set(opts.mcp_servers) == {"ragmod"}


def test_mcp_tools_are_told_apart_in_the_prompt():
    """外部來源的出處必須跟知識庫分開標，不然使用者分不出哪一句可信。"""
    arch = M.Architecture(
        name="x", paper="y", orchestration="Linear", modules=["search"],
        policy="查一次就好。" * 8, mcp_tools=["mcp__a__b"],
    )
    prompt = arch.system_prompt()
    assert "mcp__a__b" in prompt
    assert "[mcp:" in prompt
