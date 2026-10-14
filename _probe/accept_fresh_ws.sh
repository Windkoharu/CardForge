#!/usr/bin/env bash
# =====================================================================
# 验收盲区补课：**空工作区首次启动**（模拟全新机器）
#
# 此前所有验收都带着 workspace 骨架（演示卡）跑，"首次启动自动建目录 +
# 零卡欢迎态"这条路只有 paths.ensure_dirs() 的代码声明，没真跑过。
# 本次把骨架**重命名**挪走（零删除），起服务验一遍，再挪回去。
#
# 还原策略（2026-10-15 重修，第一版的教训）：
#   运行后 workspace 里的一切都是本次运行新建的——骨架已事先挪走。
#   但新建物**不只是空目录**：渲染会写 .cache/svg/*.png 光栅化缓存，
#   保存操作会写 .history/**/v*.json 版本快照。第一版只 rmdir 空目录，
#   文件清不掉，mv 骨架回去时就挪进了已存在的 workspace/ 里（变成
#   workspace/ws_backup/），还得手动合并。
#   现在：运行时现场**整体重命名**到 .packaging/fresh_ws_runtime-<ts>/
#   留作证据，骨架原位换回。全程零删除。
#   --clean（opt-in，排在验收之前，同 build_exe.py 的语义）：删掉上次的现场。
# =====================================================================
set -u
cd "$(dirname "$0")/.." || exit 1
ROOT="$(pwd)"
EXE="$ROOT/dist/CardForge/CardForge.exe"
WS="$ROOT/dist/CardForge/workspace"
BAK="$ROOT/.packaging/ws_backup"
RUNTIME_BASE="$ROOT/.packaging/fresh_ws_runtime"
PORT=8793
LOG="$ROOT/.packaging/acc"
TS="$(date +%Y%m%d-%H%M%S)"
mkdir -p "$LOG"
say() { echo "== $*"; }

CLEAN=0
for a in "$@"; do
  case "$a" in
    --clean) CLEAN=1 ;;
    *) echo "[X] 未知参数：$a（只接受 --clean）"; exit 1 ;;
  esac
done

# ── 0. 环境哨兵：不许有其他 CardForge 实例活着 ────────────────────
# 2026-10-14 的教训：上一段验收留下的 launch 实例（8790）跨会话存活，
# 它的浏览器页面对着被本脚本清空的工作区，反复重建演示卡/系列
# （.history 快照每几十秒一个、骨架 spec.json 被改写成旧内容），
# 于是"删了又长"、还原怎么都对不齐。验收 harness 的前提是独占工作区。
say "0. 环境哨兵：确认没有其他 CardForge 实例"
STRAY="$(netstat -ano 2>/dev/null | grep LISTENING | grep -E ':(879[0-9]) ' | awk '{print $5}' | sort -u)"
if [ -n "${STRAY:-}" ]; then
  echo "[X] 端口 879x 被占用（PID: $(echo $STRAY | tr '\n' ' ')）——先杀干净再验收"
  exit 1
fi
if tasklist 2>/dev/null | grep -qi cardforge; then
  echo "[X] 还有 CardForge 进程在跑——先杀干净再验收："
  tasklist 2>/dev/null | grep -i cardforge | sed 's/^/    /'
  exit 1
fi
echo "  干净：无 879x 监听、无 CardForge 进程"

# --clean 排最前（哨兵之后）：被删除护栏拦下就诚实失败在验收开始前，
# 不出现「验收跑完了却说清理失败」。
if [ "$CLEAN" = "1" ]; then
  say "0. --clean：清理上次验收留下的运行时现场"
  N_CLEAN=0
  for d in "$RUNTIME_BASE"-*; do
    [ -e "$d" ] || continue
    echo "  删除 $d"
    rm -rf "$d" || { echo "[X] 删不掉 $d"; exit 1; }
    N_CLEAN=$((N_CLEAN+1))
  done
  [ "$N_CLEAN" = "0" ] && echo "  （没有可清理的现场）"
fi

if [ ! -d "$WS" ]; then echo "[X] 找不到 $WS"; exit 1; fi
SKEL_N="$(find "$WS" -type f | wc -l)"
echo "骨架文件数：$SKEL_N"

# ── 1. 骨架挪走（重命名，零删除） ─────────────────────────────────
say "1. workspace 骨架挪到 .packaging/ws_backup"
if [ -e "$BAK" ]; then echo "[X] $BAK 已存在（上次还原没完成？），先手动处理"; exit 1; fi
mv "$WS" "$BAK" || { echo "[X] 挪不走"; exit 1; }
ls -d "$WS" 2>/dev/null && echo "[X] workspace 居然还在" || echo "  workspace 已不存在（全新机器态）"

# ── 2. 空工作区起服务 ─────────────────────────────────────────────
say "2. 空工作区 serve --port $PORT --no-browser"
"$EXE" serve --port $PORT --no-browser > "$LOG/fresh_serve.log" 2>&1 &
SRV=$!
READY=""
for i in $(seq 1 40); do
  if curl --noproxy '*' -s -m 2 "http://127.0.0.1:$PORT/api/state" > "$LOG/fresh_state.json" 2>/dev/null; then
    if grep -q '"ok"' "$LOG/fresh_state.json" 2>/dev/null; then READY=yes; break; fi
  fi
  if ! kill -0 $SRV 2>/dev/null; then echo "[X] 进程提前退出"; break; fi
  sleep 0.5
done
echo "  READY=$READY（${i:-?} 次轮询）"
if [ -z "$READY" ]; then echo "--- serve.log ---"; tail -15 "$LOG/fresh_serve.log"; fi

# ── 3. 空工作区下的三项检查 ───────────────────────────────────────
say "3. 空工作区行为"
curl --noproxy '*' -s -m 10 "http://127.0.0.1:$PORT/api/cards" > "$LOG/fresh_cards.json"
echo "  /api/cards: $(head -c 120 "$LOG/fresh_cards.json")"
curl --noproxy '*' -s -m 10 "http://127.0.0.1:$PORT/api/doctor" > "$LOG/fresh_doctor.json"
"$ROOT/.packaging/venv/Scripts/python.exe" - "$LOG/fresh_doctor.json" "$WS" <<'PYEOF'
import json, sys, os
d = json.load(open(sys.argv[1], encoding="utf-8"))
ws = sys.argv[2]
created = d.get("created_dirs")
print(f"  created_dirs（本次自检新建）: {created}")
print(f"  workspace 目录现在存在: {os.path.isdir(ws)}")
for c in d.get("checks", []):
    if c.get("name") in ("工作区", "内置数据"):
        print(f"  [{ 'OK ' if c['ok'] else 'FAIL'}] {c['name']}: {c['detail']}")
PYEOF
echo "  workspace 下实际建出的目录："
ls "$WS" 2>/dev/null | sed 's/^/    /' || echo "    （目录根本没被创建！）"

# ── 4. 首页可达（欢迎态） ─────────────────────────────────────────
say "4. / 可达（空工作区欢迎态）"
curl --noproxy '*' -s -m 10 "http://127.0.0.1:$PORT/" | head -c 80; echo

# ── 5. 清场 + 骨架归位（零删除，见文件头） ────────────────────────
say "5. 清场并还原骨架"
kill $SRV 2>/dev/null; sleep 1
PID="$(netstat -ano 2>/dev/null | grep LISTENING | grep ":$PORT " | awk '{print $5}' | head -1)"
[ -n "${PID:-}" ] && taskkill //F //PID "$PID" >/dev/null 2>&1
sleep 1
LEFT="$(netstat -ano 2>/dev/null | grep ":$PORT " | grep -c LISTENING || true)"
echo "  端口 $PORT 残留 LISTENING：$LEFT"

# 运行后 workspace 里的一切都是本次运行新建的（骨架已事先挪走），
# 整体重命名留作现场证据；骨架再原位换回。全程零删除。
RUNTIME="$RUNTIME_BASE-$TS"
if [ -d "$WS" ]; then
  RT_N="$(find "$WS" -type f | wc -l)"
  RT_SIZE="$(du -sh "$WS" 2>/dev/null | awk '{print $1}')"
  mv "$WS" "$RUNTIME" || { echo "[X] 运行时现场挪不走，骨架留在 $BAK，请手动合并"; exit 1; }
  echo "  本次运行现场：$RT_N 个文件（$RT_SIZE）→ $RUNTIME"
  echo "  （证据保留；确认无需保留可手动删，或下次运行加 --clean 提前清理）"
else
  echo "  [!] 运行后 workspace 不存在——应用根本没建目录？骨架直接换回"
fi
if [ -d "$BAK" ]; then
  mv "$BAK" "$WS" || { echo "[X] 骨架换回失败！骨架在 $BAK，请立即手动处理"; exit 1; }
fi
NOW_N="$(find "$WS" -type f 2>/dev/null | wc -l)"
if [ "$NOW_N" = "$SKEL_N" ]; then
  echo "  骨架已还原（$NOW_N 个文件，与运行前一致）"
else
  echo "  [!] 骨架文件数不符：运行前 $SKEL_N / 现在 $NOW_N"
fi
say "DONE"
