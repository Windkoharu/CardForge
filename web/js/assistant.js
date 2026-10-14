/* ══════════════════════════════════════════════════════════════════
   星奏·艾莉娅 · 完整对话抽屉
   ──────────────────────────────────────────────────────────────────
   她是**表达层**：判断都来自确定性内核，她只负责说人话。
   所以界面把她标成「参谋」而不是「裁判」，并且没有 LLM 时也照样能用 ——
   那时她走规则回答，语气普通，但结论一样可信。

   人格切换的唯一入口是 setPersona()：陪伴栏（aria.js）与抽屉共用它。

   ── 讨论体验的几条约定 ────────────────────────────────────────────
   1. **历史按人格分开存**（localStorage）。切人格 = 换一套记录，
      切回来还在；刷新页面也不丢。丢掉上下文是最伤讨论体验的事。
   2. **每条回答都能重试 / 复制**。规则模式下偶尔答偏，重新打字很烦。
   3. **回答期间输入框锁住**，发送键变「停」—— 不让重复提交，
      也给一个明确的「她在想」信号（之前只有立绘表情变了，抽屉里看不出来）。
   4. **答不上来时给出口**。内核会明确说「不在我的数据源里」，
      这时附上几条她能答的问题 —— 空回答 + 无出路 = 死胡同。
   ══════════════════════════════════════════════════════════════════ */

import { api, store } from './state.js';
import { $, $$, clear, h, toast, pretty } from './ui.js';

let open = false;
let busy = false;
let abort = null;          // 当前请求的 AbortController

const LS_KEY = 'cardforge.chat.v1';

/* ══════════════ 历史持久化 ══════════════
   结构：{ professional: [msg], lightnovel: [...] }，每条形如
   { who:'me'|'bot', text, state?, tools?, error?, ts }。
   只存**已定稿**的消息；「……思考中」这类占位不落盘。 */

function loadStore() {
  try { return JSON.parse(localStorage.getItem(LS_KEY) || '{}') || {}; }
  catch { return {}; }
}
function saveStore(o) {
  try { localStorage.setItem(LS_KEY, JSON.stringify(o)); } catch { /* 隐私模式 */ }
}
function historyList() {
  const all = loadStore();
  return Array.isArray(all[store.persona]) ? all[store.persona] : [];
}
function pushHistory(msg) {
  const all = loadStore();
  const list = Array.isArray(all[store.persona]) ? all[store.persona] : [];
  list.push(msg);
  // 单人格最多留 80 条，避免 localStorage 无限膨胀
  all[store.persona] = list.slice(-80);
  saveStore(all);
}
function clearHistory() {
  const all = loadStore();
  delete all[store.persona];
  saveStore(all);
}

/* ══════════════ 生命周期 ══════════════ */

export function initAssistant() {
  $('#btn-assistant').addEventListener('click', toggle);
  $('#btn-close-drawer').addEventListener('click', () => setOpen(false));
  $('#btn-clear-chat') && $('#btn-clear-chat').addEventListener('click', confirmClear);

  $('#chat-form').addEventListener('submit', (e) => {
    e.preventDefault();
    if (busy) { stop(); return; }
    const t = $('#chat-text').value.trim();
    if (t) { $('#chat-text').value = ''; ask(t); }
  });
  // 输入框：忙碌时禁用；Esc 停止
  $('#chat-text').addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && busy) { e.preventDefault(); stop(); }
  });

  $('#chat-suggest').addEventListener('click', (e) => {
    const b = e.target.closest('button');
    if (!b) return;
    $('#chat-text').value = b.dataset.ask || b.textContent;
    ask($('#chat-text').value);
    $('#chat-text').value = '';
  });

  window.addEventListener('cardforge:explain-gate', (e) => {
    explainGate(e.detail.gate, e.detail.rep);
  });
  // 陪伴栏（立绘）点「完整对话」或快捷指令 → 打开抽屉并直接提问
  window.addEventListener('cardforge:open-drawer', (e) => {
    setOpen(true);
    const ask0 = e.detail && e.detail.ask;
    if (ask0) ask(ask0);
  });
  // 换卡时把「当前卡」的上下文交给内核（她回答会带上这张卡）
  window.addEventListener('cardforge:card-opened', () => {
    if (open) markContext();
  });
  // 设置面板里换了模型 → 抽屉芯片立刻跟上（不等刷新）
  window.addEventListener('cardforge:llm-changed', () => { loadStatus(); });

  loadStatus();
  loadPersonas();
  syncBusy();
}

export function toggle() { setOpen(!open); }

export function setOpen(v) {
  open = v;
  $('#drawer').classList.toggle('is-open', v);
  $('#drawer').setAttribute('aria-hidden', v ? 'false' : 'true');
  if (v) {
    markContext();
    if (!$('#chat-log').children.length) {
      const saved = historyList();
      if (saved.length) replay(saved);     // 有旧记录 → 先摆出来
      else greet();                        // 全新 → 打招呼
    }
    const box = $('#chat-text');
    if (box) setTimeout(() => box.focus(), 60);
  }
}

/** 把持久化的历史摆回界面（不重新请求内核）。 */
function replay(list) {
  clear($('#chat-log'));
  for (const m of list) {
    const el = push(m.who, m.text, false, { skipStore: true });
    if (m.who === 'bot') {
      const who = el.querySelector('.who');
      if (who && m.state) who.textContent = `艾莉娅 · ${stateZh(m.state)}`;
      if (m.tools && m.tools.length) addTools(el, m.tools);
      if (m.error) el.classList.add('is-error');
      addActions(el, m.text);
    }
  }
  scrollDown();
}

/* ══════════════ 状态芯片 / 人格 ══════════════ */

async function loadStatus() {
  const chip = $('#prov-chip');
  try {
    const r = await api.get('/api/assistant/status');
    if (!r.available) {
      chip.textContent = '未安装'; chip.className = 'prov-chip rule';
      chip.title = r.error + ' — ' + (r.hint || '');
      return;
    }
    if (r.provider && !['none', 'null', 'error'].includes(r.provider)) {
      // 实测在走 LLM。芯片显示**存着的那个配置名**（env 抢权时也能看见），
      // 鼠标悬停看模型与端点 —— 「谁在说话」和「你存了什么」都答得上。
      const act = r.llm_active || {};
      chip.textContent = act.active || r.provider;
      chip.className = 'prov-chip llm';
      chip.title = (act.active
        ? `${act.active}（${act.base_url || '?'}）· 模型 ${act.model || '未指定'}`
        : `走 ${r.provider}（环境变量指定，未存配置）`) +
        '\n判断仍然来自内核，LLM 只影响表达';
    } else {
      chip.textContent = '规则模式'; chip.className = 'prov-chip rule';
      const act = r.llm_active || {};
      chip.title = (act.active
        ? `存了「${act.active}」但连不上 —— ${r.hint || '启动服务后自动恢复'}`
        : (r.hint || '')).replace(/→/g, '');
    }
  } catch (e) {
    chip.textContent = '离线'; chip.className = 'prov-chip rule';
    chip.title = e.message;
  }
}

async function loadPersonas() {
  let rows = [];
  try { rows = (await api.get('/api/assistant/personas')).personas || []; }
  catch (e) { rows = [{ key: 'professional', zh: '专业' }, { key: 'lightnovel', zh: '轻小说' }]; }
  renderPersonaRow(rows);
}

function renderPersonaRow(rows) {
  const box = clear($('#persona-row'));
  for (const p of rows) {
    box.appendChild(h(`button${p.key === store.persona ? '.is-active' : ''}`,
      { dataset: { key: p.key },
        onclick: () => setPersona(p.key),
        title: p.desc || p.brief || '结论不变，只是语气不同；各人格的聊天记录分开保存' },
      p.zh || p.key));
  }
  if (!box.children.length) {
    box.appendChild(h('div.footnote', { text: '人格模块未就绪' }));
  }
}

/** 人格切换的**唯一入口**：抽屉 chips 与陪伴栏 chips 都走这里。
 *
 * 注意：**不再清空历史**。旧版切人格会 `clear(#chat-log)`，聊到一半换个语气
 * 就把记录全抹了 —— 而且切回来也找不回。现在各人格各存一份，切换只是换册子。
 */
export function setPersona(key) {
  store.persona = key;
  store.session = '';                    // 换人格 = 内核侧开新会话（上下文不串）
  $$('#persona-row button').forEach((b) => b.classList.toggle('is-active', b.dataset.key === key));
  const saved = historyList();
  if (saved.length) replay(saved);
  else { clear($('#chat-log')); greet(); }
  window.dispatchEvent(new CustomEvent('cardforge:persona', { detail: { persona: key } }));
}

/* ══════════════ 问候 ══════════════ */

function greet() {
  const spec = store.spec;
  // 问候语由内核的 persona 模板渲染（唯一真相源）；卡上下文由界面补一句。
  api.get('/api/assistant/line', { persona: store.persona, kind: 'default' })
    .then((r) => {
      const extra = spec && spec.name
        ? `\n现在看的是「${spec.display_name || spec.name}」（卡号 ${spec.id}）。`
        : '';
      const text = (r.text || '') + extra;
      say.bot(text, { state: 'guide' });
    })
    .catch(() => say.bot('我在。左边选一张卡，或者让我帮你从头造一张。', { state: 'guide' }));
}

/** 打开抽屉 / 换卡时，把「现在看的是哪张卡」写进输入框提示 —— 
 *  比往对话里插一条系统消息干净（那是环境状态，不是对话内容，
 *  插进记录里会让讨论串变啰嗦，而且刷新后还会重放出来）。 */
function markContext() {
  const box = $('#chat-text');
  if (!box) return;
  const spec = store.spec;
  box.placeholder = spec && spec.name
    ? `就「${spec.display_name || spec.name}」（${spec.id}）问点什么…`
    : '问艾莉娅…（Enter 发送）';
}

/* ══════════════ 对话 ══════════════ */

/** 内核说「不在我的数据源里」时的几种说法 —— 用来判断该不该给出口建议。 */
const NO_ANSWER_PAT = /不在我的(确定性)?数据源|没有指定卡片|不猜|给不了结论|没有返回内容/;

async function ask(text) {
  const q = String(text || '').trim();
  if (!q) return;
  say.me(q);
  const holder = push('bot', '……', true);
  window.dispatchEvent(new CustomEvent('cardforge:chat-busy', { detail: { busy: true } }));
  abort = new AbortController();
  setBusy(true);
  try {
    // 选中了卡就把「哪张卡」交给内核 —— 键名必须用内核认的 card_id/card_name。
    // 曾经这里发的是 card，后端只读 card_id，选中卡的上下文被整个丢掉，
    // 「这张卡…」只能靠「工作区唯一卡」兜底；工作区一旦有第二张卡就答不上
    // （缺陷 #34）。后端也做了 card→card_id 归一化，旧缓存页同样有效。
    const ctx = store.spec
      ? { card_id: store.spec.id, card_name: store.spec.name,
          archetype: store.spec.archetype }
      : {};
    const r = await api.post('/api/assistant/chat',
      { text: q, session: store.session, persona: store.persona, context: ctx },
      { signal: abort.signal });
    // 用户在这期间点了「停」→ 别再覆盖那条「（已停止）」
    if (holder.classList.contains('is-stopped')) return;
    store.session = r.session || store.session;
    const reply = r.reply || '（没有返回内容）';
    holder.querySelector('.body').textContent = reply;
    holder.classList.remove('thinking');
    if (r.state) holder.querySelector('.who').textContent = `艾莉娅 · ${stateZh(r.state)}`;
    if (r.fallback_reason) {
      holder.appendChild(h('div.hint', { text: '（已回退到规则通路：' + r.fallback_reason + '）' }));
    }
    if (r.tool_calls && r.tool_calls.length) addTools(holder, r.tool_calls);
    addActions(holder, reply);
    // 答不上来 → 给出她能答的几条，别让用户对着空气猜
    if (NO_ANSWER_PAT.test(reply)) suggest(holder);
    pushHistory({ who: 'bot', text: reply, state: r.state || 'guide',
      tools: (r.tool_calls || []).map((t) => t.name), ts: Date.now() });
  } catch (e) {
    if (e && (e.name === 'AbortError' || /abort/i.test(e.message || ''))) {
      // stop() 已经把那条气泡结掉了 → 不要再写一遍（会覆盖，也会多存一条历史）
      if (holder.classList.contains('is-stopped')) return;
      holder.classList.remove('thinking');
      holder.classList.add('is-stopped');
      holder.querySelector('.body').textContent = '（已停止）';
      pushHistory({ who: 'bot', text: '（已停止）', state: 'guide', ts: Date.now() });
      return;
    }
    holder.classList.remove('thinking');
    holder.classList.add('is-error');
    holder.querySelector('.body').textContent = '我这边出问题了：' + e.message;
    holder.appendChild(h('div.hint', { text: '→ ' + (e.hint || '内核的结论还是准的，审计页可以直接看') }));
    addActions(holder, '', { error: true });
    pushHistory({ who: 'bot', text: '我这边出问题了：' + e.message,
      state: 'alert', error: true, ts: Date.now() });
  } finally {
    abort = null;
    setBusy(false);
    window.dispatchEvent(new CustomEvent('cardforge:chat-busy', { detail: { busy: false } }));
  }
}

/** 主动停止（AbortController + 界面复位）。
 *
 *  ``abort.abort()`` 会让 fetch 立刻 reject，走 ask() 的 catch 收尾 ——
 *  但那种「网络已经发出去、对方不回」的情形要等内核那边真的断开，可能慢。
 *  所以这里先把界面上那条「……」结掉，别让用户点了停还看着省略号。
 *  迟到的 catch 会再写一次内容，但因为 holder 已被标记，不会重复收尾。
 */
function stop() {
  if (abort) { try { abort.abort(); } catch { /* 已结束 */ } }
  const t = $('#chat-log .msg.thinking');
  if (t) {
    t.classList.remove('thinking');
    t.classList.add('is-stopped');
    t.querySelector('.body').textContent = '（已停止）';
    pushHistory({ who: 'bot', text: '（已停止）', state: 'guide', ts: Date.now() });
  }
  setBusy(false);
}

function setBusy(v) {
  busy = v;
  const input = $('#chat-text'), btn = $('#chat-form button[type="submit"]');
  if (input) input.disabled = v;
  if (btn) {
    btn.textContent = v ? '停' : '发送';
    btn.classList.toggle('is-stop', v);
    btn.title = v ? '停止这次回答（Esc）' : '发送（Enter）';
  }
  $('#chat-log').classList.toggle('is-busy', v);
}
function syncBusy() { setBusy(false); }

async function explainGate(gate, rep) {
  if (!open) setOpen(true);
  say.me(`帮我看看 ${gate} 的结论`);
  const holder = push('bot', '……', true);
  window.dispatchEvent(new CustomEvent('cardforge:chat-busy', { detail: { busy: true } }));
  abort = new AbortController();
  setBusy(true);
  try {
    const r = await api.post('/api/assistant/explain', {
      report: rep, gate, card: store.spec ? store.spec.id : undefined,
      session: store.session, persona: store.persona
    }, { signal: abort.signal });
    if (holder.classList.contains('is-stopped')) return;
    const text = r.text || pretty(rep);
    holder.querySelector('.body').textContent = text;
    holder.classList.remove('thinking');
    addActions(holder, text);
    pushHistory({ who: 'bot', text, state: 'guide', ts: Date.now() });
  } catch (e) {
    holder.classList.remove('thinking');
    holder.classList.add('is-error');
    const text = `翻译不可用（${e.message}）。原文结论：\n` + summarize(rep);
    holder.querySelector('.body').textContent = text;
    addActions(holder, text, { error: true });
    pushHistory({ who: 'bot', text, state: 'alert', error: true, ts: Date.now() });
  } finally {
    abort = null;
    setBusy(false);
    window.dispatchEvent(new CustomEvent('cardforge:chat-busy', { detail: { busy: false } }));
  }
}

function summarize(rep) {
  const iss = rep.issues || [];
  const n = (lv) => iss.filter((i) => i.level === lv).length;
  return `状态 ${rep.status}；ERROR ${n('ERROR')}、WARN ${n('WARN')}、INFO ${n('INFO')}。` +
    (rep.degraded ? ` 降级说明：${rep.degraded}` : '') +
    (iss.length ? '\n' + iss.map((i) => `· [${i.level}] ${i.code} ${i.message}`).join('\n') : '');
}

/* 内核状态键：guide / working / alert / pass（与 persona.STATE_KEYS 一致） */
function stateZh(s) {
  return { guide: '引导', working: '工作中', alert: '报警', pass: '通过',
    thinking: '思考中', degraded: '降级' }[s] || s;
}

/* ══════════════ 消息落库 + 渲染 ══════════════
   say 家族：既上屏、又写历史。所有「一条新消息」都必须走这里，
   免得出现「界面上有、刷新后没了」的不一致。 */

const say = {
  /** 用户说的话。 */
  me(text) {
    const el = push('me', text);
    pushHistory({ who: 'me', text, ts: Date.now() });
    return el;
  },
  /** 艾莉娅定稿的一句话。 */
  bot(text, meta = {}) {
    const el = push('bot', text);
    if (meta.state) el.querySelector('.who').textContent = `艾莉娅 · ${stateZh(meta.state)}`;
    addActions(el, text);
    pushHistory({ who: 'bot', text, state: meta.state || 'guide', ts: Date.now() });
    return el;
  },
};

function push(who, text, thinking = false, { skipStore = false } = {}) {
  const log = $('#chat-log');
  const bodyEl = h('div.body', { text });
  const col = h('div.col', {},
    who === 'bot' ? h('span.who', { text: '艾莉娅' }) : null, bodyEl);
  const el = h(`div.msg.${who}${thinking ? '.thinking' : ''}`, {},
    who === 'bot' ? h('img.avatar', { src: 'assets/aria/aria_avatar.png', alt: '' }) : null,
    col);
  log.appendChild(el);
  scrollDown();
  return el;
}

function addTools(el, calls) {
  const names = calls.map((t) => (typeof t === 'string' ? t : t.name)).filter(Boolean);
  if (names.length) el.appendChild(h('div.tools', { text: '调用了：' + names.join('、') }));
}

/** 给一条机器人回答挂上「复制 / 重试」。 */
function addActions(el, text, { error = false } = {}) {
  if (!text && !error) return;
  const bar = h('div.msg-acts');
  if (text) {
    bar.appendChild(h('button.act', {
      title: '复制这段回答',
      onclick: async (e) => {
        try {
          await navigator.clipboard.writeText(text);
          const b = e.currentTarget; b.textContent = '已复制'; b.disabled = true;
          setTimeout(() => { b.textContent = '复制'; b.disabled = false; }, 1400);
        } catch { toast('复制失败（浏览器未授权剪贴板）', { kind: 'warn' }); }
      },
    }, '复制'));
  }
  bar.appendChild(h('button.act', {
    title: '就上一个问题再问一次',
    onclick: () => retry(),
  }, '重试'));
  el.appendChild(bar);
}

/** 找到最后一条用户消息，重发一次（并把它上面的问答从记录里去掉）。 */
function retry() {
  const all = loadStore();
  const list = Array.isArray(all[store.persona]) ? all[store.persona] : [];
  let i = list.length - 1;
  while (i >= 0 && list[i].who !== 'me') i--;       // 回溯到最后一条提问
  if (i < 0) { toast('没有可重试的问题', { kind: 'warn' }); return; }
  const q = list[i].text;
  // 丢掉这条提问及其之后的内容，避免记录里出现连续两条一样的问题
  all[store.persona] = list.slice(0, i);
  saveStore(all);
  replay(all[store.persona]);
  ask(q);
}

/** 内核答不上来时，给出几条**她确实能答**的问题，一条 onClick 直接发。 */
function suggest(el, items = null) {
  const list = items || [
    '这张卡的平衡审计结果怎么样？',
    '解释一下刚才质量门的结论',
    '这个系列还缺什么卡？',
    '帮我看看卡文有没有 PSCT 问题',
  ];
  const box = h('div.msg-suggest', {}, h('span.tip', { text: '可以试这些：' }));
  for (const q of list) {
    box.appendChild(h('button', { onclick: () => ask(q) }, q));
  }
  el.appendChild(box);
}

function scrollDown() {
  const log = $('#chat-log');
  if (log) log.scrollTop = log.scrollHeight;
}

/* ══════════════ 清空 ══════════════ */

function confirmClear() {
  const n = historyList().length;
  if (!n) { toast('这个人格下还没有对话', { kind: 'warn' }); return; }
  if (!window.confirm(`清空「${personaZh()}」人格下的 ${n} 条对话记录？\n` +
    '（只清界面记录，内核的会话也会重置）')) return;
  clearHistory();
  store.session = '';
  clear($('#chat-log'));
  greet();
  toast('已清空这个人格的对话', { kind: 'ok' });
}

function personaZh() {
  const b = $(`#persona-row button[data-key="${store.persona}"]`);
  return (b && b.textContent) || store.persona;
}

function esc(s) {
  return String(s ?? '').replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
}
