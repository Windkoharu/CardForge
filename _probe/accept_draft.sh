#!/usr/bin/env bash
# AI 起草真机验收 v2：eval 点阶段 tab（属性选择器在 agent-browser 里不生效），
# 其余用 id 选择器（settings 验收时验证过可用）。
set -u
cd "$(dirname "$0")/.."
export PYTHONIOENCODING=utf-8
LOG=workspace/.cache/accept_draft.log
: > "$LOG"
say() { echo "$@" | tee -a "$LOG"; }

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
say "up: mock=$MOCK srv=$SRV"

agent-browser open http://127.0.0.1:8799 >>"$LOG" 2>&1
# 等启动面板真正消失（boot-overlay 从 DOM 移除）再操作
for i in $(seq 1 40); do
  GONE=$(agent-browser eval "document.getElementById('app-boot') ? 'no' : 'yes'" 2>/dev/null | tr -d '\r\n' | tail -1)
  [ "$GONE" = "yes" ] && break
  sleep 0.5
done
say "boot gone: $GONE"

say "== 切到卡文阶段（eval 点击）"
agent-browser eval "document.querySelector(\".stage-tab[data-stage='text']\").click()" >>"$LOG" 2>&1
sleep 1.5
say "-- 卡文阶段按钮："
agent-browser snapshot 2>/dev/null | grep -iE "AI 起草|生成|校验|写回规格" | head -6 | tee -a "$LOG"

say "== 点 AI 起草"
agent-browser click "#btn-ai-draft" >>"$LOG" 2>&1
sleep 1.5
agent-browser screenshot "_probe/ui_draft_1_concept.png" >>"$LOG" 2>&1
say "screenshot 1 ok"
say "-- 概念模态内容："
agent-browser snapshot 2>/dev/null | grep -iE "AI 起草卡文|概念|取消|起草中|大模型只提议" | head -6 | tee -a "$LOG"

say "== 填概念 → 起草"
agent-browser type "#draft-concept" "召唤成功时从卡组检索一张怪兽" >>"$LOG" 2>&1
agent-browser click "#modal-foot button.alt" >>"$LOG" 2>&1
sleep 5
agent-browser screenshot "_probe/ui_draft_2_result.png" >>"$LOG" 2>&1
say "screenshot 2 ok"
say "-- 结果模态关键内容："
agent-browser snapshot 2>/dev/null | grep -iE "起草结果|PSCT_HOPT|填入编辑器|ERROR|内核结论|G1" | head -10 | tee -a "$LOG"

say "== 填入编辑器"
agent-browser click "#modal-foot button.alt" >>"$LOG" 2>&1
sleep 1.5
FILLED=$(agent-browser eval "document.getElementById('text-editor').value.slice(0,30)" 2>/dev/null | tr -d '\r\n' | tail -1)
say "编辑器内容前 30 字：$FILLED"
agent-browser screenshot "_probe/ui_draft_3_filled.png" >>"$LOG" 2>&1
say "screenshot 3 ok"

agent-browser close >>"$LOG" 2>&1
kill $SRV $MOCK 2>/dev/null; sleep 1
for P in 8799 1235; do
  PID=$(netstat -ano | grep "127.0.0.1:$P.*LISTENING" | head -1 | awk '{print $NF}')
  [ -n "$PID" ] && taskkill //F //PID $PID >/dev/null 2>&1
done
py -3 -m cardforge llm off >>"$LOG" 2>&1
py -3 -m cardforge llm rm mockdraft >>"$LOG" 2>&1
py -3 - <<'PY' 2>&1 | tee -a "$LOG"
import json, pathlib
p = pathlib.Path('workspace/config/llm.json')
if p.exists():
    d = json.loads(p.read_text(encoding='utf-8-sig'))
    if not (d.get('providers') or {}): p.unlink(); print('config removed')
PY
netstat -ano | grep LISTENING | grep -qE "8799|1235" && say "WARN busy" || say "CLEAN"
say "== DONE"
