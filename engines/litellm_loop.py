"""engine：自己寫的 agent loop（接 litellm，可用任何 provider）。

存在的理由有兩個：
1. 你不想用 Anthropic —— 這條接 OpenAI / Gemini / Groq / Ollama / 任何 litellm 支援的模型。
2. 教學 —— agentic RAG 的本質就是「while 迴圈 + 工具」，不是黑魔法。
   把這支跟 agent_sdk.py 擺在一起看，就知道 SDK 到底幫你做了什麼。

差別：SDK 那邊 loop、context、結果回填、重試都是免費的；這裡全部要自己寫。
另外這條拿不到結構化 thinking，所以理由欄是靠 system prompt 要求模型
「呼叫工具前先講一句為什麼」，再把那句話當 reasoning 事件送出去。
"""

from __future__ import annotations

import json
import os
import time

from engines import Emit
from retrieval import Index
from modules import ARCHITECTURES, Architecture, MODULES, module_source, run_module


async def run(question: str, ix: Index, emit: Emit, arch: Architecture | None = None) -> None:
    import litellm

    arch = arch or ARCHITECTURES["modular"]

    litellm.drop_params = True  # 不同 provider 支援的參數不同，讓 litellm 自己刪掉不支援的

    model = os.getenv("LLM_MODEL", "")
    started = time.time()
    step = 0

    messages = [
        {"role": "system", "content": arch.system_prompt()},
        {"role": "user", "content": question},
    ]
    tools = [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": MODULES[name]["description"],
                "parameters": MODULES[name]["schema"],
            },
        }
        for name in arch.modules
        if name in MODULES
    ]
    answer = ""

    for _ in range(arch.max_turns):
        response = await litellm.acompletion(model=model, messages=messages, tools=tools)
        choice = response.choices[0].message
        messages.append(choice.model_dump())

        # 模型在呼叫工具之前寫的那句話 = 它選這個策略的理由
        if choice.content and choice.content.strip():
            emit({"type": "reasoning", "text": choice.content.strip()})

        calls = choice.tool_calls or []
        if not calls:
            answer = (choice.content or "").strip()
            break

        for call in calls:
            step += 1
            name = call.function.name
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}

            emit(
                {
                    "type": "tool_call",
                    "step": step,
                    "tool": name,
                    "args": args,
                    "source": module_source(name),
                }
            )

            result = run_module(name, args, ix)
            emit({"type": "tool_result", "step": step, "tool": name, **_summarize(result)})

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "name": name,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )
    else:
        emit(
            {
                "type": "error",
                "text": f"跑滿 {arch.max_turns} 輪還沒收斂，用手上已有的資料作答",
                "fatal": False,
            }
        )

    emit({"type": "answer", "text": answer or "（沒有產生答案，看看右邊軌跡卡在哪一步）"})
    emit({"type": "done", "turns": step, "elapsed_ms": int((time.time() - started) * 1000)})


def _summarize(payload: dict) -> dict:
    if "error" in payload:
        return {"summary": f"失敗：{payload['error']}", "detail": payload}
    if "results" in payload:
        n = len(payload["results"])
        top = payload["results"][0]["score"] if n else 0
        extra = "（降級為 BM25）" if payload.get("degraded") else ""
        return {"summary": f"{n} 筆，最高分 {top}{extra}", "detail": payload}
    if "chunks" in payload:
        return {"summary": f"取回 {len(payload['chunks'])} 塊完整內文", "detail": payload}
    if "total_chunks" in payload:
        return {
            "summary": f"{payload['total_chunks']} 片段 / {payload['total_files']} 檔案",
            "detail": payload,
        }
    return {"summary": "完成", "detail": payload}
