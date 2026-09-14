# Sub-agents 與 Agent Teams

兩個聽起來很像但完全不同的東西。

## Sub-agent：主對話派出去的分身

Sub-agent 是主 Claude 用 Task 工具生出來的**子代理**。它有自己的上下文視窗，
做完事情只把**結論**回報給主對話。

```
主對話
  ├─ Task → sub-agent A（自己的 context）→ 回報結論
  └─ Task → sub-agent B（自己的 context）→ 回報結論
```

**最大的價值是省 context。** 例如叫 sub-agent 去讀 30 個檔案找某個函式，
它讀掉的 30 個檔案不會佔用主對話的視窗，主對話只收到一句「在 `retrieval.py:88`」。

定義方式是在 `.claude/agents/` 放一個 markdown 檔：

```markdown
---
name: code-reviewer
description: 審查程式碼變更，找出 bug 與可簡化處
tools: Read, Grep, Glob
model: sonnet
---

你是一位資深工程師，專門審查 diff。只回報真正的問題，不要挑風格。
```

**限制：sub-agent 之間不能互相講話。** 它們各自獨立，只跟主對話溝通。

## Agent Team：多個獨立實例平行工作

Agent team 是 team lead 生出來的**獨立 Claude Code 實例**，
它們共享一張任務清單和一個信箱，**可以直接互傳訊息、對齊契約**。

| | Sub-agent | Agent team |
|---|---|---|
| 誰生的 | 主對話 | team lead |
| 彼此能溝通 | 不行 | 可以 |
| 有沒有獨立工作區 | 沒有 | 通常配合 git worktree |
| 適合 | 一次性的委派任務 | 需要協調的平行開發 |
| 成本 | 較低 | 較高 |

## 什麼時候用哪個

**用 sub-agent**：任務可以獨立完成、只需要結論、想省主對話的 context。
例如「找出所有呼叫這個函式的地方」「審查這份 diff」。

**用 agent team**：多個人要同時改一個系統的不同部分，而且彼此有介面依賴。
例如「一個做後端 API、一個做前端、一個做動畫，三邊要對齊資料格式」。

Agent team 的關鍵是**先凍結規格與 API 契約再開工**，
否則平行做出來的東西合不起來，省下的時間全部還回去。
