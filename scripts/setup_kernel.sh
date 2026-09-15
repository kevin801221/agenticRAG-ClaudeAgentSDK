#!/usr/bin/env bash
# 把專案的 .venv 註冊成一個具名 kernel，Jupyter 和 VS Code 的選單就看得到它。
#
# 會這樣做是因為：notebook 裡 import 得到 modules.py，靠的不是「開哪個資料夾」，
# 而是「kernel 用的是哪一個 python」。選錯 kernel 就會 ModuleNotFoundError，
# 而且錯誤訊息完全不會提到 kernel。
set -euo pipefail
cd "$(dirname "$0")/.."

# 刻意不在這裡跑 uv sync ——「uv sync --extra X」會把不在 X 裡的套件**移除**，
# 在這支只該註冊 kernel 的腳本裡順手 sync，會默默把 chromadb / pymupdf 拔掉。
if [ ! -x .venv/bin/python ]; then
  echo "找不到 .venv。先跑：uv sync --all-extras" >&2
  exit 1
fi

uv run python -m ipykernel install --user \
  --name agentic-rag \
  --display-name "agentic-rag (.venv, Python 3.13)"

echo
echo "好了。Jupyter / VS Code 的 kernel 選單挑「agentic-rag (.venv, Python 3.13)」。"
echo
uv run jupyter kernelspec list
