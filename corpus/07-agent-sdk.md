# Claude Agent SDK

Claude Agent SDK 是**把 Claude Code 包成函式庫**。它不是另一支 API ——
底層會開一個 `claude` CLI 的子行程，用 stdin/stdout 傳 JSON 溝通。

## 它跟其他選項的差別

| | 誰跑 agent loop | 內建工具 | 認證 |
|---|---|---|---|
| Messages API | 你自己寫 while 迴圈 | 沒有 | API key |
| Tool Runner | SDK（只跑你定義的工具） | 沒有 | API key |
| **Agent SDK** | **SDK（完整 Claude Code）** | **Read/Write/Bash/WebSearch…** | **CLI 有什麼就用什麼** |

最後一欄是關鍵：因為它 spawn 的是 CLI，**CLI 讀什麼憑證它就用什麼**。
本機 `claude` 已經登入的話，程式不用設任何 API key 就能跑，走的是訂閱額度。

## 四種認證方式

| 方式 | 怎麼設 |
|---|---|
| 本機已登入 | 什麼都不用做 |
| 長效 OAuth token | `claude setup-token` → `CLAUDE_CODE_OAUTH_TOKEN` |
| 任何 Anthropic 相容端點 | `ANTHROPIC_BASE_URL` + `ANTHROPIC_AUTH_TOKEN` + `ANTHROPIC_MODEL` |
| Anthropic 官方 API | `ANTHROPIC_API_KEY` |

第三種可以接 DeepSeek、Kimi、GLM、OpenRouter，或自架的 LiteLLM proxy。
**程式碼完全一樣，只有環境變數不同。**

## 兩個入口

`query()` 是一次性的：

```python
from claude_agent_sdk import query, ClaudeAgentOptions, AssistantMessage, TextBlock

async for message in query(prompt="你好", options=ClaudeAgentOptions(tools=[])):
    if isinstance(message, AssistantMessage):
        for block in message.content:
            if isinstance(block, TextBlock):
                print(block.text)
```

`ClaudeSDKClient` 可以在同一個 session 裡連續問：

```python
async with ClaudeSDKClient(options=options) as client:
    await client.query("第一個問題")
    async for msg in client.receive_response():
        ...
    await client.query("接著問")          # 有前面的上下文
```

## 用 hook 看見 agent 在做什麼

```python
from claude_agent_sdk import HookMatcher

async def on_pre_tool(data, tool_use_id, context):
    print("呼叫", data["tool_name"], data["tool_input"])
    return {}          # 回 {} 代表放行

options = ClaudeAgentOptions(
    hooks={"PreToolUse": [HookMatcher(hooks=[on_pre_tool])]},
)
```

Hook callback 的簽名固定是 `(input, tool_use_id, context)`。

**模型會平行呼叫多個工具**，所以要對應「呼叫」和「結果」時，
必須用 `tool_use_id`，不能用遞增計數器 —— 結果回來的順序不保證。

## 把 agent 關進安全的小房間

```python
ClaudeAgentOptions(
    tools=[],                    # 關閉所有內建工具
    strict_mcp_config=True,      # 忽略專案的 .mcp.json
    setting_sources=[],          # 不載入專案的 CLAUDE.md 與 hooks
    permission_mode="bypassPermissions",
)
```

最後一行看起來危險，但配上第一行就是安全的 —— 沒有工具可以被濫用。
