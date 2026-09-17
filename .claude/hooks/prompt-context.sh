#!/usr/bin/env bash
# Hook: UserPromptSubmit —— 你每按一次 Enter 就跑，stdout 會接在你的訊息前面。
#
# 這支是整組裡最適合示範的：它讓 Claude「不用查就知道」現在幾點、在哪個分支。
# 手動測：echo '{"prompt":"hi"}' | .claude/hooks/prompt-context.sh
set -uo pipefail
cd "${CLAUDE_PROJECT_DIR:-$(pwd)}" || exit 0
printf '【此刻｜由 UserPromptSubmit hook 注入】%s，分支 %s\n' \
  "$(date '+%H:%M:%S')" "$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"
