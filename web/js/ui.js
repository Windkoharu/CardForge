/* 极小的 DOM 工具 + 提示组件。没有框架，也不需要框架。 */

/**
 * 建元素。标签名支持 `tag.cls1.cls2#id` 这种简写 —— 必须在这里拆开成
 * 真的 class / id，因为 `document.createElement('div.field')` **不会报错**，
 * 它会造出一个叫 "DIV.FIELD" 的未知元素：DOM 里查不到 .field，CSS 也不生效。
 * （这个坑会让整个界面变成没有样式的空白页，而且控制台一条错误都不报。）
 */
export function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(...splitTag(tag));
  const cls = selectClasses(tag);
  if (cls) el.className = cls;
  const id = selectId(tag);
  if (id) el.id = id;
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') el.className = (el.className ? el.className + ' ' : '') + v;
    else if (k === 'html') el.innerHTML = v;
    else if (k === 'text') el.textContent = v;
    else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
    else if (k === 'dataset') Object.assign(el.dataset, v);
    else el.setAttribute(k, v === true ? '' : String(v));
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.appendChild(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

function splitTag(tag) {
  return [String(tag).replace(/[.#][^.#]+/g, '') || 'div'];
}
function selectClasses(tag) {
  return String(tag).replace(/#.*$/, '').match(/(?<=\.)[^.#]+/g) ? [...new Set(
    String(tag).replace(/#.*$/, '').match(/(?<=\.)[^.#]+/g))].join(' ') : '';
}
function selectId(tag) {
  const m = String(tag).match(/#([^.#]+)/);
  return m ? m[1] : '';
}

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
export function clear(el) { while (el && el.firstChild) el.removeChild(el.firstChild); return el; }
export function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

export function debounce(fn, ms = 320) {
  let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

/** 带「下一步建议」的浮层提示。错误必须可复制。 */
export function toast(message, { kind = '', hint = '', ms = 6000 } = {}) {
  const box = $('#toasts');
  if (!box) return;
  const el = h(`div.toast${kind ? '.' + kind : ''}`, {},
    h('div', { text: message }),
    hint ? h('div.t-hint', { text: '→ ' + hint }) : null);
  box.appendChild(el);
  const kill = () => { el.style.opacity = '0'; setTimeout(() => el.remove(), 200); };
  el.addEventListener('click', kill);
  setTimeout(kill, ms);
}

export function modal({ title = '', body = null, actions = [] }) {
  const back = $('#modal-backdrop');
  clear($('#modal-title')).appendChild(document.createTextNode(title));
  const bodyBox = clear($('#modal-body'));
  if (body) bodyBox.appendChild(body.nodeType ? body : h('div', { html: body }));
  const foot = clear($('#modal-foot'));
  for (const a of actions) {
    foot.appendChild(h(`button.${a.class || 'mini-btn'}`,
      { onclick: () => { if (a.onClick) a.onClick(); if (!a.keepOpen) close(); } }, a.label));
  }
  if (!actions.length) foot.appendChild(h('button.mini-btn', { onclick: close }, '关闭'));
  back.hidden = false;
  function close() { back.hidden = true; }
  back.onclick = (e) => { if (e.target === back) close(); };
  document.addEventListener('keydown', function up(e) {
    if (e.key === 'Escape') { close(); document.removeEventListener('keydown', up); }
  });
  return { close, body: bodyBox };
}

/* ══════════════ 表单控件生成 ══════════════ */

export function field(label, input, { hint = '', full = false, req = false } = {}) {
  return h(`div.field${full ? '.full' : ''}`, {},
    h('span.k', {}, label, req ? h('span.req', { text: ' *' }) : null),
    input,
    hint ? h('span.hint', { text: hint }) : null);
}

/**
 * 下拉框的显示文本。**必须**兜住「直接塞对象」这一种写法：
 * `Object.entries({某表})` 得到的是 `[key, 对象]`，若原样丢给 option，
 * 浏览器会把对象串成 `[object Object]` —— 界面看起来"卡种显示不正常"，
 * 而控制台一条错误都不报（缺陷 #32）。这里统一从对象里取可读字段。
 */
export function optionLabel(v, fallback = '') {
  if (v === null || v === undefined) return fallback;
  if (typeof v === 'object') {
    return String(v.zh || v.zh_cn || v.label || v.name || v.native ||
      v.en || v.key || fallback || '');
  }
  return String(v);
}

export function select(options, value, { onChange, labels = null } = {}) {
  const el = document.createElement('select');
  for (const o of options) {
    const [v, zh] = Array.isArray(o) ? o : [o && o.key, o];
    const text = optionLabel(zh, optionLabel(v));
    el.appendChild(h('option', { value: v }, text || String(v ?? '')));
  }
  if (value !== undefined && value !== null) el.value = String(value);
  if (onChange) el.addEventListener('change', () => onChange(el.value));
  return el;
}

export function textInput(value, { onChange, type = 'text', placeholder = '', onEnter } = {}) {
  const el = document.createElement('input');
  el.type = type;
  el.value = value ?? '';
  el.placeholder = placeholder;
  if (onChange) el.addEventListener('input', () => onChange(el.value));
  if (onEnter) el.addEventListener('keydown', (e) => { if (e.key === 'Enter') onEnter(el.value); });
  return el;
}

export function textarea(value, { onChange, rows = 3, placeholder = '', mono = false } = {}) {
  const el = document.createElement('textarea');
  el.rows = rows; el.value = value ?? ''; el.placeholder = placeholder; el.spellcheck = false;
  if (mono) el.style.fontFamily = 'var(--font-code)';
  if (onChange) el.addEventListener('input', () => onChange(el.value));
  return el;
}

export function checkboxGroup(options, picked, { onChange } = {}) {
  const set = new Set(picked || []);
  const box = h('div.chips');
  for (const [val, zh] of options) {
    const cb = document.createElement('input');
    cb.type = 'checkbox'; cb.checked = set.has(val); cb.value = val;
    cb.addEventListener('change', () => {
      cb.checked ? set.add(val) : set.delete(val);
      if (onChange) onChange([...set]);
    });
    box.appendChild(h('label', {}, cb, h('span', { text: zh || val })));
  }
  return box;
}

/** 问题列表 → 可读卡片。带「放行」按钮（放行要写理由）。 */
export function renderIssues(box, issues, { onWaive, emptyText = '没有发现问题' } = {}) {
  clear(box);
  const list = (issues || []).filter(Boolean);
  if (!list.length) {
    box.appendChild(h('div.clean', { text: '✓ ' + emptyText }));
    return;
  }
  const order = { ERROR: 0, WARN: 1, INFO: 2 };
  list.sort((a, b) => (order[a.level] ?? 3) - (order[b.level] ?? 3));
  for (const it of list) {
    const row = h('div.issue' + (it.waived ? '.waived' : ''), {},
      h(`span.lv.${it.level || 'INFO'}`, { text: it.level || 'INFO' }),
      h('span.code', { text: it.code || '' }),
      h('span.msg', {}, it.message || '',
        it.hint ? h('div.hint', { text: '→ ' + it.hint }) : null,
        it.waived && it.waiver_reason ? h('div.hint', { text: `已放行：${it.waiver_reason}` }) : null),
      (it.waived || !onWaive) ? null
        : h('button.mini-btn.waive', {
          onclick: () => onWaive(it),
          title: '强制放行这一条（会留痕，写进审计报告）'
        }, '放行'));
    box.appendChild(row);
  }
}

export function pretty(v) {
  try { return JSON.stringify(v, null, 2); } catch { return String(v); }
}
