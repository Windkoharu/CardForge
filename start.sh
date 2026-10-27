#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════════════
#  CardForge 卡锻 2.0 —— macOS / Linux 一键启动
#  用法：./start.sh                    环境自检后启动图形界面
#        ./start.sh doctor             只做环境自检
#        ./start.sh render --demo      渲染一张演示卡
#        ./start.sh <任意子命令>        透传给 cardforge
#
#  与 启动.bat 同样的原则（缺陷 #36）：**只认真的能跑起来的解释器**。
#  PATH 里叫 python3 的东西不一定是 Python（Windows 上的应用执行别名就是
#  一个典型），所以每个候选都要用 >=3.10 的版本探针真正执行一次。
#
#  优先级：$CARDFORGE_PYTHON > .venv > PATH 上的 python3.x > 常见安装位置
# ════════════════════════════════════════════════════════════════════
set -euo pipefail
cd "$(dirname "$0")"

# 探针：能导入、版本 >=3.10，才算数
py_ok() {
  "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)' >/dev/null 2>&1
}

PY=""
CANDIDATES=()

if [ -n "${CARDFORGE_PYTHON:-}" ]; then
  CANDIDATES+=("$CARDFORGE_PYTHON")
fi
if [ -x ".venv/bin/python" ]; then
  CANDIDATES+=(".venv/bin/python")
fi
CANDIDATES+=(python3.13 python3.12 python3.11 python3.10 python3 python)
for p in \
  /opt/homebrew/bin/python3 \
  /usr/local/bin/python3 \
  "$HOME/.pyenv/shims/python3" \
  "$HOME/miniconda3/bin/python" \
  "$HOME/anaconda3/bin/python" \
  /opt/miniconda3/bin/python \
  /opt/anaconda3/bin/python
do
  if [ -x "$p" ]; then CANDIDATES+=("$p"); fi
done

for c in "${CANDIDATES[@]}"; do
  if [ -z "$c" ]; then continue; fi
  if ! command -v "$c" >/dev/null 2>&1 && [ ! -x "$c" ]; then continue; fi
  if py_ok "$c"; then PY="$c"; break; fi
done

if [ -z "$PY" ]; then
  echo
  echo "  [X] 没有找到能用的 Python 3.10 或更高版本。"
  echo "      已检查：CARDFORGE_PYTHON、.venv、PATH、常见安装目录。"
  echo
  echo "      macOS : brew install python3"
  echo "      Ubuntu: sudo apt install python3 python3-pip"
  echo "      其他  : https://www.python.org/downloads/"
  echo "      便携版 / conda：export CARDFORGE_PYTHON=/路径/bin/python3"
  echo
  exit 1
fi

PYVER="$("$PY" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"
echo "  使用 Python ${PYVER}  [$PY]" >&2

if [ "$#" -eq 0 ]; then
  echo
  echo "  一键启动：环境自检 → 启动服务 → 自动打开浏览器"
  echo "  （已在跑的实例会被直接复用；端口被占用会自动顺延）"
  echo
  exec "$PY" -m cardforge launch
else
  exec "$PY" -m cardforge "$@"
fi
