# 自訂 Slash Commands

Slash command 是使用者主動觸發的指令範本。放在 `.claude/commands/` 底下，
檔名就是指令名稱。

## 最小範例

`.claude/commands/changelog.md`：

```markdown
---
description: 依 git log 更新 CHANGELOG.md
---

看 `git log --oneline -20`，把還沒寫進 CHANGELOG.md 的變更整理成繁體中文條目，
依「新增 / 修正 / 調整」分類，然後更新檔案。
```

打 `/changelog` 就會執行。

## 傳參數

用 `$ARGUMENTS` 接收使用者打在指令後面的文字：

```markdown
---
description: 用繁體中文逐段解釋指定檔案
---

讀 `$ARGUMENTS` 這個檔案，逐段解釋它在做什麼，
解釋完把結果寫進同目錄的 `<檔名>.explained.md`。
```

用法：`/explain retrieval.py`

## 命名空間

放在子資料夾裡的指令會帶上前綴：

```
.claude/commands/db/migrate.md   →  /db:migrate
```

Plugin 提供的指令也會有前綴，例如 `/pr-review-toolkit:review-pr`。

## 什麼時候該用 command 而不是 skill

**用 command**：你希望自己決定何時執行。例如「產週報」「跑發布流程」。

**用 skill**：你希望 Claude 每次遇到某種情況都自動照做。例如「這個專案的 commit 一律用繁中」。

判斷方式很簡單：**如果你會忘記叫它，那就該做成 skill。**
