"""外部 MCP server：別人寫好的工具，接進來就是這套的模組。

這件事比它看起來重要。我們自己的七個模組本來就是用 `create_sdk_mcp_server`
包成一個叫 `ragmod` 的 MCP server 餵給 SDK 的 —— 也就是說，
**接一個外部 MCP server，跟我們自己寫一個模組，對編排來說是同一件事**：

    mcp__ragmod__search          ← 我們寫的
    mcp__context7__query-docs    ← 別人寫的

policy 裡一樣只是一個名字。這就是 Modular RAG 說的「模組」——
它沒有規定模組要住在哪裡。

探測方式：連一個什麼都不做的 SDK client，只掛這一個 server，
然後輪詢 `get_mcp_status()` 直到它從 pending 變成 connected。
拿到的 tools 清單就是可以拖進畫布的東西。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
STORE = HERE / "mcp.json"          # gitignore 掉：裡面可能有 token
CLAUDE_CONFIG = Path(os.path.expanduser("~/.claude.json"))

PROBE_TIMEOUT_S = 25


def _read() -> dict[str, dict]:
    try:
        return json.loads(STORE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _write(d: dict) -> None:
    STORE.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def configs() -> dict[str, dict]:
    """名字 -> SDK 要的 server config。直接餵給 ClaudeAgentOptions.mcp_servers。"""
    return {k: v["config"] for k, v in _read().items()}


def listing() -> list[dict]:
    """給前端看的。config 裡的 token 一律遮掉。"""
    out = []
    for name, rec in sorted(_read().items()):
        out.append({
            "name": name,
            "config": _safe_config(rec["config"]),
            "status": rec.get("status", "unknown"),
            "info": rec.get("info") or {},
            "tools": rec.get("tools") or [],
            "stage": rec.get("stage", "Retrieval"),
            "error": rec.get("error"),
        })
    return out


def _safe_config(cfg: dict) -> dict:
    out = {k: v for k, v in cfg.items() if k not in ("headers", "env")}
    for k in ("headers", "env"):
        if cfg.get(k):
            out[k] = {kk: "（已設定，不顯示）" for kk in cfg[k]}
    return out


def tool_names(name: str) -> list[str]:
    rec = _read().get(name) or {}
    return [f"mcp__{name}__{t}" for t in (rec.get("tools") or [])]


def all_tools() -> list[dict]:
    """全部已連上的 MCP 工具，長得跟 MODULES 的條目一樣，前端可以直接混著畫。"""
    out = []
    for name, rec in sorted(_read().items()):
        if rec.get("status") != "connected":
            continue
        info = rec.get("info") or {}
        for t in rec.get("tools") or []:
            out.append({
                "name": f"mcp__{name}__{t}",
                "short": t,
                "server": name,
                "stage": rec.get("stage", "Retrieval"),
                "description": f"{info.get('name', name)} 提供的工具。"
                               f"{info.get('description', '')}".strip(),
                "mcp": True,
            })
    return out


async def probe(config: dict) -> dict:
    """連上去問它有哪些工具。連不上就把錯誤原樣回去 —— 這是最常卡住的地方。"""
    import anyio
    from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

    opts = ClaudeAgentOptions(
        tools=[], setting_sources=[], strict_mcp_config=True,
        mcp_servers={"probe": config},
    )
    try:
        async with ClaudeSDKClient(opts) as client:
            with anyio.fail_after(PROBE_TIMEOUT_S):
                while True:
                    st = await client.get_mcp_status()
                    servers = st.get("mcpServers") or []
                    s = servers[0] if servers else {}
                    if s.get("status") != "pending":
                        break
                    await anyio.sleep(1)
    except TimeoutError:
        return {"status": "failed", "error": f"{PROBE_TIMEOUT_S} 秒內沒連上（stdio 指令可能不存在，或網址不通）"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}

    tools = []
    for t in s.get("tools") or []:
        tools.append(t if isinstance(t, str) else t.get("name", ""))
    return {
        "status": s.get("status", "unknown"),
        "error": s.get("error"),
        "info": s.get("serverInfo") or {},
        "tools": [t for t in tools if t],
    }


async def add(name: str, config: dict, stage: str = "Retrieval") -> dict:
    """先探測再存。連不上就不要存 —— 存一個死的 server 只會讓學生以為自己弄壞了。"""
    name = "".join(c for c in name.strip() if c.isalnum() or c in "-_")[:40]
    if not name:
        raise ValueError("server 名字只能用英數字、- 和 _")
    got = await probe(config)
    if got["status"] != "connected":
        raise ValueError(got.get("error") or f"連不上（狀態：{got['status']}）")

    d = _read()
    d[name] = {"config": config, "stage": stage, **got}
    _write(d)
    return listing()


def remove(name: str) -> bool:
    d = _read()
    if name not in d:
        return False
    del d[name]
    _write(d)
    return True


def set_stage(name: str, stage: str) -> bool:
    d = _read()
    if name not in d:
        return False
    d[name]["stage"] = stage
    _write(d)
    return True


def importable() -> list[dict]:
    """你 Claude Code 裡已經裝好的 MCP server，一鍵搬過來。

    只讀 ~/.claude.json 的 mcpServers 那一段，而且只在本機自己的瀏覽器上顯示。
    token 之類的東西照樣遮掉。
    """
    out = []
    try:
        data = json.loads(CLAUDE_CONFIG.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return out
    have = set(_read())
    for name, cfg in (data.get("mcpServers") or {}).items():
        if not isinstance(cfg, dict):
            continue
        out.append({
            "name": name,
            "config": cfg,
            "safe": _safe_config(cfg),
            "already": name in have,
            "kind": cfg.get("type") or ("http" if cfg.get("url") else "stdio"),
        })
    return out
