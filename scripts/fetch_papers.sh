#!/usr/bin/env bash
# 把這套教材引用到的論文從 arXiv 抓下來，放進 corpus/papers/。
#
# 為什麼不直接放進 repo：那是別人的論文，各自有各自的授權，
# 這個 repo 不該替他們重新散布。抓下來的檔案已經在 .gitignore 裡。
#
#   bash scripts/fetch_papers.sh          # 全部抓
#   bash scripts/fetch_papers.sh crag     # 只抓名字含 crag 的
#
# 抓完記得重建索引：uv run python index_corpus.py

set -euo pipefail
cd "$(dirname "$0")/.."
DIR=corpus/papers
mkdir -p "$DIR"

# 檔名=arXiv ID。檔名會變成引用時看到的東西，所以取得好讀一點
PAPERS="
rag-original=2005.11401
hyde=2212.10496
self-ask=2210.03350
ircot=2212.10509
flare=2305.06983
rewrite-retrieve-read=2305.14283
self-rag=2310.11511
crag=2401.15884
adaptive-rag=2403.14403
modular-rag=2407.21059
search-o1=2501.05366
agentic-rag-survey=2501.09136
"

filter="${1:-}"
ok=0
skip=0

for entry in $PAPERS; do
  name="${entry%%=*}"
  id="${entry##*=}"
  [ -n "$filter" ] && [[ "$name" != *"$filter"* ]] && continue

  out="$DIR/$name.pdf"
  if [ -f "$out" ]; then
    echo "  已存在  $name.pdf"
    skip=$((skip + 1))
    continue
  fi

  printf "  下載中  %-24s arXiv:%s ... " "$name.pdf" "$id"
  if curl -fsSL --retry 2 -o "$out" "https://arxiv.org/pdf/$id"; then
    echo "$(du -h "$out" | cut -f1)"
    ok=$((ok + 1))
    sleep 1   # 對 arXiv 客氣一點
  else
    echo "失敗"
    rm -f "$out"
  fi
done

echo
echo "完成：新抓 $ok 份，已存在 $skip 份，全部在 $DIR/"
echo "接著跑：uv run python index_corpus.py"
