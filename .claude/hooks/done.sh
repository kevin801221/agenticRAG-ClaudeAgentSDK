#!/usr/bin/env bash
# Hook: Stop —— 每一輪結束時響一聲，順便報告這一輪改了幾個檔。
set -uo pipefail
cd "${CLAUDE_PROJECT_DIR:-$(pwd)}" || exit 0
n=$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')
printf '\a'                       # 終端機的鈴聲
echo "🔔 這一輪結束。工作區目前有 $n 個檔案有改動。"
