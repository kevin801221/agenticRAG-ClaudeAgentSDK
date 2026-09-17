#!/usr/bin/env bash
# Hook: SessionStart
#
# 什麼時候跑：你打 `claude` 進入 session 的第一秒，以及 /clear、/compact 之後。
# stdout 會被當成 context 塞給 Claude —— 它一開場就知道這些事，不用問你。
#
# 手動測：echo '{}' | .claude/hooks/session-start.sh

set -uo pipefail
cd "${CLAUDE_PROJECT_DIR:-$(pwd)}" || exit 0

branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "not-a-git-repo")
dirty=$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')

if [ -f data/index.pkl ]; then
  # 用專案的 .venv —— index.pkl 裡是 Chunk 物件，系統 python 反序列化不了
  PY=./.venv/bin/python
  if [ ! -x "${PY}" ]; then PY=python3; fi
  chunks=$("${PY}" -c "import pickle; print(len(pickle.load(open('data/index.pkl','rb'))['chunks']))" 2>/dev/null)
  if [ -z "$chunks" ]; then chunks="?"; fi
  if [ -f data/vectors.npy ]; then
    index="$chunks 個片段（有向量）"
  else
    index="$chunks 個片段（純 BM25）"
  fi
else
  index="還沒建，先跑 uv run python index_corpus.py --no-vectors"
fi

if grep -q "^NEO4J_URI=." .env 2>/dev/null; then
  graph="有設定"
else
  graph="沒接"
fi

echo "【專案現況｜由 SessionStart hook 自動注入】"
echo "分支：${branch}（$dirty 個檔案有改動）"
echo "索引：$index"
echo "圖資料庫：$graph"
