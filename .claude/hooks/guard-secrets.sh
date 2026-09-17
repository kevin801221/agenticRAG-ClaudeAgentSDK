#!/usr/bin/env bash
# Hook: PreToolUse (Write|Edit|MultiEdit) —— 在 Claude **真的寫檔之前**攔截。
#
# exit 2 = 擋下來。stderr 會回給 Claude，所以它看得到原因、會自己換路。
# 用 python3 解 JSON（不依賴 jq —— 學生機器不一定有）。
#
# 手動測：
#   echo '{"tool_name":"Write","tool_input":{"file_path":".env"}}' | .claude/hooks/guard-secrets.sh; echo "exit=$?"
#   echo '{"tool_name":"Write","tool_input":{"file_path":"a.py"}}' | .claude/hooks/guard-secrets.sh; echo "exit=$?"
set -uo pipefail
INPUT=$(cat)
read -r TOOL FILE <<<"$(printf '%s' "$INPUT" | python3 -c "
import json, sys
try: d = json.load(sys.stdin)
except Exception: print('', ''); raise SystemExit
print(d.get('tool_name', ''), d.get('tool_input', {}).get('file_path', ''))
" 2>/dev/null)"

case "${TOOL:-}" in Write|Edit|MultiEdit) ;; *) exit 0 ;; esac
[ -z "${FILE:-}" ] && exit 0

case "$(basename "$FILE")" in
  .env.example|.env.sample|.env.template) exit 0 ;;
  .env|.env.*|*.pem|*.key|credentials.json|id_rsa|id_ed25519)
    echo "🚫 guard-secrets 擋下：$FILE" >&2
    echo "原因：符合敏感檔案樣式。要放範本請用 .env.example。" >&2
    exit 2 ;;
esac
exit 0
