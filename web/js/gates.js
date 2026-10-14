/* ══════════════════════════════════════════════════════════════════
   质量门状态条 + 详情浮层
   ──────────────────────────────────────────────────────────────────
   状态语义是**六态**，不是「通过/不通过」两态：
     pass 真过了 · warn 有警告 · fail 被拦 · waived 人为放行（留痕）
     skipped 根本没跑（降级） · pending 还没跑
   skipped 与 pass 必须在视觉上分开 —— 把「没跑」看成「过了」是
   这个项目历史上最严重的一次缺陷（G3 谎报）。
   ══════════════════════════════════════════════════════════════════ */

import { api, store } from './state.js';
import { $, clear, h, modal, renderIssues, toast, textarea, pretty } from './ui.js';

const STATUS_ZH = {
  pass: '通过', warn: '警告', fail: '拦截', waived: '已放行',
  skipped: '未运行', pending: '未检查', error: '出错'
};

export function initGates() {
  const box = $('#gates');
  for (const g of ['G1', 'G2', 'G3', 'G4', 'G5']) {
    box.appendChild(h('button.gate-chip', { dataset: { gate: g, s: 'pending' },
      title: `${g} 尚未检查`, onclick: () => openGate(g) },
      h('span.dot'), h('span', { text: g })));
  }
  store.on('card', () => { reset('pending'); runQuick(); });
}

export function setGate(gate, report) {
  const chip = $(`.gate-chip[data-gate="${gate}"]`);
  if (!chip) return;
  const s = report && report.status ? report.status : 'pending';
  chip.dataset.s = s;
  const n = report && report.issues ? report.issues.length : 0;
  chip.title = `${gate} ${STATUS_ZH[s] || s}` +
    (report && report.degraded ? ` · ${report.degraded}` : '') +
    (n ? ` · ${n} 条` : '');
  chip.querySelector('span:last-child').textContent =
    gate + (n && s !== 'pass' ? ' ' + n : '');
  store.gates[gate] = report;
  // 艾莉娅（立绘陪伴栏）会把这句翻译成她的语气；事实仍由内核从 report 生成
  window.dispatchEvent(new CustomEvent('cardforge:gate-done',
    { detail: { gate, rep: report } }));
}

function reset(s) {
  ['G1', 'G2', 'G3', 'G4', 'G5'].forEach((g) => {
    const chip = $(`.gate-chip[data-gate="${g}"]`);
    if (chip) { chip.dataset.s = s; chip.querySelector('span:last-child').textContent = g; }
    delete store.gates[g];
  });
}

/** 换卡后先跑两道快的（G1 平衡、G2 脚本）；G3 需要人主动点。 */
async function runQuick() {
  if (!store.spec) return;
  // 未落盘的草稿（id=0 / cardExists=false）不跑门：没有卡号可查，
  // 跑出来只会是 GATE_CALL error —— 真机验收时发现草稿态会亮红 G1。
  if (!store.spec.id || store.cardExists === false) { reset('pending'); return; }
  reset('pending');
  for (const g of ['G1', 'G2']) {
    try {
      const r = await api.get(`/api/gates/${g}`, { card: store.spec.id });
      setGate(g, r.report);
    } catch (e) {
      setGate(g, { status: 'error', issues: [{ level: 'ERROR', code: g + '_CALL',
        message: e.message, hint: e.hint }] });
    }
  }
}

export async function openGate(gate) {
  const spec = store.spec;
  if (!spec && gate !== 'G5') { toast('先选中一张卡', { kind: 'warn' }); return; }
  const meta = (store.meta && store.meta.gates || {})[gate] || {};
  const body = h('div', {}, h('p', { class: 'footnote', text: '检查中…' }));
  const m = modal({ title: `${gate} · ${meta.zh || ''}`, body,
    actions: [{ label: '重新运行', class: 'mini-btn', keepOpen: true, onClick: () => run(gate, m) },
      { label: '问艾莉娅', class: 'mini-btn alt', onClick: () => askAbout(gate) }] });
  run(gate, m);
}

async function run(gate, m) {
  const body = m.body; clear(body);
  const isG3 = gate === 'G3';
  const opts = { card: store.spec ? store.spec.id : undefined };
  if (isG3) { opts.duels = 3; opts.scenario = true; }
  const note = h('p', { class: 'footnote', text: isG3 ? '实跑对局可能要几十秒…' : '检查中…' });
  body.appendChild(note);
  try {
    const r = await api.get(`/api/gates/${gate}`, opts);
    setGate(gate, r.report);
    renderReport(body, gate, r.report);
  } catch (e) {
    clear(body).appendChild(h('div.notice.bad', {},
      h('b', { text: '这道门跑不起来：' }), e.message,
      h('div.hint', { text: '→ ' + (e.hint || '') })));
    setGate(gate, { status: 'error', issues: [{ level: 'ERROR', code: 'GATE_CALL',
      message: e.message, hint: e.hint }] });
  }
}

function renderReport(box, gate, rep) {
  clear(box);
  const s = rep.status || 'pending';
  const tone = s === 'pass' ? 'ok' : (s === 'fail' || s === 'error') ? 'bad'
    : (s === 'skipped' || s === 'warn' || s === 'waived') ? 'warn' : '';
  box.appendChild(h(`div.notice.${tone}`, {},
    h('b', { text: `状态：${STATUS_ZH[s] || s}` }),
    h('br'), rep.summary || '',
    rep.degraded ? h('div', {}, h('br'), h('b', { text: '降级说明：' }), rep.degraded) : null,
    rep.took_ms ? h('div.hint', { text: `耗时 ${rep.took_ms} ms` }) : null));

  if (s === 'skipped') {
    box.appendChild(h('div.notice.warn', {},
      h('b', { text: '这一门没有真的运行。' }),
      ' 「未运行」和「通过」是两回事 —— 别把它当成绿灯。'));
  }

  const issueBox = h('div.issue-bar');
  box.appendChild(issueBox);
  renderIssues(issueBox, rep.issues, {
    onWaive: (it) => waive(gate, it, box),
    emptyText: '这一门没发现问题'
  });

  if (gate === 'G3') {
    box.appendChild(h('p.footnote', { text: 'G3 会开真对局。跑不通通常说明脚本有非法 API ' +
      '或死循环；跑通只代表「不报错」，不代表效果符合你的设计意图 —— ' +
      '那需要看场景断言。' }));
  }
}

async function waive(gate, it, box) {
  const reason = prompt(`放行 ${it.code} 的理由（会写进审计报告，不可省略）：`);
  if (!reason || !reason.trim()) { toast('没写理由，已取消放行', { kind: 'warn' }); return; }
  try {
    const r = await api.post('/api/gates/waive', {
      gate, code: it.code, reason, card: store.spec ? store.spec.id : undefined, who: 'gui'
    });
    setGate(gate, r.report);
    renderReport(box, gate, r.report);
    toast('已放行并留痕', { kind: 'ok', hint: r.audit ? '审计报告：' + r.audit : '' });
  } catch (e) {
    toast('放行失败：' + e.message, { kind: 'err', hint: e.hint });
  }
}

function askAbout(gate) {
  const rep = store.gates[gate];
  if (!rep) { toast('这一门还没跑过', { kind: 'warn' }); return; }
  window.dispatchEvent(new CustomEvent('cardforge:explain-gate', { detail: { gate, rep } }));
}
