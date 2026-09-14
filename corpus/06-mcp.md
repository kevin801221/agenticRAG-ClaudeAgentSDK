# MCP：把外部工具接進來

MCP（Model Context Protocol）是讓 Claude 存取外部系統的標準協定。
一個 MCP server 提供一組工具，Claude 就能呼叫它們。

## 三種傳輸方式

| 型態 | 怎麼跑 | 適合 |
|---|---|---|
| `stdio` | Claude 開一個子行程，用標準輸入輸出溝通 | 本機工具、CLI 包裝 |
| `http` | 連到一個 HTTP 端點 | 遠端服務、團隊共用 |
| `sse` | Server-Sent Events（較舊） | 舊的遠端服務 |

設定寫在 `.mcp.json`（專案層級）或使用者設定裡：

```json
{
  "mcpServers": {
    "sqlite": {
      "command": "uvx",
      "args": ["mcp-server-sqlite", "--db-path", "./app.db"]
    }
  }
}
```

## 工具名稱會被加上前綴

MCP 工具在 Claude 眼中的名字是 `mcp__<server 名>__<工具名>`。
所以上面那個 server 如果提供 `query` 工具，完整名稱就是 `mcp__sqlite__query`。

寫 `allowed_tools` 的時候要用**完整名稱**，這是很常見的踩雷點。

## In-process MCP server（Agent SDK 專用）

用 Agent SDK 的時候不需要真的開一個 server 行程 ——
可以把 Python 函式直接包成工具，跑在同一個程序裡：

```python
from claude_agent_sdk import tool, create_sdk_mcp_server

@tool("add", "把兩個數字相加", {
    "type": "object",
    "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
    "required": ["a", "b"],
})
async def add(args):
    return {"content": [{"type": "text", "text": str(args["a"] + args["b"])}]}

server = create_sdk_mcp_server("calc", "1.0.0", [add])
```

然後掛上去：

```python
ClaudeAgentOptions(
    mcp_servers={"calc": server},
    allowed_tools=["mcp__calc__add"],
    strict_mcp_config=True,      # 忽略專案的 .mcp.json，只用這裡給的
)
```

好處是沒有行程啟動成本、可以直接存取程式裡的變數（例如已經載入記憶體的索引）。

## 工具描述決定它會不會被正確使用

模型只看得到工具的 `description` 和 JSON schema。
描述寫得含糊，它就會亂用或不用。

寫描述時要包含：**這個工具做什麼、什麼時候該用、回傳什麼、失敗會怎樣**。
