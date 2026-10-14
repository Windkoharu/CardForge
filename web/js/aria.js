/* ══════════════════════════════════════════════════════════════════
   星奏·艾莉娅 · 立绘陪伴栏
   ──────────────────────────────────────────────────────────────────
   架构位置：她是**表达层**。本模块里没有一句自己发明的结论 ——
   所有气泡文字都来自内核：

     GET  /api/assistant/line       （状态话术 / 问候，纯模板渲染）
     POST /api/assistant/gate-line  （门结论一句话，事实由内核从 report 生成）

   本模块只做三件事：换表情（六档交叉淡入）、排队气泡、把界面事件
   （切卡 / 切阶段 / 门完成 / 任务进行）翻译成对上面两个接口的调用。
   ══════════════════════════════════════════════════════════════════ */

import { api, store } from './state.js';
import { $, esc } from './ui.js';

/* 表情 → 立绘文件（docs/04 §2；生成凭据在 data/assets/aria/manifest.json） */
const FIG = {
  guide: 'assets/aria/aria_guide.png',
  working: 'assets/aria/aria_working.png',
  alert: 'assets/aria/aria_alert.png',
  pass: 'assets/aria/aria_pass.png',
  think: 'assets/aria/aria_think.png',
  surprise: 'assets/aria/aria_surprise.png',
};
const ZH = { guide: '引导', working: '工作', alert: '报警', pass: '通过',
  think: '思考', surprise: '惊讶' };

/* 四个阶段的向导语（只描述「这一步在做什么」，不含任何结论） */
const STAGE_STEPS = {
  spec: { step: '规格', detail: '卡种、数值、效果都在这定 —— 后面的一切都从这份规格派生。',
    next: '卡文 · 脚本' },
  text: { step: '卡文 · 脚本', detail: '卡文与 Lua 都是效果 IR 的投影；生成不了的地方会写明，不会瞎编。',
    next: '卡图 · 卡面' },
  art: { step: '卡图 · 卡面', detail: '本机 ComfyUI 出图，再叠罕贵/出框合成卡面。',
    next: '上桌' },
  pack: { step: '上桌', detail: '导出 EDOPro 扩展包或 MDPro3 的 .ypk；导入这一步由你在游戏里点。',
    next: '打完收工' },
};

let front = 'a';                 // 当前显示的是 a/b 哪张（交叉淡入用）
let state = 'guide';
let lastCtx = null;              // 最近一次语境（换人格时重放）
let personas = [];

export function initAria() {
  const a = $('#aria-img-a'), b = $('#aria-img-b');
  if (!a || !b) return;
  a.classList.add('is-on');
  a.dataset.key = 'guide';

  // 预加载全部表情，切换时不闪
  Object.values(FIG).forEach((src) => { const im = new Image(); im.src = src; });

  $('#aria-figure').addEventListener('click', () => openDrawer());
  $('#aria-figure').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openDrawer(); }
  });
  $('#aria-bubble-close').addEventListener('click', () => {
    $('#aria-bubble').hidden = true;
  });
  $('#aria-open').addEventListener('click', () => openDrawer());
  $('#aria-quick').addEventListener('click', (e) => {
    const btn = e.target.closest('button');
    if (btn) openDrawer(btn.dataset.ask || '');
  });

  loadPersonas();

  /* ── 全局事件接线 ─────────────────────────────────────────── */
  store.on('card', (spec) => onCard(spec));
  window.addEventListener('cardforge:stage', (e) => onStage(e.detail && e.detail.stage));
  window.addEventListener('cardforge:gate-done', (e) => gateLine(e.detail && e.detail.rep));
  window.addEventListener('cardforge:job', (e) => onJob(e.detail || {}));
  window.addEventListener('cardforge:persona', () => personaRefresh());
  window.addEventListener('cardforge:saved', () => line({
    state: 'pass', step: '保存',
    facts: '规格已写入工作区；旧版本进了 .history/，随时能回滚。',
  }));
  window.addEventListener('cardforge:chat-busy', (e) => {
    // 对话进行中：立绘进入「思考」；结束后回到引导
    setState(e.detail && e.detail.busy ? 'think' : 'guide');
  });

  say('正在自检环境……', { state: 'working', silentState: true });
}

/* ══════════════ 与内核说话 ══════════════ */

/** 状态话术 / 问候。参数必须来自内核结果或界面已知事实（步骤名），不含判断。 */
async function line(params, { replayable = true } = {}) {
  if (replayable) lastCtx = { type: 'line', params };
  try {
    const r = await api.get('/api/assistant/line',
      Object.assign({ persona: store.persona }, params));
    if (r && r.text) say(r.text, { state: r.state || params.state || 'guide' });
  } catch (e) {
    // 内核不可用：说最保守的一句（不含任何结论），不编造
    say('内核的措辞服务暂时不可用 —— 结论仍然可以在各面板直接看。',
      { state: 'alert' });
  }
}

/** 门结论一句话：事实由内核从 report 生成（gate_line），这里只显示。 */
async function gateLine(rep) {
  if (!rep || !rep.gate) return;
  lastCtx = { type: 'gate', report: rep };
  try {
    const r = await api.post('/api/assistant/gate-line',
      { report: rep, persona: store.persona });
    const st = r.status === 'pass' || r.status === 'waived' ? 'pass'
      : (r.status === 'skipped' || r.status === 'pending') ? 'guide' : 'alert';
    say(r.text || '', { state: st });
  } catch (e) { /* 失败时保持原气泡，不猜结论 */ }
}

function personaRefresh() {
  if (!lastCtx) return;
  if (lastCtx.type === 'gate') gateLine(lastCtx.report);
  else if (lastCtx.type === 'line') line(lastCtx.params, { replayable: false });
}

function openDrawer(ask = '') {
  window.dispatchEvent(new CustomEvent('cardforge:open-drawer', { detail: { ask } }));
}

/* ══════════════ 界面事件 ══════════════ */
function onCard(spec) {
  if (!spec || !spec.name) { line({ kind: 'first' }); return; }
  line({
    state: 'guide', step: '看卡',
    detail: `现在看着「${spec.display_name || spec.name}」（卡号 ${spec.id}）。`,
    next: '改表单，或者直接问我它的结论',
  });
}

function onStage(stage) {
  const s = STAGE_STEPS[stage];
  if (s) line(Object.assign({ state: 'guide' }, s));
}

function onJob(d) {
  const label = d.label || '任务';
  if (d.state === 'working') {
    line({ state: 'working', step: label, detail: d.facts || '正在跑，进度就在面板上。' });
  } else if (d.state === 'pass') {
    line({ state: 'pass', step: label, facts: d.facts || `${label}完成。` });
  } else if (d.state === 'alert') {
    line({ state: 'alert', step: label, facts: d.facts || `${label}出了问题。` });
  }
}

/* ══════════════ 显示层 ══════════════ */

/** 换表情（交叉淡入）。同种表情重复调用是 no-op。 */
export function setState(key) {
  const k = FIG[key] ? key : 'guide';
  const a = $('#aria-img-a'), b = $('#aria-img-b');
  if (!a || !b) return;
  const curEl = front === 'a' ? a : b;
  state = k;
  if (curEl.dataset.key === k) return;
  const nextEl = front === 'a' ? b : a;
  nextEl.src = FIG[k];
  nextEl.dataset.key = k;
  const show = () => { nextEl.classList.add('is-on'); curEl.classList.remove('is-on'); };
  nextEl.onload = show;
  if (nextEl.complete) show();          // 缓存命中时 onload 不一定再来
  front = front === 'a' ? 'b' : 'a';
}

/** 气泡。text 来自内核；这里只做 **加粗** 与换行的轻量渲染。 */
export function say(text, { state: st = state, silentState = false } = {}) {
  const box = $('#aria-bubble');
  const body = $('#aria-bubble-text');
  const chip = $('#aria-chip');
  if (!box || !body) return;
  if (!silentState) setState(st);
  box.dataset.state = st;
  chip.textContent = ZH[st] || st;
  body.innerHTML = esc(String(text || ''))
    .replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>')
    .replace(/\n/g, '<br>');
  box.hidden = false;
}

/* ══════════════ 人格（与抽屉同源，切换即重放当前语境）══════════════ */
async function loadPersonas() {
  try {
    const r = await api.get('/api/assistant/personas');
    personas = r.personas || [];
  } catch (e) {
    personas = [{ key: 'professional', zh: '专业型' }];
  }
  renderPersonas();
  window.addEventListener('cardforge:persona', renderPersonas);
}

function renderPersonas() {
  const box = $('#aria-persona');
  if (!box) return;
  box.innerHTML = '';
  for (const p of personas) {
    const btn = document.createElement('button');
    btn.textContent = p.zh || p.key;
    btn.title = '切换人格 —— 结论不变，只是语气不同';
    if (p.key === store.persona) btn.classList.add('is-active');
    btn.addEventListener('click', () => {
      // 复用抽屉的统一入口（它负责重置会话、清空聊天、广播事件）
      import('./assistant.js').then((m) => m.setPersona(p.key));
    });
    box.appendChild(btn);
  }
  if (!personas.length) {
    const d = document.createElement('div');
    d.className = 'footnote';
    d.textContent = '人格模块未就绪';
    box.appendChild(d);
  }
}
