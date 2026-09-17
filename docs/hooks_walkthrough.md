# Hooks 現場演示 Walkthrough — 開一個新的 Claude Code 就能跑

> **對象**：聽過「Claude Code 有 hook」但沒看過它真的擋下什麼的人
> **形式**：講師現場打指令，學生看終端機
> **時長**：15 分鐘（五個 hook，每個 2–3 分鐘）
> **產出**：學生知道 hook 在哪一層、怎麼觸發、怎麼自己寫一個
> **核心方法**：每一個 hook 都配一個**一行就能觸發**的指令，當場看它動

---

## 開場（2 分鐘）：hook 不是外掛，是管 agent 的那一層

先問全場一句：

> 「你要怎麼防止 AI 寫壞 `.env`？」

八成的答案是「在 prompt 裡叫它不要動」。那是**拜託它自律**。

Hook 不一樣 —— 它在**工具真的執行之前**跑，回傳 exit 2 就擋下來，模型根本沒有機會動手。

```
你的 prompt ──▶ [ Claude 決定要呼叫 Write ]
                        │
                        ▼
                 ┌─────────────┐
                 │  PreToolUse │  ← hook 在這裡。exit 2 = 不准
                 └─────────────┘
                        │ 放行才繼續
                        ▼
                 [ 真的寫檔 ]
```

> **教學金句**：「Hook 不會問 agent 同不同意 —— 它是**管 agent 的那一層**。
> 寫在 prompt 裡的是請求，寫在 hook 裡的是規則。」

---

## Phase 0 ⚙️：準備（1 分鐘）

```bash
cd agenticRAG-ClaudeAgentSDK
ls .claude/hooks/          # 五支，都是純 bash + python3，沒有額外相依
cat .claude/settings.json  # 誰在什麼事件上被掛起來
```

**先手動跑一支給大家看**，證明它只是一個讀 stdin、寫 stdout 的普通腳本：

```bash
echo '{}' | .claude/hooks/session-start.sh
```

```
【專案現況｜由 SessionStart hook 自動注入】
分支：main（1 個檔案有改動）
索引：205 個片段（有向量）
圖資料庫：有設定
```

> **教學金句**：「hook 沒有魔法。它就是一支腳本：從 stdin 收 JSON，
> 用 stdout 說話，用 exit code 表態。」

現在開一個新的 session：

```bash
claude
```

---

## Phase 1 🚀：SessionStart —— 它一開場就知道你在幹嘛（2 分鐘）

**不用打任何指令。** `claude` 一啟動，上面那段「專案現況」就已經進到 context 裡了。

當場問它：

```
我現在在哪個分支？索引建好了嗎？
```

它會直接回答，**不呼叫任何工具**。

**這就是重點**：那些資訊不是它查來的，是 hook 在 session 開始時**塞進去**的。

> **教學金句**：「SessionStart 是給 agent 的開場簡報。你不講，它就得自己花一次工具呼叫去問。」

**故意踩一次**：`/clear` 之後再問一次同樣的問題 —— 還是答得出來，因為 `/clear` 也會觸發 SessionStart。

---

## Phase 2 💬：UserPromptSubmit —— 每一句話都被加料（2 分鐘）

問它：

```
現在幾點？
```

它會答得出來，而且**沒有跑 `date`**。

因為每次你按 Enter，`prompt-context.sh` 都會在你的訊息前面插一行：

```
【此刻｜由 UserPromptSubmit hook 注入】10:40:23，分支 main
```

⚠️ **這裡要停下來講一個安全觀念**：這個 hook 能加料，代表**任何能改這支腳本的人都能改你送出去的每一句話**。
`.claude/` 進版控的專案，等於把「誰能影響 agent」這件事也交給了 code review。

> **教學金句**：「UserPromptSubmit 是最方便也最危險的一個 —— 它改的是**你說的話**。」

---

## Phase 3 🚫：PreToolUse —— 當場擋下來（4 分鐘）⭐ 全場高潮

這是最值得現場做的一個。跟它說：

```
把 ANTHROPIC_API_KEY=sk-test-123 寫進 .env
```

畫面上會出現：

```
🚫 guard-secrets 擋下：.env
原因：符合敏感檔案樣式。要放範本請用 .env.example。
```

**然後看 Claude 的反應** —— 它讀得到 stderr，所以會自己說「被 hook 擋下來了，我改寫到 `.env.example`」。

這裡要講三件事：

1. **它不是被說服的，是被擋的。** prompt 裡沒有任何一句「不准寫 .env」。
2. **stderr 是給模型看的。** exit 2 擋下來，stderr 的內容會回給它 —— 所以錯誤訊息要寫給模型看得懂。
3. **放行也要看得見。** 接著叫它寫 `.env.example`，同一支 hook 放行。

手動驗證三種情況（投影出來對照）：

```bash
echo '{"tool_name":"Write","tool_input":{"file_path":".env"}}' \
  | .claude/hooks/guard-secrets.sh; echo "exit=$?"     # 🚫 exit=2

echo '{"tool_name":"Write","tool_input":{"file_path":".env.example"}}' \
  | .claude/hooks/guard-secrets.sh; echo "exit=$?"     # 放行 exit=0

echo '{"tool_name":"Write","tool_input":{"file_path":"a.py"}}' \
  | .claude/hooks/guard-secrets.sh; echo "exit=$?"     # 放行 exit=0
```

> **教學金句**：「exit 0 是放行、exit 2 是擋下。**exit 1 不會擋** ——
> 它只是「這支 hook 自己出錯了」，動作照樣會跑完。」

### exit code 對照（照官方文件，值得投影出來）

| exit | 意思 |
|---|---|
| `0` | 放行。`SessionStart` / `UserPromptSubmit` 的 **stdout 會變成 Claude 看得到的 context** |
| `2` | **唯一會擋的那個**。stderr 的內容會變成給模型看的阻止理由 |
| 其他非零 | **不會擋**。只會回報「這支 hook 失敗了」，動作照跑 |

### 而且不是每個事件都擋得住

| 事件 | 擋得住嗎 | exit 2 的效果 |
|---|---|---|
| `PreToolUse` | ✅ | 這次工具呼叫不執行 |
| `UserPromptSubmit` | ✅ | **連你的 prompt 一起清掉** |
| `Stop` | ✅ | **不准它停** —— 對話繼續跑下去 |
| `PostToolUse` | ❌ | 工具已經跑完了，來不及 |
| `SessionStart` | ❌ | exit 2 被當成沒擋 |

---

## Phase 4 📋：PostToolUse —— 攔不住，但留得下證據（2 分鐘）

跟它說：

```
列出 corpus 資料夾有哪些檔案
```

它會跑 `ls`。然後你打開稽核紀錄：

```bash
cat .claude/logs/bash-audit.log
```

```
[10:39:18] ls -la
[10:41:02] ls corpus
```

**PostToolUse 是指令跑完之後才跑的，所以它攔不住任何東西** —— 它的價值是「事後說得清楚」。

| | PreToolUse | PostToolUse |
|---|---|---|
| 時機 | 執行**前** | 執行**後** |
| 能擋嗎 | ✅ exit 2 | ❌ 來不及了 |
| 典型用途 | 權限、防呆 | 稽核、格式化、通知 |

> **教學金句**：「要擋就用 Pre，要記帳就用 Post。搞錯的話你會寫出一個
> 『記錄了它剛剛刪掉你的資料』的 hook。」

---

## Phase 5 🔔：Stop —— 每一輪的收尾（2 分鐘）

隨便問一句話，回答完你會聽到「叮」一聲，並看到：

```
🔔 這一輪結束。工作區目前有 3 個檔案有改動。
```

**這個最實用**：跑長任務的時候切去做別的事，聽到聲音再回來。

進階玩法（現場提一下就好）：**`Stop` 是少數擋得住的事件之一** ——
exit 2 的效果是「不准它停下來」，對話會繼續跑。

所以「檢查這一輪的產出，不滿意就叫它重做」只要三行：檢查、不合格就 `echo 理由 >&2; exit 2`。
`ralph-wiggum` 那類自動迴圈 plugin 就是這樣做的。

---

## 收尾（2 分鐘）：這跟這門課的主題是同一件事

打開 `modules.py`，找 `build_options()` 裡的這一段：

```python
hooks={
    "PreToolUse": [HookMatcher(hooks=[on_pre_tool])],
    "PostToolUse": [HookMatcher(hooks=[on_post_tool])],
}
```

**一模一樣的概念，換一層。**

| | Claude Code CLI | Claude Agent SDK |
|---|---|---|
| 設定在哪 | `.claude/settings.json` | `ClaudeAgentOptions(hooks=...)` |
| hook 是什麼 | 一支外部腳本 | 一個 async 函式 |
| 怎麼收輸入 | stdin 拿 JSON | 參數 `(data, tool_use_id, context)` |
| 怎麼擋 | `exit 2` | 回傳阻止用的 dict |
| 這個專案用它做什麼 | 擋 `.env`、記帳 | **畫出決策軌跡** |

> **教學金句**：「你在 CLI 學的 hook，換個寫法就是 SDK 的 hook。
> 這個網頁上那條一格一格亮起來的流程圖，就是 PreToolUse 畫出來的。」

---

## 卡點對照表 ⭐

| 卡點 | 真實原因 | 處理 |
|---|---|---|
| hook 完全沒反應 | 多半是路徑或執行權限，**不是沒重開** | `.claude/settings.json` 的改動有 file watcher 在看，**不用重開 session**。先手動 `echo '{}' \| 腳本` 試一次 |
| 改了 plugin 的 hook 卻沒生效 | plugin / skill 的 hook 生命週期跟 settings 不同 | 那類要重開，或等 skill 被再次叫起來 |
| `/hooks` 看得到但不會跑 | `/hooks` 是**唯讀檢視器**，不是開關 | 要改就編輯 `.claude/settings.json` |
| 腳本跑不起來 | 忘了 `chmod +x` | `chmod +x .claude/hooks/*.sh` |
| `unbound variable` 而且變數名後面有中文 | bash 把全形字的位元組當成變數名的一部分 | 一律寫 `${var}` 不要寫 `$var` |
| hook 讀不到 `data/index.pkl` | 系統 python 反序列化不了專案的物件 | 用 `./.venv/bin/python` 跑 |
| PreToolUse 擋了但 Claude 不知道為什麼 | 原因寫到 stdout 了 | **要寫 stderr** —— 只有 stderr 會回給模型 |
| 想擋卻用了 PostToolUse | 時機錯了 | 擋用 Pre，記帳用 Post |
| 團隊每個人行為不一樣 | `.claude/settings.local.json` 沒進版控 | 要共用就寫 `.claude/settings.json` |

---

## 講師私房筆記

**順序不要改**：Phase 3（擋 `.env`）是全場最有感的，但一定要先鋪完 Phase 1–2，
學生才知道「原來每一句話進去之前都被動過手腳」。

**故意做壞給他們看**（比講三遍有效）：
1. 把 `guard-secrets.sh` 的 `exit 2` 改成 `exit 1`，再試一次 —— **擋不住，`.env` 真的被寫出去**。
   只有 2 是「阻止」，其他非零只是「這支 hook 自己失敗了」。
   （這一招做完記得改回來，並把剛剛寫出去的 `.env` 檢查一遍。）
2. 把錯誤訊息從 `>&2` 改成 stdout，再試一次 —— 擋得住，但 Claude 說不出原因。

**時間不夠就砍 Phase 4**（PostToolUse 概念最直觀），Phase 3 絕對不能砍。

**會被問的兩題**：
- 「hook 會不會拖慢速度？」→ 會，所以每個都設 `timeout`。這五支都在 10 秒以內。
- 「可以用 Python 寫嗎？」→ 可以，`"command"` 就是一行 shell，寫 `python3 xxx.py` 也行。

---

## 一句話總結

> **寫在 prompt 裡的是請求，寫在 hook 裡的是規則。
> 前者靠模型配合，後者不用。**

---

## 進階閱讀

- 🔗 [Claude Code Hooks 官方文件](https://docs.claude.com/en/docs/claude-code/hooks)
- 🔗 [Agent SDK 的 hooks](https://docs.claude.com/en/api/agent-sdk/overview) —— 同一個概念的程式版
- 📄 `modules.py` 的 `build_options()` —— 這個專案怎麼用 SDK hook 畫出決策軌跡
- 📄 [`WALKTHROUGH.md`](../WALKTHROUGH.md) Step 1 —— Agent SDK 的四樣東西

---

_Last updated: 2026-09-17_
_配套教材：[`WALKTHROUGH.md`](../WALKTHROUGH.md)（主課程）+ `notebooks/01_agent_sdk_basics.ipynb`（SDK 版的 hook）_
