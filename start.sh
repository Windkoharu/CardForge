#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════════════
#  CardForge 卡锻 2.0 —— macOS / Linux 一键启动
#  用法：./start.sh                    环境自检后启动图形界面
#        ./start.sh doctor             只做环境自检
#        ./start.sh render --demo      渲染一张演示卡
#        ./start.sh <任意子命令>        透传给 cardforge
# ════════════════════════════════════════════════════════════════════
set -euo pipefail
cd "$(dirname "$0")"

# 找一个可用的 Python 3.10+
PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1; then
    if "$c" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
      PY="$c"; break
    fi
  fi
done

if [ -z "$PY" ]; then
  echo
  echo "  [X] 没有找到 Python 3.10 或更高版本。"
  echo "      macOS : brew install python3"
  echo "      Ubuntu: sudo apt install python3 python3-pip"
  echo "      其他  : https://www.python.org/downloads/"
  echo
  exit 1
fi

if [ "$#" -eq 0 ]; then
  echo
  echo "  一键启动：环境自检 → 启动服务 → 自动打开浏览器"
  echo "  （已在跑的实例会被直接复用；端口被占用会自动顺延）"
  echo
  exec "$PY" -m cardforge launch
else
  exec "$PY" -m cardforge "$@"
fi
