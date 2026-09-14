# Permissions：另一套「擋東西」的機制

Claude Code 有兩套獨立的阻擋機制，寫在同一個 `settings.json` 裡，互不干涉。
搞混這兩個是新手最常見的誤解。

## Hook 與 Permission 的差別

| | Hook | Permission |
|---|---|---|
| 判斷方式 | 執行一支腳本，看 exit code | 比對規則字串 |
| 能不能做複雜判斷 | 可以（任意程式邏輯） | 不行（只有模式比對） |
| 速度 | 要開行程，較慢 | 極快 |
| 會不會問使用者 | 不會，直接擋 | 可以設成詢問 |
| 適合什麼 | 需要看內容才能決定的規則 | 一眼就能判斷的黑白名單 |

簡單說：**能寫成規則字串的用 permission，需要看內容才能決定的用 hook。**

## 三個區塊：allow / deny / ask

```json
{
  "permissions": {
    "allow": [
      "Bash(git status)",
      "Bash(git diff:*)",
      "Read(**)"
    ],
    "deny": [
      "Bash(rm -rf:*)",
      "Read(.env)",
      "Write(/Users/**/.ssh/**)"
    ],
    "ask": [
      "Bash(git push:*)"
    ]
  }
}
```

- **allow** — 不用問就能執行
- **deny** — 直接拒絕，連問都不問
- **ask** — 每次都問使用者

規則格式是 `工具名稱(參數模式)`，`*` 是萬用字元，`:*` 代表「這個指令開頭的任何參數」。

## Permission modes

除了規則清單，整個 session 還有一個模式：

| 模式 | 行為 |
|---|---|
| `default` | 照規則走，沒規則的就問 |
| `acceptEdits` | 檔案編輯自動同意，其他照問 |
| `plan` | 唯讀，不能改任何東西 |
| `bypassPermissions` | 全部放行（只在沙箱或工具已受限時用） |

## 一個容易誤解的地方

在 Agent SDK 裡，`allowed_tools` **不等於**「只能用這些工具」。
它是「不用問就能用」的白名單 —— 沒列出來的工具仍然存在，只是會觸發詢問。

要真正把工具**關掉**，用 `tools` 參數：

```python
ClaudeAgentOptions(
    tools=[],                      # 關閉所有內建工具
    allowed_tools=["mcp__x__y"],   # 這些不用問
)
```

`tools=[]` 之後 Bash / Write / Read 根本不存在，這時候再開 `bypassPermissions` 才是安全的。
