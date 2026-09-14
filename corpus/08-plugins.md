# Plugins 與 Marketplace

Plugin 是把 commands、agents、skills、hooks、MCP server 打包成一份可安裝的東西。

## 目錄結構

```
my-plugin/
├── .claude-plugin/
│   └── plugin.json      ← 必要，描述這個 plugin
├── commands/
├── agents/
├── skills/
├── hooks/
└── .mcp.json
```

`plugin.json` 最小內容：

```json
{
  "name": "my-plugin",
  "description": "一句話說明它幹嘛",
  "version": "0.1.0"
}
```

## Marketplace

Marketplace 就是一個列出多個 plugin 的 repo，根目錄要有
`.claude-plugin/marketplace.json`：

```json
{
  "name": "my-marketplace",
  "plugins": [
    { "name": "my-plugin", "source": "./my-plugin" }
  ]
}
```

安裝流程：

```
/plugin marketplace add <github-user>/<repo>
/plugin install my-plugin@my-marketplace
```

## ~/.claude/plugins/ 是誰的地盤

`~/.claude/plugins/` 是 **Claude Code 自動管理**的安裝區，不是給你手動放東西的：

- `marketplaces/` — 加過的 marketplace
- `data/` — 已安裝 plugin 的實際檔案
- `cache/` — metadata 快取
- `installed_plugins.json` — 狀態檔

**開發 plugin 的原始碼要放在自己的 repo**，不要塞進這個資料夾 ——
它隨時會被 Claude Code 覆寫。

開發時用 `--plugin-dir` 指向本機目錄測試，不用先發布。
