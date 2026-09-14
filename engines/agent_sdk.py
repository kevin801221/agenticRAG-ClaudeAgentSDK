"""engine：Claude Agent SDK（預設）。

這支很薄 —— 真正的內容在 modules.py：模組庫 + Architecture + build_options。
網頁只是把某一個 Architecture 跑起來、把事件串到瀏覽器而已。

換句話說：**這個網頁就是 notebook 02 的其中一格，加了個畫面。**

認證四選一（程式碼完全相同，只差環境變數）：
  本機已登入的 claude CLI / CLAUDE_CODE_OAUTH_TOKEN
  ANTHROPIC_BASE_URL + ANTHROPIC_AUTH_TOKEN   ← 任何 Anthropic 相容端點
  ANTHROPIC_API_KEY
"""

from __future__ import annotations

import time

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
    ThinkingBlock,
)

from engines import Emit
from modules import ARCHITECTURES, Architecture, build_options
from retrieval import Index


async def run(question: str, ix: Index, emit: Emit, arch: Architecture | None = None) -> None:
    arch = arch or ARCHITECTURES["modular"]
    started = time.time()

    options, step = build_options(arch, ix, emit)

    # 每段文字延後一拍才送 —— 最後那段是答案，要留給答案欄，不能也塞進軌跡
    pending: str | None = None
    async with ClaudeSDKClient(options=options) as client:
        await client.query(question)
        async for msg in client.receive_response():
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, ThinkingBlock) and block.thinking.strip():
                        emit({"type": "reasoning", "text": block.thinking.strip()})
                    elif isinstance(block, TextBlock) and block.text.strip():
                        if pending:
                            emit({"type": "reasoning", "text": pending})
                        pending = block.text.strip()
            elif isinstance(msg, ResultMessage):
                break

    emit({"type": "answer", "text": pending or "（沒有產生答案，看看右邊的軌跡是哪一步卡住）"})
    emit(
        {
            "type": "done",
            "turns": step["n"],
            "elapsed_ms": int((time.time() - started) * 1000),
            "architecture": arch.name,
        }
    )
