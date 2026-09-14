# Hooks：用程式碼焊死流程

Hook 是 Claude Code 在特定事件發生時自動執行的 shell 指令。
它不是給 Claude 的建議，而是**管 Claude 的 harness** —— Claude 沒有辦法忽略它。

## Hook 事件一覽

| 事件 | 什麼時候觸發 | 典型用途 |
|---|---|---|
| `PreToolUse` | 工具真正執行**之前** | 阻止危險操作、注入額外脈絡 |
| `PostToolUse` | 工具執行**之後** | 自動格式化、跑測試、記錄稽核軌跡 |
| `UserPromptSubmit` | 使用者送出訊息時 | 強制訊息格式、附加專案狀態 |
| `Stop` | 一輪對話結束 | 桌面通知、自動 commit、迴圈觸發 |
| `SubagentStop` | 子代理結束時 | 收集子代理產出 |
| `PreCompact` | 壓縮上下文之前 | 保存即將被壓掉的資訊 |
| `Notification` | Claude 發出通知時 | 轉發到 Slack 或其他管道 |

## 用 exit code 控制流程

Hook 腳本的**離開碼決定 Claude 接下來能不能繼續**：

| exit code | 意義 | Claude 會怎樣 |
|---|---|---|
| `0` | 通過 | 照常執行工具 |
| `2` | **阻止** | 工具不會執行，stderr 的內容回傳給 Claude 當理由 |
| 其他非零 | 錯誤 | 記錄錯誤，但不阻止 |

關鍵在 `exit 2`：它不只是擋下來，還會把你寫在 stderr 的訊息**餵回給模型**，
所以模型看得到「為什麼被擋」，然後自己改走別條路。

## 範例：擋住寫入 .env 與其他敏感檔案

`.claude/hooks/guard-secrets.sh`：

```bash
#!/usr/bin/env bash
# PreToolUse hook：阻止寫入敏感檔案
payload=$(cat)
path=$(echo "$payload" | python3 -c "import sys,json;print(json.load(sys.stdin).get('tool_input',{}).get('file_path',''))")

case "$path" in
  *.env|*.pem|*credentials.json|*id_rsa*)
    echo "拒絕寫入敏感檔案 $path。請改寫 .env.example，並把真實值交給使用者自己填。" >&2
    exit 2
    ;;
esac
exit 0
```

記得 `chmod +x`。

## 光放在資料夾不會生效，要註冊

Hook 必須寫進 `.claude/settings.json` 才會被載入：

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Write|Edit|MultiEdit",
        "hooks": [
          {
            "type": "command",
            "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/guard-secrets.sh",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

`matcher` 是工具名稱，可以用 `|` 串多個。改完設定要**重開 session** 才會生效 ——
這是最常卡住的地方。

## 寫 hook 的三個原則

**stderr 的訊息是寫給 AI 看的，不是寫給人看的 log。** Claude 靠讀那段文字決定改走哪條路，
所以要寫成「你應該改做什麼」，而不是「ERROR: permission denied」。

**阻止型 hook 要短、要快、不要依賴網路。** 它擋在每一次工具呼叫前面，
慢 200 毫秒乘上一整天的呼叫次數就很可觀。

**不要在 hook 裡做會失敗的事。** hook 自己爆掉會拖累整個 session。
