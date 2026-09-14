# Skills：把做事方法教給 Claude

Skill 是一包「怎麼做某件事」的指示，Claude 判斷情境符合時會自己載入。
它跟 slash command 的差別是：**command 要你主動叫，skill 是它自己判斷要不要用**。

## 檔案結構

```
.claude/skills/<skill-name>/
└── SKILL.md          ← 必要
    references/       ← 選用，放大份的參考資料
    scripts/          ← 選用，放可執行的腳本
```

`SKILL.md` 的開頭是 YAML frontmatter：

```markdown
---
name: commit-zh
description: 當使用者要求 commit、寫 commit message，或執行 git commit 時使用。
             產出繁體中文、不加署名的 commit message。
---

# 怎麼寫這個專案的 commit message

1. 用繁體中文
2. 第一行不超過 50 字，描述「做了什麼」而不是「改了哪些檔案」
3. 不要加 emoji，除非使用者明確要求
4. 不要加任何 AI 署名
```

## description 決定它會不會被觸發

`description` 是 Claude 唯一用來判斷「現在該不該載入這個 skill」的依據。
寫得含糊它就不會觸發。

**寫得好的**：「當使用者要求 commit 變更、寫 commit message，或執行 `git commit` 時使用。
觸發詞：commit、幫我 commit、寫 commit msg」

**寫得差的**：「Git 相關的輔助工具」

要點是**把觸發情境和觸發詞寫進去**，而不是描述這個 skill 有多厲害。

## 漸進式揭露

`SKILL.md` 本身應該精簡 —— 它會被載入上下文。大份的參考資料放 `references/`，
在 SKILL.md 裡指路即可：

```markdown
完整的 API 對照表在 `references/api-table.md`，需要時再讀。
```

這樣平常只花幾百個 token，真的需要細節時才載入。

## Skill 與 Command 與 Sub-agent 的分工

| | 誰決定要用 | 適合 |
|---|---|---|
| Slash command | 使用者主動打 `/xxx` | 明確的一次性動作 |
| Skill | Claude 自己判斷 | 「做這類事情的時候要照這個規矩」 |
| Sub-agent | Claude 決定要不要委派 | 需要獨立 context 的子任務 |
