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
  $('#btn-tidy-text').addEventListener('click', tidyText);
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
  const lv = $('#lua-view');
  if (spec.lua) { lv.textContent = spec.lua; lv.classList.remove('is-preview'); }
  else if (store.luaPreview) {
    // 这份是后端按当前规格现场投影的预览（质量门看的就是它），没写进工作区
    lv.textContent = '// （预览：还没生成落盘，点「生成脚本」写入工作区）\n'
      + store.luaPreview;
    lv.classList.add('is-preview');
  } else { lv.textContent = '// 还没有脚本'; lv.classList.remove('is-preview'); }
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

/* ══════════════ 整理为标准文本（零 AI，只动文本不动 IR） ══════════════ */
async function tidyText() {
  if (!needCard()) return;
  const text = $('#text-editor').value || '';
  if (!text.trim()) { toast('卡文框是空的，没什么可整理', { kind: 'warn' }); return; }
  let r;
  try {
    r = await api.post('/api/psct/tidy', { card: store.spec.id, text, lang: currentLang }, {});
  } catch (e) { toast('整理失败：' + e.message, { kind: 'err', hint: e.hint }); return; }
  if (!r.ok) { toast(r.error || '整理失败', { kind: 'err', hint: r.hint }); return; }
  showTidy(r);
}

function showTidy(r) {
  const paras = r.paragraphs || [];
  const picked = paras.map((p) => p.out);            // 每段当前采纳哪一版
  const LB = { rewritten: '整段重写', surface: '只做表层', kept: '原样保留' };

  const preview = h('pre.code-view.small', { text: assemble() });
  function assemble() {
    const block = [], rest = [];
    paras.forEach((p, i) => (p.kind === 'summon_block' ? block : rest).push(picked[i]));
    return [...block, rest.join('\n')].filter((x) => String(x || '').trim()).join('\n');
  }
  function refresh() { preview.textContent = assemble(); }

  const rows = paras.map((p, i) => h('tr', {},
    h('td', { text: p.index ? String(p.index) : '—' }),
    h('td', { class: 'tidy-src', text: p.src }),
    h('td', { class: p.status === 'rewritten' ? 'tidy-new' : '', text: p.out }),
    h('td', {},
      h('span', { class: `chip ${p.recognized ? 'ok' : 'bad'}`, text: LB[p.status] || p.status }),
      h('div.footnote', { text: p.reason || '' }),
      (p.rules || []).length ? h('div.footnote', { text: '规则：' + (p.rules || []).join(' · ') }) : null,
      h('button.mini-btn.alt', {
        type: 'button', style: 'margin-top:4px',
        onclick: () => { picked[i] = picked[i] === p.out ? p.src : p.out; refresh(); },
      }, picked[i] === p.out ? '保留我的原文' : '用整理后的'))));

  const body = h('div', {},
    h('div.notice', {},
      h('b', { text: '内核识别：' }), `${r.recognized}/${r.total} 段认出了效果种类`,
      ` · 整段重写 ${r.rewritten} 段 · 校验 ERROR ${r.lint_before.errors} → ${r.lint_after.errors}`, h('br'),
      h('b', { text: '只改文本：' }), '效果列表、脚本、卡面都不动 —— 这一步不碰 IR。', h('br'),
      h('b', { text: '一键替换：' }),
      h('span', { class: r.safe_to_apply ? 'chip ok' : 'chip warn',
                  text: r.safe_to_apply ? '可以（每段都识别 + 数值卡名保真 + 校验不劣化）' : '不建议（见下方原因）' })),
    (r.blockers || []).length ? h('div.notice.bad', {},
      h('b', { text: '为什么不给一键替换：' }),
      h('ul', {}, (r.blockers || []).map((b) => h('li', { text: b })))) : null,
    h('h4', { text: '逐段对照' }),
    h('table.grid.tidy-diff', {},
      h('thead', {}, h('tr', {}, ['段', '你的原文', '整理后', '状态与原因'].map((x) => h('th', { text: x })))),
      h('tbody', {}, rows)),
    (r.surface_edits || []).length ? h('details', { open: true },
      h('summary', { text: `表层归一 ${r.surface_edits.length} 处` }),
      h('ul', {}, (r.surface_edits || []).map((e) =>
        h('li', { text: `${e.from} → ${e.to}：${e.why}（${e.code}）` })))) : null,
    (r.terms || []).length ? h('details', {},
      h('summary', { text: `术语建议 ${r.terms.length} 条（只报不改：这些词会出现在卡名里，自动替换会连名字一起改掉）` }),
      h('ul', {}, (r.terms || []).map((t) =>
        h('li', { text: `「${t.bad}」→「${t.good}」${t.level === 'INFO' ? '（旧卡原文也这么写，仅建议）' : ''}：${t.why}` })))) : null,
    (r.notes || []).map((n) => h('p.footnote', { text: n })),
    h('h4', { text: '采纳后的文本' }), preview);

  modal({
    title: `整理为标准文本 · ${r.lang_label}（零 AI 规则整理）`,
    body,
    actions: [
      { label: '采纳全部', class: 'mini-btn primary', keepOpen: true, onClick: () => {
          if (!r.safe_to_apply) {
            toast('还有段落内核认不出来，只能逐段采纳', { kind: 'warn',
              hint: (r.blockers || [])[0] || '' }); return;
          }
          $('#text-editor').value = assemble();
          $('#text-editor').dispatchEvent(new Event('input', { bubbles: true }));
          toast('整理结果已填入卡文框（还没保存，点「写回规格」才落盘）', { kind: 'ok' });
        } },
      { label: '只采纳我勾的这段', class: 'mini-btn alt', keepOpen: true, onClick: () => {
          $('#text-editor').value = assemble();
          $('#text-editor').dispatchEvent(new Event('input', { bubbles: true }));
          toast('已按上表的取舍填入卡文框（未保存）', { kind: 'ok',
            hint: '表里点「保留我的原文 / 用整理后的」可以逐段切换' });
        } },
      { label: '把整理结果同步进 IR', class: 'mini-btn danger', keepOpen: true,
        onClick: () => syncTidyToIR(assemble()) },
    ],
  });
  ariaJob('pass', '卡文整理',
    `整理完成：${r.recognized}/${r.total} 段被内核识别，${r.rewritten} 段整段重写，` +
    `校验 ERROR ${r.lint_before.errors} → ${r.lint_after.errors}。`);
}

/** 显式的第二步：把整理好的文本反解成效果列表（会动 IR，所以单独确认）。 */
async function syncTidyToIR(text) {
  let r;
  try {
    r = await api.post('/api/psct/infer', { card: store.spec.id, text, lang: currentLang }, {});
  } catch (e) { toast('反解失败：' + e.message, { kind: 'err', hint: e.hint }); return; }
  const effs = r.effects || [];
  const blank = effs.filter((x) => !x.kind).length;
  modal({
    title: '把这段文本反解成效果列表',
    body: h('div', {},
      h('div.notice.warn', {},
        h('b', { text: '这一步会动 IR：' }),
        `效果列表会被替换成反解出的 ${effs.length} 条（其中 ${blank} 条内核认不出种类，需要你在规格页补）。`,
        h('br'), '脚本与卡面会随之变化。不确定就先取消，只保留整理好的文本。'),
      h('table.grid', {}, h('thead', {}, h('tr', {},
        ['#', '种类', '时点', '限制', '原文'].map((x) => h('th', { text: x })))),
        h('tbody', {}, effs.map((x, i) => h('tr', {},
          h('td', { text: String(i + 1) }),
          h('td', { class: x.kind ? '' : 'warn-text', text: x.kind || '（认不出）' }),
          h('td', { text: x.trigger || '' }), h('td', { text: x.limit || '' }),
          h('td', { text: String(x.raw_text || '').slice(0, 44) }))))),
      h('p.footnote', { text: r.hint || '' })),
    actions: [{
      label: '确认替换效果列表', class: 'mini-btn danger', keepOpen: true,
      onClick: async () => {
        const spec = JSON.parse(JSON.stringify(store.spec));
        spec.effects = effs.map((x) => { delete (x.params || {})._index; return x; });
        spec.text_i18n = Object.assign({}, spec.text_i18n, { [currentLang]: text });
        try {
          await api.put(`/api/cards/${spec.id}`, spec);
          store.spec = spec; store.markSaved(); store.set('card', spec);
          $('#text-editor').value = text;
          toast('效果列表与卡文已同步', { kind: 'ok', hint: '记得跑一次「校验」和 G2' });
          window.dispatchEvent(new CustomEvent('cardforge:saved'));
        } catch (e) { toast('同步失败：' + e.message, { kind: 'err', hint: e.hint }); }
      },
    }],
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
  store.luaPreview = '';   // 已经有真脚本了，预览标记该清掉
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
