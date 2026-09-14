"""兩個 engine，同一份工具、同一份事件格式。

engine 是可替換的實作，`tools.py` 與事件格式才是契約。
換 engine 不動 tools.py、不動 retrieval.py、不動前端 —— 這個邊界本身是教學重點。
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from retrieval import Index

Emit = Callable[[dict], None]

# 注意：system prompt 與 max_turns 現在屬於 Architecture（見 modules.py），
# 不再是全域設定 —— 因為不同架構的編排規則本來就不一樣。


def get_engine(name: str) -> Callable[..., Awaitable[None]]:
    if name == "agent_sdk":
        from engines.agent_sdk import run

        return run
    if name == "litellm":
        from engines.litellm_loop import run

        return run
    raise SystemExit(f"ENGINE 只能是 agent_sdk 或 litellm，收到 {name!r}")


def describe_engine(name: str) -> str:
    """給 /api/health 與前端狀態列看的一行說明。"""
    if name == "agent_sdk":
        if os.getenv("ANTHROPIC_BASE_URL"):
            return f"Claude Agent SDK → {os.getenv('ANTHROPIC_BASE_URL')}"
        if os.getenv("ANTHROPIC_API_KEY"):
            return "Claude Agent SDK → Anthropic API key"
        return "Claude Agent SDK → OAuth 訂閱（無 API 費用）"
    return f"litellm → {os.getenv('LLM_MODEL', '未設定')}"


def check_config(name: str) -> None:
    """啟動時就把設定問題講清楚，不要等到使用者問第一個問題才爆。"""
    if name == "agent_sdk":
        has_auth = any(
            os.getenv(k)
            for k in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY")
        )
        if not has_auth:
            # 不硬擋：本機 claude CLI 已經登入的話，SDK 會直接沿用那組憑證。
            # 真的沒有憑證時，第一個問題會在畫面上回報 SDK 的錯誤。
            print(
                "[note] .env 沒有設任何認證。若這台機器的 claude CLI 已登入就會直接沿用；\n"
                "否則四選一：\n"
                "  (0) claude login                  ← 本機登入一次即可\n"
                "  (1) CLAUDE_CODE_OAUTH_TOKEN=...   ← 推薦，跑 claude setup-token，用訂閱不計費\n"
                "  (2) ANTHROPIC_BASE_URL + ANTHROPIC_AUTH_TOKEN + ANTHROPIC_MODEL\n"
                "      （任何 Anthropic 相容端點：DeepSeek / Kimi / GLM / OpenRouter / LiteLLM proxy）\n"
                "  (3) ANTHROPIC_API_KEY=...         ← Anthropic 官方 API，會計費\n"
                "\n完全不想用 Claude 的話：ENGINE=litellm + LLM_MODEL=ollama/qwen3（免費離線）"
            )
    elif name == "litellm":
        if not os.getenv("LLM_MODEL"):
            raise SystemExit(
                "ENGINE=litellm 需要 LLM_MODEL，例如：\n"
                "  LLM_MODEL=ollama/qwen3          ← 本地跑，不需要任何 key\n"
                "  LLM_MODEL=gemini/gemini-3-pro   ← 需要 GEMINI_API_KEY\n"
                "  LLM_MODEL=openai/gpt-5          ← 需要 OPENAI_API_KEY"
            )
