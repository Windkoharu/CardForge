#!/usr/bin/env bash
# =====================================================================
# CardForge 打包真机验收（#12）—— 全部在同一个 shell 调用里完成：
#   AI 起的后台服务跨调用会被会话回收，所以「起服务 → 轮询 → 验收 → 杀」
#   必须一气呵成。端口用 8792，避开开发机的 8790。
#
# 验收点：
#   A. doctor --json（CLI）：frozen 路径解析（root/data/web/vendor 指向 _internal）
#   B. serve 起得来、/api/state 就绪
#   C. /api/doctor：各层能力如实上报（Pillow 在、引擎不在且明说）
#   D. /api/cards：exe 同级的 workspace 骨架被看见（演示卡 210000011）
#   E. /api/render/card-image：frozen 下完整渲染管线（PIL+字体+卡框）出真图
#   F. /：web/ 从 _internal 正常服务
#   G. 清场：杀进程 + 端口复核
# =====================================================================
set -u
cd "$(dirname "$0")/.." || exit 1
ROOT="$(pwd)"
EXE="$ROOT/dist/CardForge/CardForge.exe"
PORT=8792
LOG="$ROOT/.packaging/acc"
mkdir -p "$LOG"

say() { echo "== $*"; }

if [ ! -f "$EXE" ]; then
  echo "[X] 找不到 $EXE —— 先跑 tools/build_exe.py"
  exit 1
fi

# ── A. CLI doctor：frozen 路径解析 ─────────────────────────────────
say "A. doctor --json（CLI，frozen 路径解析）"
"$EXE" doctor --json > "$LOG/doctor_cli.json" 2>"$LOG/doctor_cli.err"
py_root() {
  "$ROOT/.packaging/venv/Scripts/python.exe" - "$1" <<'PYEOF'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
p = d.get("paths", {})
print("  version:", d.get("version"), "| python:", d.get("python"))
for k in ("root", "data", "web", "vendor", "engine", "workspace"):
    v = p.get(k) or {}
    print(f"  {k:<10} exists={v.get('exists')}  {v.get('path')}")
checks = d.get("checks", [])
bad = [c for c in checks if not c["ok"]]
print(f"  checks: {len(checks)} 项，未过 {len(bad)} 项")
for c in bad:
    print(f"    - {c['name']}: {c['detail']}" + (f"  -> {c['hint']}" if c.get("hint") else ""))
lv = d.get("levels", {})
print("  levels:", {k: v for k, v in lv.items()})
PYEOF
}
py_root "$LOG/doctor_cli.json" || { echo "[X] doctor --json 解析失败"; cat "$LOG/doctor_cli.err" | head -5; }

# ── B. 起服务（frozen exe 自己起，不靠系统 Python） ────────────────
say "B. serve --port $PORT --no-browser"
"$EXE" serve --port $PORT --no-browser > "$LOG/serve.log" 2>&1 &
SRV=$!
READY=""
for i in $(seq 1 40); do
  if curl --noproxy '*' -s -m 2 "http://127.0.0.1:$PORT/api/state" > "$LOG/state.json" 2>/dev/null; then
    if grep -q '"ok"\|version\|cards' "$LOG/state.json" 2>/dev/null; then READY=yes; break; fi
  fi
  sleep 0.5
done
if [ -z "$READY" ]; then
  echo "[X] 服务 20s 未就绪；serve.log："; tail -15 "$LOG/serve.log"
  kill $SRV 2>/dev/null
  exit 1
fi
echo "  就绪（${i} 次轮询）；/api/state 前 200 字："
head -c 200 "$LOG/state.json"; echo

# ── C. /api/doctor：各层能力 ───────────────────────────────────────
say "C. /api/doctor（frozen 各层能力）"
curl --noproxy '*' -s -m 10 "http://127.0.0.1:$PORT/api/doctor" > "$LOG/doctor_api.json"
"$ROOT/.packaging/venv/Scripts/python.exe" - "$LOG/doctor_api.json" <<'PYEOF'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
lv = d.get("levels", {})
print("  levels:", lv)
caps = d.get("capabilities") or d.get("render") or {}
for k in ("pillow", "text_engine", "fonts", "numpy"):
    if k in caps: print(f"  caps.{k} = {caps[k]}")
for c in d.get("checks", []):
    mark = "OK " if c.get("ok") else ("warn" if c.get("level") == "warn" else "FAIL")
    print(f"  [{mark}] {c.get('name')}: {c.get('detail')}")
PYEOF

# ── D. /api/cards：exe 同级 workspace 骨架 ─────────────────────────
say "D. /api/cards（演示卡应来自 exe 同级的 workspace/）"
curl --noproxy '*' -s -m 10 "http://127.0.0.1:$PORT/api/cards" > "$LOG/cards.json"
head -c 400 "$LOG/cards.json"; echo

# ── E. 渲染演示卡：frozen 完整管线 ────────────────────────────────
say "E. /api/render/card-image（PIL+字体+卡框全链路）"
curl --noproxy '*' -s -m 60 -o "$LOG/card.png" \
  "http://127.0.0.1:$PORT/api/render/card-image?card=210000011&archetype=%E6%98%9F%E5%A5%8F&fmt=png&size=edopro"
"$ROOT/.packaging/venv/Scripts/python.exe" - "$LOG/card.png" <<'PYEOF'
import sys
p = sys.argv[1]
raw = open(p, "rb").read()
print(f"  字节数: {len(raw)}  文件头: {raw[:8]!r}")
if raw[:8] == b"\x89PNG\r\n\x1a\n":
    from PIL import Image
    im = Image.open(p); im.load()
    print(f"  [OK] 真 PNG，尺寸 {im.size[0]}x{im.size[1]}")
else:
    print("  [X] 不是 PNG，内容前 200 字：", raw[:200])
PYEOF

# ── F. web/ 首页 ──────────────────────────────────────────────────
say "F. / （web/ 从 _internal 服务）"
curl --noproxy '*' -s -m 10 "http://127.0.0.1:$PORT/" | head -c 150; echo

# ── G. 清场 ───────────────────────────────────────────────────────
say "G. 清场"
kill $SRV 2>/dev/null
sleep 1
# exe 是直接进程，kill 即杀；保险起见再按端口找一次真 PID
PID="$(netstat -ano 2>/dev/null | grep "LISTENING" | grep ":$PORT " | awk '{print $5}' | head -1)"
if [ -n "${PID:-}" ]; then
  echo "  端口 $PORT 仍有 PID $PID，taskkill"
  taskkill //F //PID "$PID" >/dev/null 2>&1
fi
sleep 1
LEFT="$(netstat -ano 2>/dev/null | grep ":$PORT " | grep -c LISTENING || true)"
echo "  端口 $PORT LISTENING 数：$LEFT（0=干净）"
say "DONE"
