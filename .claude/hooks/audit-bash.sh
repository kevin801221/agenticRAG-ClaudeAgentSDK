#!/usr/bin/env bash
# Hook: PostToolUse (Bash) —— 指令**跑完之後**記一筆。攔不住，但留得下證據。
#
# 手動測：echo '{"tool_name":"Bash","tool_input":{"command":"ls"}}' | .claude/hooks/audit-bash.sh
set -uo pipefail
CMD=$(cat | python3 -c "
import json, sys
try: print(json.load(sys.stdin).get('tool_input', {}).get('command', ''))
except Exception: pass
" 2>/dev/null)
[ -z "${CMD:-}" ] && exit 0
DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}/.claude/logs"
mkdir -p "$DIR"
printf '[%s] %s\n' "$(date '+%H:%M:%S')" "$CMD" >> "$DIR/bash-audit.log"
exit 0
