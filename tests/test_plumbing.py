"""供應商、MCP 登記、軌跡、架構師 —— 這四層以前一個測試都沒有。

全部不呼叫 LLM。挑的都是「壞掉會很難發現」的地方：
環境變數沒清乾淨、token 被回給前端、路徑穿越、名字被洗成空字串。
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import architect
import mcp_registry
import providers
import traces


# ══════════ providers ══════════


@pytest.fixture(autouse=True)
def _reset_provider():
    providers.reset()
    yield
    providers.reset()


def test_switching_provider_blanks_the_ones_it_does_not_use():
    """env 是疊在 os.environ 上的，只加不減。

    不把沒用到的清成空字串，切過去之後會被上一個供應商的殘留汙染 ——
    而且那種錯誤超難查，因為它看起來「有設定啊」。
    """
    providers.use("anthropic", {"ANTHROPIC_API_KEY": "sk-test-123456789"})
    env = providers.env_overlay()
    assert env["ANTHROPIC_API_KEY"] == "sk-test-123456789"
    for k in ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK"):
        assert env[k] == "", f"{k} 沒被清掉"
    assert set(env) >= set(providers.MANAGED)


def test_cloud_presets_set_their_flag():
    providers.use("bedrock", {"AWS_REGION": "us-west-2", "ANTHROPIC_MODEL": ""})
    env = providers.env_overlay()
    assert env["CLAUDE_CODE_USE_BEDROCK"] == "1"
    assert env["CLAUDE_CODE_USE_VERTEX"] == ""
    assert env["AWS_REGION"] == "us-west-2"


def test_oauth_means_no_overlay_at_all():
    """預設要完全不動環境 —— 本機 claude 登入狀態才是那個真相。"""
    providers.use("anthropic", {"ANTHROPIC_API_KEY": "x" * 20})
    assert providers.env_overlay()
    providers.use("oauth", {})
    assert providers.env_overlay() == {}
    assert providers.model_override() is None


def test_required_fields_are_enforced():
    with pytest.raises(ValueError, match="還沒填"):
        providers.use("compatible", {"ANTHROPIC_BASE_URL": "http://x"})   # 少 token 和模型


def test_status_never_leaks_the_token():
    secret = "sk-ant-super-secret-value-9999"
    providers.use("anthropic", {"ANTHROPIC_API_KEY": secret})
    shown = json.dumps(providers.status(), ensure_ascii=False)
    assert secret not in shown, "token 被原樣回給前端了"
    assert "…" in shown


# ══════════ mcp_registry ══════════


def test_headers_and_env_are_masked_before_going_to_the_browser():
    """MCP 的 headers 常常放 Bearer token。前端只需要知道「有設定」。"""
    cfg = {"type": "http", "url": "https://x/mcp",
           "headers": {"Authorization": "Bearer super-secret"}}
    safe = mcp_registry._safe_config(cfg)
    assert "super-secret" not in json.dumps(safe, ensure_ascii=False)
    assert safe["headers"]["Authorization"] == "（已設定，不顯示）"
    assert safe["url"] == "https://x/mcp"          # 非機密的照原樣，不然看不出接到哪


def test_only_connected_servers_contribute_tools(tmp_path, monkeypatch):
    """連不上的 server 不該把工具丟進模組庫 —— 拖得進去卻跑不動最惡劣。"""
    store = tmp_path / "mcp.json"
    store.write_text(json.dumps({
        "good": {"config": {"type": "http", "url": "http://a"}, "status": "connected",
                 "tools": ["alpha"], "stage": "Retrieval", "info": {"name": "Good"}},
        "dead": {"config": {"command": "nope"}, "status": "failed",
                 "tools": ["beta"], "stage": "Retrieval", "info": {}},
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(mcp_registry, "STORE", store)

    names = [t["name"] for t in mcp_registry.all_tools()]
    assert names == ["mcp__good__alpha"]
    assert mcp_registry.tool_names("good") == ["mcp__good__alpha"]


# ══════════ traces ══════════


def test_trace_id_cannot_escape_the_trace_folder():
    """id 是我們自己產的，但它會從網址進來。"""
    assert traces._safe("../../etc/passwd") == "etcpasswd"
    assert traces._safe("0914-222029-ff28") == "0914-222029-ff28"
    assert len(traces._safe("x" * 200)) <= 40


def test_recorder_stores_relative_time_not_wall_clock(monkeypatch, tmp_path):
    """存相對毫秒，重播才好按原節奏播 —— 也不會洩漏這份軌跡是什麼時候跑的。"""
    monkeypatch.setattr(traces, "TRACE_DIR", tmp_path)
    rec = traces.Recorder("ask", "測試問題", ["naive"])
    rec.add({"type": "tool_call", "step": 1, "tool": "search"})
    rec.add({"type": "answer", "text": "答案"})
    meta = rec.save()

    saved = json.loads((tmp_path / f"{meta['id']}.json").read_text(encoding="utf-8"))
    assert [e["t"] for e in saved["events"]] == sorted(e["t"] for e in saved["events"])
    assert saved["events"][0]["t"] < 1000        # 相對時間，不是 epoch
    assert meta["calls"] == 1
    assert meta["pinned"] is False


def test_prune_never_touches_pinned(monkeypatch, tmp_path):
    """釘選的是上課要用的那幾份，清理不能碰。"""
    monkeypatch.setattr(traces, "TRACE_DIR", tmp_path)
    monkeypatch.setattr(traces, "KEEP_UNPINNED", 2)
    for i in range(5):
        tid = f"0101-00000{i}-aaaa"
        (tmp_path / f"{tid}.json").write_text(json.dumps({
            "id": tid, "pinned": i == 0, "events": [], "calls": 0, "ms": 0,
        }), encoding="utf-8")

    traces.prune()
    left = {d["id"] for d in traces.listing()}
    assert "0101-000000-aaaa" in left, "釘選的被清掉了"
    assert len(left) == 3                        # 1 份釘選 + 2 份最新的


# ══════════ architect ══════════


def test_slug_keeps_chinese_names():
    """第一版只留 ASCII，全中文的名字會被洗成空字串，key 變成裸的 custom_。"""
    assert architect.slug("客服知識庫用") == "custom_客服知識庫用"
    assert architect.slug("!!!").startswith("custom_")
    assert architect.slug("!!!") != "custom_"


def test_validate_rejects_invented_modules():
    """模型有時候會發明模組。存進去之後才炸，學生會以為是自己弄壞的。"""
    ok, why = architect.validate({
        "name": "x", "policy": "查一次就好。", "modules": ["search", "magic_rerank"],
    })
    assert not ok and "magic_rerank" in why


def test_validate_rejects_mcp_tools_that_are_not_connected(monkeypatch):
    monkeypatch.setattr(mcp_registry, "all_tools", lambda: [])
    ok, why = architect.validate({
        "name": "x", "policy": "查一次就好。", "modules": ["search"],
        "mcp_tools": ["mcp__ghost__thing"],
    })
    assert not ok and "mcp__ghost__thing" in why


def test_json_block_picks_the_architecture_not_any_json():
    reply = """先給你一段設定：

```json
{"unrelated": true}
```

這才是架構：

```json
{"name": "A", "modules": ["search"], "policy": "查一次"}
```
"""
    got = architect._json_block(reply)
    assert got and got["name"] == "A"


def test_a_workflow_with_only_a_builtin_tool_is_legal():
    """只放一顆 WebSearch 也是一個工作流 —— n8n 那種「給了權限就該跑得動」。

    第一版要求 modules 非空，所以畫布上只有 WebSearch 會被擋在門口，
    而且錯誤訊息還說「畫布上還沒有模組」—— 使用者明明看到它在那裡。
    """
    ok, why = architect.validate({
        "name": "只上網查", "policy": "直接用 WebSearch 查，然後回答。",
        "modules": [], "builtin_tools": ["WebSearch"],
    })
    assert ok, why

    ok, why = architect.validate({
        "name": "什麼都沒有", "policy": "亂寫", "modules": [],
    })
    assert not ok and "工具" in why


# ══════════ 圖資料庫 ══════════


def test_cypher_guard_blocks_writes():
    """給 agent 的那個工具只能讀。

    不是信任問題 —— 是 policy 寫錯一個字就可能把教室的資料庫清掉，
    而那個錯誤要到下一堂課才會被發現。
    """
    import graph_store

    for bad in (
        "MATCH (n) DETACH DELETE n",
        "CREATE (n:Chunk {id: 'x'})",
        "MATCH (n) SET n.x = 1",
        "MERGE (n:File {path: 'x'})",
        "CALL apoc.periodic.iterate('MATCH (n) RETURN n', 'DELETE n', {})",
        "LOAD CSV FROM 'file:///x.csv' AS row RETURN row",
        "DROP CONSTRAINT chunk_id",
    ):
        ok, why = graph_store.read_only(bad)
        assert not ok, f"這句應該被擋下來：{bad}"
        assert why

    for good in (
        "MATCH (c:Chunk) RETURN c LIMIT 5",
        "  match (a)-[:SIMILAR]->(b) return a.id, b.id  ",
        "WITH 1 AS x RETURN x",
    ):
        ok, why = graph_store.read_only(good)
        assert ok, f"這句應該放行：{good}（{why}）"


def test_graph_says_so_instead_of_crashing_when_not_configured(monkeypatch):
    """沒接圖不能讓整個系統掛掉 —— 它只是少一個資料源。"""
    import graph_store

    for k in ("NEO4J_URI", "NEO4J_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    assert not graph_store.configured()
    assert graph_store.describe() == {"ok": False, "why": "沒有設定 NEO4J_URI / NEO4J_PASSWORD"}
    assert not graph_store.subgraph()["ok"]


def test_graph_module_returns_an_error_dict_not_an_exception(monkeypatch):
    """模組回錯誤字典，agent 看得懂也能自己換路 —— 丟例外的話整輪問答就死了。"""
    import modules as M

    for k in ("NEO4J_URI", "NEO4J_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    out = M.graph_neighbors(None, "01-hooks.md#0")
    assert "error" in out and "NEO4J_URI" in out["error"]
