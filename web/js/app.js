/* ══════════════════════════════════════════════════════════════════
   启动。界是壳：所有判断都来自 Python 内核，这里只做展示与编排。
   ══════════════════════════════════════════════════════════════════ */

import { api, store, boot } from './state.js';
import { $, $$, clear, h, toast, modal, pretty, debounce } from './ui.js';
import { initSpec, save as saveSpec, previewNow } from './spec.js';
import { initText } from './text.js';
import { initArt } from './art.js';
import { initPack } from './pack.js';
import { initGates, openGate, setGate } from './gates.js';
import { initAssistant } from './assistant.js';
import { initAria } from './aria.js';
import { initArchetype } from './archetype.js';
import { initSettings } from './settings.js';

const LS_KEY = 'cardforge.ui.v1';
const ui = loadUi();
// 深链（?card=&stage=&panel=）与"浏览器恢复上次滚动位置"是打架的：
// 恢复发生在脚本之后，会把画面又滚回上一轮的面板。关掉自动恢复，
// 由下面 start() 里的显式滚动决定画面停在哪。
try { history.scrollRestoration = 'manual'; } catch { /* 老浏览器没有这个属性 */ }

/** URL 深链：``?card=210000021&stage=text&panel=summon``。
 *
 *  存在的理由有两个：① 卡链接可以直接发给别人；② 录屏/自测能以无头浏览器
 *  精确复现某个界面状态。**只本次导航生效**：card/stage 顺手记进会话偏好，
 *  panel 不持久化 —— 否则一次 ``?panel=summon`` 会把之后每次打开都滚到那里。 */
const deep = (() => {
  let q;
  try { q = new URLSearchParams(location.search); } catch { return { panel: '' }; }
  const out = { panel: q.get('panel') || '' };
  const card = parseInt(q.get('card') || '', 10);
  if (card) ui.cardId = card;
  const stage = q.get('stage') || '';
  if (['spec', 'text', 'art', 'pack'].includes(stage)) ui.stage = stage;
  return out;
})();

function loadUi() {
  try { return JSON.parse(localStorage.getItem(LS_KEY) || '{}'); } catch { return {}; }
}
function saveUi() {
  try { localStorage.setItem(LS_KEY, JSON.stringify(ui)); } catch { /* 隐私模式里会失败，忽略 */ }
}

/* ══════════════ 启动进度（页面这一侧）═════════════
   与终端进度条同源：**每一步都挂在真实的 await 上**（自检 → 装配 → 读卡），
   不演戏。启动完成后整个面板淡出移除。 */
let bootUI = null;

function bootStart() {
  if (bootUI) return;
  bootUI = h('div.boot-overlay#app-boot', {},
    h('div.boot-card', {},
      h('img.boot-avatar', { src: 'assets/aria/aria_avatar.png', alt: '' }),
      h('div.boot-title', { text: '卡锻工坊 · 启动中' }),
      h('div.boot-bar', {}, h('i.boot-fill')),
      h('div.boot-step', { text: '正在自检环境…' })));
  document.body.appendChild(bootUI);
  requestAnimationFrame(() => bootUI && bootUI.classList.add('is-on'));
}

function bootStep(text, frac) {
  if (!bootUI) return;
  const fill = bootUI.querySelector('.boot-fill');
  const step = bootUI.querySelector('.boot-step');
  if (fill) fill.style.width = Math.round(Math.max(0, Math.min(1, frac)) * 100) + '%';
  if (step && text) step.textContent = text;
}

function bootDone() {
  if (!bootUI) return;
  const el = bootUI;
  bootUI = null;
  el.classList.add('is-done');
  setTimeout(() => el.remove(), 420);
}

function bootFail(e) {
  if (!bootUI) return;
  const card = bootUI.querySelector('.boot-card');
  bootUI.classList.add('is-failed');
  if (card) {
    card.appendChild(h('div.boot-err', {},
      h('b', { text: '界面起不来：' }), String((e && e.message) || e), h('br'),
      h('span', { text: '→ ' + ((e && e.hint) || '跑一次 python -m cardforge doctor 看缺什么') })));
  }
}

/* ══════════════ 启动 ══════════════ */
async function start() {
  bootStart();
  bootStep('正在自检环境…', 0.12);
  let meta;
  try {
    ({ meta } = await boot());
  } catch (e) {
    fatal(e);
    return;
  }
  bootStep('环境自检完成，正在装配界面…', 0.5);
  renderLevels();
  renderRailFoot();

  initSpec(); initText(); initArt(); initPack(); initGates(); initAssistant();
  initAria();
  initArchetype();
  initSettings();
  switchStage(ui.stage || 'spec');
  bindNav();
  bindRail();
  bindKeys();
  bindHero();
  bindUnloadGuard();

  bootStep('正在读取工作区…', 0.78);
  const list = await refreshCards();
  const wanted = ui.cardId && list.some((c) => c.id === ui.cardId) ? ui.cardId
    : (list[0] && list[0].id);
  if (wanted) { showHero(false); await openCard(wanted); }
  else { newCardDraft(); showHero(true); }
  if (deep.panel) {
    // 深链指定的面板：滚过去，省得录屏/检查时画面停在最上面
    const el = $(`#b-${deep.panel}`);
    if (el && !el.hidden) el.scrollIntoView({ block: 'start' });
  } else {
    // 没指定面板就回到顶部（浏览器会按会话恢复上一次的滚动位置，
    // 深链截图就会拍到意料之外的面板）。等一帧，让布局先落地。
    requestAnimationFrame(() => {
      for (const el of [document.scrollingElement, ...$$('.pane-body')]) {
        if (el) el.scrollTop = 0;
      }
    });
  }
  bootStep('就绪', 1);
  bootDone();
  clear($('main .booting'));
}

function fatal(e) {
  const msg = String((e && e.message) || e);
  const hint = (e && e.hint) || '跑一次 python -m cardforge doctor 看缺什么';
  if (bootUI) { bootFail(e); return; }       // 启动面板里直接显示，别切走
  const box = document.querySelector('.workspace') || document.body;
  clear(box).appendChild(h('div.notice.bad', {},
    h('b', { text: '界面起不来：' }), msg, h('br'),
    h('span', { text: '→ ' + hint })));
}

/* ══════════════ 顶栏能力指示 ══════════════ */
function renderLevels() {
  const box = clear($('#levels'));
  const lv = (store.state && store.state.levels) || {};
  const defs = [
    ['L0', '数据层', lv['L0-data'] || true, '永远可用：规格、卡文、导出、校验'],
    ['L1', '渲染', lv['L1-render'], '卡面 PNG 合成。缺 Pillow 时退回矢量预览'],
    ['L2', '出图', lv['L2-art'], '本机 ComfyUI。不在时用「上传我自己的图」'],
    ['L3', '对局', lv['L3-duel'] === 'ocgcore' ? true : 'degraded',
      (lv['L3-duel'] === 'ocgcore' ? '真开一局跑给你看'
        : '引擎不在，G3 只给静态校验结论（界面会写明「未运行」）')],
  ];
  for (const [k, label, on, why] of defs) {
    box.appendChild(h('span.lvl', { dataset: { on: on === 'degraded' ? 'degraded' : (on ? '1' : '0') },
      title: `${label}：${why}` }, k));
  }
}

/* ══════════════ 阶段切换 ══════════════ */
function bindNav() {
  $('#stages').addEventListener('click', (e) => {
    const b = e.target.closest('.stage-tab');
    if (b) switchStage(b.dataset.stage);
  });
}

export function switchStage(name) {
  ui.stage = name; saveUi();
  showHero(false);                       // 用户要干活了，欢迎态先退场
  $$('.stage-tab').forEach((b) => b.classList.toggle('is-active', b.dataset.stage === name));
  $$('.stage-panel').forEach((p) => p.classList.toggle('is-active', p.dataset.stage === name));
  window.dispatchEvent(new CustomEvent('cardforge:stage', { detail: { stage: name } }));
}

/* ══════════════ 欢迎态（列表为空时看到的第一屏）══════════════ */
function showHero(v) {
  const hero = $('#studio-hero');
  if (!hero) return;
  hero.hidden = !v;
  if (v) $$('.stage-panel').forEach((p) => p.classList.remove('is-active'));
  else {
    const cur = (ui.stage || 'spec');
    $$('.stage-panel').forEach((p) => p.classList.toggle('is-active', p.dataset.stage === cur));
  }
}

function bindHero() {
  const n = $('#hero-new');
  if (n) n.addEventListener('click', () => createCard());
  const g = $('#hero-guide');
  if (g) g.addEventListener('click', () => {
    window.dispatchEvent(new CustomEvent('cardforge:open-drawer',
      { detail: { ask: '带我走一遍造卡的完整流程。' } }));
  });
}

/* 有未保存的表单改动时，离开页面前留一句。 */
function bindUnloadGuard() {
  window.addEventListener('beforeunload', (e) => {
    if (store.isDirty()) {
      e.preventDefault();
      e.returnValue = '';               // 浏览器原生的「确定要离开吗」
    }
  });
}

function bindKeys() {
  document.addEventListener('keydown', (e) => {
    if (!(e.ctrlKey || e.metaKey)) return;
    const k = e.key.toLowerCase();
    if (k === 's') { e.preventDefault(); saveSpec(); }
    else if (k === 'enter') { e.preventDefault(); saveSpec().then(() => toast('已保存', { kind: 'ok' })); }
    else if (k >= '1' && k <= '4') { e.preventDefault(); switchStage(['spec', 'text', 'art', 'pack'][+k - 1]); }
  });
}

/* ══════════════ 卡片列表 ══════════════ */
function bindRail() {
  $('#btn-new-card').addEventListener('click', () => createCard());
  $('#card-search').addEventListener('input', debounce(() => renderList($('#card-search').value), 200));
  $('#card-list').addEventListener('click', (e) => {
    const li = e.target.closest('li[data-id]');
    if (li) openCard(parseInt(li.dataset.id, 10));
  });
  const updBtn = $('#btn-update');
  if (updBtn) updBtn.addEventListener('click', checkUpdate);
}

/* ══════════════════════════════════════════════════════════════════
   更新检测 —— 本地版本 vs GitHub main（走 api.github.com）
   ══════════════════════════════════════════════════════════════════ */
async function checkUpdate() {
  const btn = $('#btn-update');
  if (!btn || btn.dataset.busy) return;
  btn.dataset.busy = '1';
  const label = btn.innerHTML;
  btn.innerHTML = '<span class="btn-glyph" aria-hidden="true">⭳</span>检查中…';
  try {
    const r = await api.get('/api/update/check');
    if (!r.ok) {
      toast('更新检查失败：' + (r.error || '网络不可达'),
            { kind: 'err', hint: r.hint || '需要能访问 api.github.com；不影响本地使用' });
    } else if (r.update_available) {
      toast(`有新版本：${r.local_version} → ${r.remote_version}`,
            { kind: 'ok', hint: r.hint || '', ms: 10000 });
      if (r.url) window.open(r.url, '_blank', 'noopener');
    } else {
      toast(r.hint || `已是最新版本（${r.local_version}）`, { kind: 'ok' });
    }
  } catch (e) {
    toast('更新检查失败：' + e.message, { kind: 'err', hint: '需要能访问 api.github.com' });
  } finally {
    delete btn.dataset.busy;
    btn.innerHTML = label;
  }
}

export async function refreshCards() {
  try {
    const r = await api.get('/api/cards');
    store.set('cards', r.cards || []);
    renderList($('#card-search') ? $('#card-search').value : '');
    return r.cards || [];
  } catch (e) {
    toast('卡片列表读不出来：' + e.message, { kind: 'err', hint: e.hint });
    return [];
  }
}

function renderList(q = '') {
  const box = clear($('#card-list'));
  const items = (store.cards || []).filter((c) => {
    if (!q) return true;
    const s = q.toLowerCase();
    return String(c.id).includes(s) || (c.name || '').toLowerCase().includes(s)
      || (c.archetype || '').toLowerCase().includes(s);
  });
  if (!items.length) {
    box.appendChild(h('li.empty', { text: q ? '没有匹配的卡' : '工作区还是空的，点「+ 新卡」开始' }));
    return;
  }
  for (const c of items) {
    box.appendChild(h(`li${c.id === store.cardId ? '.is-active' : ''}`, { dataset: { id: c.id } },
      h('span.cname', { text: c.name || '（无名）' }),
      h('span.cmeta', { text: `${c.id} · ${c.frame_label || c.frame}` +
        (c.archetype ? ` · ${c.archetype}` : '') +
        (c.n_effects ? ` · ${c.n_effects} 效果` : '') })));
  }
}

function renderRailFoot() {
  const box = $('#rail-foot');
  const c = (store.state && store.state.counts) || {};
  clear(box).append(
    h('div', { text: `卡 ${c.cards || 0} · 系列 ${c.archetypes || 0} · 卡组 ${c.decks || 0}` }),
    h('div', { text: (store.state && store.state.pool && store.state.pool.available)
      ? '官方卡池已挂载' : '官方卡池未挂载（查重会跳过）' }));
}

export async function openCard(id) {
  try {
    const r = await api.get(`/api/cards/${id}`, { gates: 'G1,G2' });
    store.cardId = id;
    store.cardExists = true;
    ui.cardId = id; saveUi();
    store.set('spec', r.spec);
    store.spec = r.spec;
    // 后端在 spec 还没脚本时会**现场投影一份预览**（质量门就看这份）。
    // 界面必须说清楚它是预览，否则就是「面板写着没有脚本，门却在报脚本的错」。
    store.luaPreview = r.lua_preview ? (r.lua || '') : '';
    store.markSaved();
    if (r.gates) Object.entries(r.gates).forEach(([g, rep]) => setGate(g, rep));
    store.set('card', r.spec);
    renderList($('#card-search') ? $('#card-search').value : '');
    $('#notice') && clear($('#notice'));
    // 告诉全局「换卡了」—— 助手抽屉靠这个事件把输入框提示从旧卡名换成新卡名
    // （曾经只有监听没有派发，placeholder 停在打开抽屉时那一张上）。
    window.dispatchEvent(new CustomEvent('cardforge:card-opened',
      { detail: { id, spec: r.spec } }));
    return r;
  } catch (e) {
    toast('打不开这张卡：' + e.message, { kind: 'err', hint: e.hint });
    return null;
  }
}

/** 未落盘的草稿：给一套能直接改的默认值，而不是空表单让人懵。 */
export function newCardDraft() {
  const spec = {
    id: 0, name: '', frame: 'effect', attribute: '暗', race: '魔法师族',
    level: 4, atk: 1600, dfd: 1200, setcode: '0x0', archetype: '',
    name_i18n: {}, text_i18n: {}, pendulum_text_i18n: {}, flavor: '',
    effects: [], tags: [], link_markers: [], pendulum_effect_indices: [],
    summon: { materials: [], methods: [], limit: '', cannot_be_material: [],
      ritual_spell: '', ritual_spell_archetype: false },
    render: { rarity: 'common', lang_name: 'zh_cn', lang_text: 'zh_cn',
      lang_flavor: 'zh_cn', fullart: { mode: 'none' }, psct_bold: true,
      show_laser: true, show_password: true, show_copyright: true,
      art_fit: 'cover', art_scale: 1, art_offset_y: 0 },
  };
  store.cardId = 0; store.cardExists = false;
  store.spec = spec; store.saved = null;
  store.set('card', spec);
  switchStage('spec');
  return spec;
}

async function createCard() {
  const spec = newCardDraft();
  const name = prompt('这张卡叫什么？（先给卡名，其他都能在表单里改）', '');
  if (name === null) return;
  spec.name = name.trim();
  if (!spec.name) { toast('没填卡名，已建一张空白草稿', { kind: 'warn' }); return; }
  store.emit('spec:patch', spec);
  await saveSpec();
  await refreshCards();
  showHero(false);
}

window.addEventListener('cardforge:saved', async () => {
  await refreshCards();
  renderLevels();
});

/* ══════════════ 顶栏调试入口 ══════════════ */
function bindDebug() {
  const b = h('button.ghost-btn', { title: '环境自检报告（原始 JSON）',
    onclick: async () => {
      try {
        const r = await api.get('/api/doctor');
        modal({ title: '环境自检', body: h('pre.code-view', { text: pretty(r) }) });
      } catch (e) { toast('取不到：' + e.message, { kind: 'err' }); }
    } }, '自检');
  $('#topbar').insertBefore(b, $('#btn-assistant'));
}

/* 模块脚本是 deferred 的，正常情况下 DOMContentLoaded 还没触发；
   但如果脚本被缓存/延迟到事件之后（浏览器行为不一致），监听器就永远等不到。
   所以两种情况都要覆盖 —— 这类「界面全白但没有任何报错」最难查。 */
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => { start().then(bindDebug); });
} else {
  start().then(bindDebug);
}
