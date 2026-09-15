# 自訂架構

這裡放**用系統組出來的**架構。三種做法都會存到這裡：

- 主畫面「讓 agent 幫我組一個」—— 聊出來的
- `/studio` 畫布 —— 拖出來的
- 手寫一份 JSON

## 格式

```json
{
  "name": "顯示在選單上的名字",
  "orchestration": "Linear | Conditional | Branching | Looping（可加括號說明）",
  "modules": ["search", "grade_documents"],
  "builtin_tools": ["WebSearch"],
  "mcp_tools": ["mcp__context7__query-docs"],
  "max_turns": 12,
  "policy": "這份架構的靈魂。什麼時候用哪個模組、判斷條件、失敗了怎麼辦、出處怎麼標。",
  "why": "為什麼這樣設計",
  "graph": { "nodes": [...], "edges": [...] }
}
```

`graph` 是選填的，只有在 Studio 上畫過才有。沒有的話，Studio 會把 `policy`
讀成一張圖再畫出來 —— **policy 才是真的會被執行的東西，圖只是它的樣子。**

放進來的檔案啟動時會自動載入；`validate()` 擋掉用了不存在模組的檔案，
壞掉的那一份會被跳過，不會擋住整個啟動。

## 自己實驗的放哪

`architectures/local/`（已 gitignore）。這裡的東西會進 git，
所以請只留下**你願意讓別人照著學**的那幾份。
