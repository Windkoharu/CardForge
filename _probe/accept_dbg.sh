#!/usr/bin/env bash
# 调试：看启动后页面结构，确认阶段 tab 与 AI 起草按钮的可点击状态
set -u
cd "$(dirname "$0")/.."
export PYTHONIOENCODING=utf-8
LOG=workspace/.cache/accept_dbg.log
: > "$LOG"

py -3 tools/mock_llm_server.py 1235 mock-qwen-7b --draft &
MOCK=$!
for i in $(seq 1 30); do
  py -3 -c "import socket;socket.create_connection(('127.0.0.1',1235),timeout=0.2).close()" 2>/dev/null && break
  sleep 0.2
done
py -3 -m cardforge llm set --name mockdraft --base-url http://127.0.0.1:1235/v1 --use >>"$LOG" 2>&1
py -3 -m cardforge serve --port 8799 --no-browser >workspace/.cache/cf_srv.log 2>&1 &
SRV=$!
for i in $(seq 1 60); do
  curl -s --noproxy '*' http://127.0.0.1:8799/api/state >/dev/null 2>&1 && break
  sleep 0.5
done
echo "up: mock=$MOCK srv=$SRV"

agent-browser open http://127.0.0.1:8799 >>"$LOG" 2>&1
sleep 12
echo "── snapshot -i（前 60 行）:"
agent-browser snapshot -i 2>/dev/null | head -60

echo "── 点 text 阶段 tab"
agent-browser click ".stage-tab[data-stage='text']" 2>&1 | tail -2
sleep 2
echo "── 再 snapshot -i（找 btn-ai-draft）:"
agent-browser snapshot -i 2>/dev/null | grep -iE "起草|生成|校验|写回" | head -8

echo "── 点 AI 起草"
agent-browser click "#btn-ai-draft" 2>&1 | tail -2
sleep 2
agent-browser screenshot "_probe/ui_dbg_modal.png" 2>&1 | tail -1
echo "── snapshot 看模态:"
agent-browser snapshot 2>/dev/null | grep -iE "AI 起草|概念|取消|起笔" | head -6

agent-browser close >>"$LOG" 2>&1
kill $SRV $MOCK 2>/dev/null; sleep 1
for P in 8799 1235; do
  PID=$(netstat -ano | grep "127.0.0.1:$P.*LISTENING" | head -1 | awk '{print $NF}')
  [ -n "$PID" ] && taskkill //F //PID $PID >/dev/null 2>&1
done
py -3 -m cardforge llm off >>"$LOG" 2>&1
py -3 -m cardforge llm rm mockdraft >>"$LOG" 2>&1
py -3 - <<'PY' 2>&1
import json, pathlib
p = pathlib.Path('workspace/config/llm.json')
if p.exists():
    d = json.loads(p.read_text(encoding='utf-8-sig'))
    if not (d.get('providers') or {}): p.unlink(); print('config removed')
PY
netstat -ano | grep LISTENING | grep -qE "8799|1235" && echo "WARN busy" || echo "CLEAN"
