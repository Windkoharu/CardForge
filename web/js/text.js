/* ══════════════════════════════════════════════════════════════════
   阶段 2 · 卡文（PSCT）与脚本（Lua）
   ──────────────────────────────────────────────────────────────────
   两边共用同一个效果 IR：卡文是给玩家读的，脚本是给引擎执行的，
   二者都由内核从同一份定义投影出来，所以不会出现「文本说一套、脚本做一套」。
   ══════════════════════════════════════════════════════════════════ */

import { api, store } from './state.js';
import { $, $$, clear, h, renderIssues, toast, modal, pretty } from './ui.js';

/** 给艾莉娅（立绘陪伴栏）播报一次任务结果；facts 必须是内核返回的字段。 */
function ariaJob(state, label, facts) {
  window.dispatchEvent(new CustomEvent('cardforge:job', { detail: { state, label, facts } }));
}

const NATIVE = ['zh_cn', 'zh_tw', 'ja', 'en', 'ko'];
let langs = ['zh_cn'];
let currentLang = 'zh_cn';

export function initText() {
  renderLangPicker();
  store.on('card', () => { loadStored(); });
  $('#btn-compose').addEventListener('click', compose);
  $('#btn-ai-draft').addEventListener('click', aiDraft);
  $('#btn-lint-text').addEventListener('click', lintText);
  $('#btn-write-text').addEventListener('click', writeBack);
  $('#btn-emit').addEventListener('click', emitLua);
  $('#btn-lint-lua').addEventListener('click', lintLua);
  $('#btn-write-lua').addEventListener('click', writeLua);
  $('#text-editor').addEventListener('input', () => {
    if (!store.spec) return;
    store.spec.text_i18n = Object.assign({}, store.spec.text_i18n, { [currentLang]: $('#text-editor').value });
    store.patch({});
  });
}

function renderLangPicker() {
  const box = $('#text-lang');
  clear(box);
  const table = (store.meta && store.meta.langs) || {};
  for (const k of NATIVE.filter((x) => x in table)) {
    const cb = document.createElement('input');
    cb.type = 'checkbox'; cb.checked = langs.includes(k); cb.value = k;
    cb.addEventListener('change', () => {
      langs = $$('#text-lang input').filter((i) => i.checked).map((i) => i.value);
      if (!langs.length) { cb.checked = true; langs = [k]; }
    });
    cb.addEventListener('click', (e) => {
      e.stopPropagation();
      currentLang = k;
      $$('#text-lang label').forEach((l) => l.classList.remove('is-active'));
      cb.closest('label').classList.add('is-active');
      const t = (store.spec && store.spec.text_i18n || {})[k];
      $('#text-editor').value = t || '';
    });
    box.appendChild(h('label' + (k === currentLang ? '.is-active' : ''), { title: table[k].zh_cn || k },
      cb, h('span', { text: (table[k].zh_cn || k).replace('中文', '') })));
  }
}

function loadStored() {
  const spec = store.spec;
  if (!spec) { $('#text-editor').value = ''; return; }
  currentLang = currentLang && spec.text_i18n && spec.text_i18n[currentLang]
    ? currentLang : (spec.render && spec.render.lang_text) || 'zh_cn';
  $('#text-editor').value = (spec.text_i18n || {})[currentLang] || '';
  $('#lua-view').textContent = spec.lua || '// 还没有脚本';
  $$('#text-lang label').forEach((l) => l.classList.remove('is-active'));
}

function needCard() {
  if (!store.spec) { toast('先选中一张卡', { kind: 'warn' }); return false; }
  return true;
}

/* ══════════════ 卡文 ══════════════ */
async function compose() {
  if (!needCard()) return;
  const r = await api.post('/api/psct/compose',
    { card: store.spec.id, langs }, {}).catch(errPayload);
  if (!r.ok) { toast(r.error || '生成失败', { kind: 'err', hint: r.hint }); return; }
  const out = r.langs || {};
  const first = langs[0];
  const got = out[first] || {};
  $('#text-editor').value = got.text || '';
  if (!got.text) {
    toast('生成了空文本', { kind: 'warn',
      hint: '效果列表是空的。先在规格页加效果，或用「从卡文推断」把已有文本结构化。' });
    ariaJob('alert', '生成卡文', '效果列表是空的，没生成出文本。');
  } else if (got.degraded) {
    toast(`${first} 没有原生句式模板，已退回 ${got.used_lang}`, { kind: 'warn', hint: got.reason || '' });
    ariaJob('alert', '生成卡文', `${first} 没有原生句式模板（内核已退回 ${got.used_lang}）。`);
  } else {
    toast('已生成 ' + Object.keys(out).length + ' 种语言的卡文', { kind: 'ok',
      hint: '这只是草稿，点「写回规格」才会保存' });
    ariaJob('pass', '生成卡文', `卡文已生成：${Object.keys(out).length} 种语言，仍待写回规格。`);
  }
  showComposeDetail(out);
}

function showComposeDetail(perLang) {
  const rows = Object.entries(perLang).map(([lang, v]) =>
    h('tr', {},
      h('td', { text: lang }),
      h('td', { text: (v.text || '（空）').slice(0, 120) }),
      h('td', { text: v.degraded ? `退回 ${v.used_lang}` : (v.source || '') }),
      h('td', { text: v.reason || '' })));
  modal({
    title: '各语言生成结果',
    body: h('table.grid', {}, h('thead', {}, h('tr', {},
      h('th', { text: '语言' }), h('th', { text: '文本' }),
      h('th', { text: '来源' }), h('th', { text: '说明' }))),
      h('tbody', {}, rows)),
  });
}

/* ══════════════ AI 起草（LLM 提议 → 内核裁决） ══════════════ */
async function aiDraft() {
  if (!needCard()) return;
  const spec = store.spec;
  const kinds = (spec.effects || []).map((e) => e.kind).filter(Boolean);
  const ta = h('textarea#draft-concept', {
    rows: 5, spellcheck: 'false',
    placeholder: '例：这张卡翻转时，把墓地 1 只怪兽特殊召唤。\n' +
      (kinds.length ? `（已定义效果：${kinds.join('、')} —— 写概念时会一并交给模型）` : ''),
  });
  ta.value = spec.flavor || '';
  const go = h('button.mini-btn.alt', { text: '起草' });
  const m = modal({
    title: 'AI 起草卡文',
    body: h('div', {},
      h('p.footnote', { text: '大模型只提议草稿；问题清单与门结论由内核校验器（PSCT 规则 + G1）确定性给出，模型的自评不采信。' }),
      ta),
    actions: [
      { label: '取消' },
      { label: '起草', class: 'mini-btn alt', keepOpen: true, onClick: async () => {
        const concept = ta.value.trim();
        if (!concept) { toast('先写一句概念描述', { kind: 'warn' }); return; }
        go.disabled = true; go.textContent = '起草中…';
        const r = await api.post('/api/assistant/draft',
          { concept, card: spec.id, lang: currentLang }, {}).catch(errPayload);
        go.disabled = false; go.textContent = '起草';
        if (!r.ok) { m.close(); showDraftFailure(r); return; }
        m.close();
        showDraftResult(r);
        ariaJob('working', 'AI 起草卡文',
          `草稿已由 ${r.provider || '模型'} 提议，内核报出 ${(r.counts || {}).error || 0} ERROR。`);
      } },
    ],
  });
}

/** 没配大模型 / 调用失败：如实说，并给一条能走通的路。 */
function showDraftFailure(r) {
  const body = h('div', {},
    h('p', { text: r.error || r.degraded || '起草失败' }),
    r.hint ? h('p.footnote', { text: '→ ' + r.hint }) : null);
  const actions = [{ label: '关闭' }];
  if (r.degraded) {
    actions.push({ label: '去设置模型', class: 'mini-btn alt', onClick: () => $('#btn-settings').click() });
  }
  modal({ title: 'AI 起草不可用', body, actions });
  ariaJob('alert', 'AI 起草卡文', r.degraded ? '没有可用的大模型，草稿没有生成。' : String(r.error || ''));
}

function showDraftResult(r) {
  const c = r.counts || {};
  const view = h('textarea.draft-view', { readonly: true, rows: 10, spellcheck: 'false' });
  view.value = r.draft || '';
  const issuesBox = h('div.issues');
  const parts = [
    h('p.footnote', { text: `模型：${r.provider || '未知'}${r.model ? ' · ' + r.model : ''} ｜ 内核结论：${c.error || 0} ERROR、${c.warn || 0} WARN、${c.info || 0} INFO` }),
    view,
    h('p.footnote', { text: '内核校验器的问题清单（逐条可放行前先读懂）：' }),
    issuesBox,
  ];
  if (r.gate) {
    parts.push(h('p.footnote', { text: `G1 平衡审计（对象是规格本身，不是草稿文字）：${r.gate.status} —— ${r.gate.summary || ''}` }));
  } else if (r.gate_degraded) {
    parts.push(h('p.footnote', { text: `G1：${r.gate_degraded}` }));
  }
  if (r.degraded) parts.push(h('p.footnote', { text: r.degraded }));
  modal({
    title: '起草结果（草稿只是提议，过目后再用）',
    body: h('div', {}, ...parts),
    actions: [
      { label: '关闭' },
      { label: '填入编辑器', class: 'mini-btn alt', onClick: () => {
        $('#text-editor').value = r.draft || '';
        if (store.spec) {
          store.spec.text_i18n = Object.assign({}, store.spec.text_i18n,
            { [currentLang]: $('#text-editor').value });
          store.patch({});
        }
        toast('已填入编辑器', { kind: 'ok', hint: '点「写回规格」才会保存；「校验」可复查' });
      } },
    ],
  });
  renderIssues(issuesBox, r.issues, { emptyText: 'PSCT 校验没有发现问题' });
}

async function lintText() {
  if (!needCard()) return;
  const r = await api.post('/api/psct/lint',
    { spec: editable(), langs }, {}).catch(errPayload);
  renderIssues($('#text-issues'), r.ok ? r.issues : [{ level: 'ERROR', code: 'LINT',
    message: r.error, hint: r.hint }]);
  if (r.ok) toast(r.errors ? `${r.errors} 个错误需要处理` : '校验通过',
    { kind: r.errors ? 'err' : 'ok', hint: '错误级会拦住 G-文本，警告级可以放行' });
  if (r.ok) {
    ariaJob(r.errors ? 'alert' : 'pass', '卡文校验',
      r.errors ? `卡文校验报出 ${r.errors} 个 ERROR。` : '卡文校验：没有 ERROR。');
  } else {
    ariaJob('alert', '卡文校验', String(r.error || '校验没跑成'));
  }
}

async function writeBack() {
  if (!needCard()) return;
  const spec = JSON.parse(JSON.stringify(store.spec));
  spec.text_i18n = Object.assign({}, spec.text_i18n, { [currentLang]: $('#text-editor').value });
  try {
    await api.put(`/api/cards/${spec.id}`, spec);
    store.spec = spec; store.markSaved(); store.set('card', spec);
    toast('卡文已写回规格', { kind: 'ok', hint: '下一步：卡面渲染会直接用它' });
    window.dispatchEvent(new CustomEvent('cardforge:saved'));
  } catch (e) { toast('写回失败：' + e.message, { kind: 'err', hint: e.hint }); }
}

/* ══════════════ Lua ══════════════ */
async function emitLua() {
  if (!needCard()) return;
  const r = await api.post('/api/lua/emit', { card: store.spec.id, tier: 1 }, {})
    .catch(errPayload);
  if (!r.ok) {
    $('#lua-view').textContent = `-- 无法生成脚本\n-- ${r.error}\n-- ${r.hint || ''}`;
    toast(r.error || '脚本生成失败', { kind: 'err', hint: r.hint });
    return;
  }
  $('#lua-view').textContent = r.lua || '-- 空脚本';
  const todos = (r.lua.match(/需人工补写/g) || []).length;
  toast(todos ? `脚本已生成，有 ${todos} 处需要人工补写` : '脚本已生成',
    { kind: todos ? 'warn' : 'ok',
      hint: todos ? '这些位置内核不认，写成注释而不是假代码 —— 宁缺毋滥' : '' });
  lintLua({ silent: true });
}

async function lintLua({ silent = false } = {}) {
  if (!needCard()) return;
  const lua = $('#lua-view').textContent;
  if (!lua.trim() || lua.startsWith('// 无法生成')) {
    if (!silent) toast('没有可检查的脚本', { kind: 'warn' });
    return;
  }
  const r = await api.post('/api/lua/lint', { lua, spec: editable() }, {}).catch(errPayload);
  const box = $('#lua-issues');
  if (!r.ok) {
    renderIssues(box, [{ level: 'ERROR', code: 'LUA_LINT', message: r.error, hint: r.hint }]);
    return;
  }
  const extra = [];
  const un = r.unknown || {};
  for (const key of ['functions', 'constants', 'methods', 'other']) {
    const list = un[key];
    if (list && (Array.isArray(list) ? list.length : Object.keys(list).length)) {
      extra.push({ level: 'ERROR', code: 'LUA_UNKNOWN_' + key.toUpperCase(),
        message: `引用了白名单之外的 ${key}：${fmtList(list)}`,
        hint: '这个 build 的 Lua API 里不存在它。引擎会直接报错 —— 换写法或删掉这段' });
    }
  }
  if (!r.syntax.ok) extra.unshift({ level: 'ERROR', code: 'LUA_SYNTAX',
    message: '语法检查不通过：' + (r.syntax.reason || ''), hint: '看行号定位括号/end 配对' });
  renderIssues(box, (r.issues || []).concat(extra),
    { emptyText: '静态检查干净（这不代表真能跑，要过 G3）' });
  if (!silent) toast(extra.length ? '有问题，看下面' : '静态检查通过',
    { kind: extra.length ? 'err' : 'ok' });
}

async function writeLua() {
  if (!needCard()) return;
  const r = await api.post('/api/lua/emit', { card: store.spec.id, write: true }, {})
    .catch(errPayload);
  if (!r.ok) { toast('写入失败：' + (r.error || ''), { kind: 'err', hint: r.hint }); return; }
  store.spec.lua = r.lua;
  $('#lua-view').textContent = r.lua;
  toast('脚本已写入工作区', { kind: 'ok',
    hint: r.script_path ? r.script_path + ' · 下一步：导出包会带上它' : '' });
}

function fmtList(x) {
  if (Array.isArray(x)) return x.slice(0, 8).join('、') + (x.length > 8 ? ` …共 ${x.length} 项` : '');
  if (x && typeof x === 'object') return Object.keys(x).slice(0, 8).join('、');
  return String(x);
}

/** 提交给校验器/生成器的规格：带上编辑器里未保存的文本，避免「界面看到 A、内核校验 B」。 */
function editable() {
  const s = JSON.parse(JSON.stringify(store.spec || {}));
  s.text_i18n = Object.assign({}, s.text_i18n, { [currentLang]: $('#text-editor').value });
  delete s.type_bits; delete s.race_bits; delete s.attr_bits;
  delete s.link_bits; delete s.def_value; delete s.schema_version;
  return s;
}

function errPayload(e) { return { ok: false, error: e.message, hint: e.hint }; }
