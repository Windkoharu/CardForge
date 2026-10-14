/* ══════════════════════════════════════════════════════════════════
   阶段 1 · 规格
   ──────────────────────────────────────────────────────────────────
   表单是 CardSpec 的直接映射。卡种不同 → 显示不同字段（15 种框的
   差异由后端 FRAMES 定义驱动，前端不硬编码卡种清单）。
   ══════════════════════════════════════════════════════════════════ */

import { api, store, zhMeta } from './state.js';
import { $, $$, clear, h, field, select, textInput, textarea, checkboxGroup,
  toast, modal, pretty, optionLabel } from './ui.js';

const ZONES = [['', '（不限）'], ['DECK', '卡组'], ['HAND', '手卡'], ['GRAVE', '墓地'],
  ['REMOVED', '除外区'], ['FIELD', '场上'], ['EXTRA', '额外卡组'],
  ['MZONE', '怪兽区'], ['SZONE', '魔陷区']];
const FILTERS = [['any', '任意'], ['archetype', '本家字段'], ['race', '种族'],
  ['attribute', '属性'], ['type', '卡种'], ['level', '等级'], ['name', '卡名']];
const COSTS = [['none', '无代价'], ['release', '解放'], ['discard', '丢弃手卡'],
  ['send_grave', '送去墓地'], ['pay_lp', '支付 LP'], ['banish', '除外'],
  ['tribute_self', '解放这张卡'], ['detach', '去除超量素材']];
const MARKERS = [['左上', '↖'], ['上', '↑'], ['右上', '↗'], ['左', '←'],
  ['右', '→'], ['左下', '↙'], ['下', '↓'], ['右下', '↘']];

let previewTimer = null;

export function initSpec() {
  store.on('meta', () => { if (store.spec) renderForm(); });
  store.on('card', (spec) => { renderForm(); schedulePreview(60); });
  store.on('spec:patch', () => schedulePreview());
  // 系列名单变了（通常是刚在系列面板里建了一个）→ 重绘表单，
  // 让「所属系列」那行的提示从「还没有系列」当场变成「已有系列圣经」。
  window.addEventListener('cardforge:archetypes-changed', () => {
    if (store.spec) renderForm();
  });
  $('#btn-save').addEventListener('click', save);
  $('#btn-preview-now').addEventListener('click', () => schedulePreview(0));
  $('#btn-add-effect').addEventListener('click', addEffect);
  $('#btn-infer-effect').addEventListener('click', inferFromText);
}

/* ══════════════ 表单渲染 ══════════════ */
function renderForm() {
  const spec = store.spec;
  if (!spec) {
    ['f-basic', 'f-monster', 'f-spell', 'f-belong', 'f-effects'].forEach((id) => clear($('#' + id)));
    $('#f-markers') && clear($('#f-markers'));
    $('#eff-count') && ($('#eff-count').textContent = '0');
    $('#b-monster').hidden = true; $('#b-spell').hidden = true;
    return;
  }
  const meta = store.meta || {};
  // 后端 /api/meta 的 frames 是 {key: 对象}；选项必须显式取中文名，
  // 不能把对象直接交给 option（会渲染成 [object Object]，缺陷 #32）。
  const frames = Object.entries(meta.frames || {})
    .map(([k, v]) => [k, optionLabel(v, k)]);
  const isMon = !['spell', 'trap'].includes(spec.frame);
  const isPend = String(spec.frame).includes('pendulum');
  const isLink = spec.frame === 'link';

  /* ── 基本信息 ── */
  clear($('#f-basic'));
  $('#f-basic').append(
    field('卡号', h('input', { value: spec.id, readonly: true,
      title: '卡号由内核分配，需 ≥ 210000000 才会避开官方池' })),
    field('卡名', textInput(spec.name, { onChange: (v) => patch({ name: v }) }),
      { req: true, hint: '中文名；其他语言在下方对照' }),
    field('日文名', textInput((spec.name_i18n || {}).ja || '',
      { onChange: (v) => patchI18n('ja', v) })),
    field('英文名', textInput((spec.name_i18n || {}).en || '',
      { onChange: (v) => patchI18n('en', v) })),
    field('卡种', select(frames, spec.frame, { onChange: (v) => patch({ frame: v }, true) }),
      { hint: '决定卡框、版式与 type 位掩码' }),
  );

  /* ── 怪兽数值 ── */
  $('#b-monster').hidden = !isMon;
  clear($('#f-monster'));
  if (isMon) {
    clear($('#f-monster'));
    $('#f-monster').append(
      field('属性', selFrom(meta.attributes || spec.attribute, spec.attribute,
        (v) => patch({ attribute: v }))),
      field('种族', selFrom(meta.races || spec.race, spec.race, (v) => patch({ race: v }))),
      field(isLink ? '连接值（自动）' : (spec.frame === 'xyz' ? '阶级' : '等级'),
        h('input', { value: isLink ? (spec.level || '') : (spec.level ?? ''),
          type: 'number', min: 0, max: 13, readonly: isLink,
          oninput: (e) => patch({ level: parseInt(e.target.value || '0', 10) }) }),
        { hint: isLink ? '连接值由箭头数量推导，只读' : '' }),
      field('攻击力', textInput(String(spec.atk ?? ''), {
        onChange: (v) => patch({ atk: /^[-+]?\d+$/.test(v.trim()) ? parseInt(v, 10) : v.trim() || '?' })
      }), { hint: '未知填 ?' }),
      field(isLink ? '（连接怪兽无守备力）' : '守备力', textInput(String(spec.dfd ?? ''), {
        onChange: (v) => patch({ dfd: /^[-+]?\d+$/.test(v.trim()) ? parseInt(v, 10) : v.trim() || '?' })
      }), { hint: isLink ? '连接怪兽不存守备力' : '未知填 ?' }),
    );
    if (isPend) {
      $('#f-monster').append(field('灵摆刻度（左）', h('input', {
        type: 'number', min: 1, max: 13, value: spec.pendulum_scale ?? '',
        oninput: (e) => patch({ pendulum_scale: parseInt(e.target.value || '0', 10) || null })
      })));
      $('#f-monster').append(field('灵摆刻度（右）', h('input', {
        type: 'number', min: 1, max: 13, value: '',
        oninput: (e) => patch({ pendulum_scale_right: parseInt(e.target.value || '0', 10) || null })
      })));
    }
    if (spec.frame !== 'token') {
      $('#f-monster').append(field('特殊标签', checkboxGroup(
        Object.entries(meta.monster_tags || {}).map(([k, v]) => [k, v.zh_cn || k]),
        spec.tags || [], { onChange: (v) => patch({ tags: v }) }), { full: true }));
    }
  }

  /* ── 连接箭头 ── */
  const mbox = $('#f-markers');
  clear(mbox);
  if (isLink) {
    const picked = new Set(spec.link_markers || []);
    for (const [val, glyph] of MARKERS) {
      const cb = document.createElement('input');
      cb.type = 'checkbox'; cb.checked = picked.has(val);
      cb.addEventListener('change', () => {
        const cur = new Set((store.spec.link_markers || []));
        cb.checked ? cur.add(val) : cur.delete(val);
        patch({ link_markers: MARKERS.map(([v]) => v).filter((v) => cur.has(v)),
          level: [...cur].length });
        cb.closest('.mk').classList.toggle('on', cb.checked);
      });
      mbox.appendChild(h('div.mk' + (picked.has(val) ? '.on' : ''), {}, cb));
      mbox.appendChild(h('div.cap', { text: glyph }));
    }
    mbox.appendChild(h('div.hint.full', { text: '箭头方向 = 相互连接区的位置，与连接值同源' }));
  }

  /* ── 魔法 / 陷阱 ── */
  const isST = ['spell', 'trap'].includes(spec.frame);
  $('#b-spell').hidden = !isST;
  clear($('#f-spell'));
  if (isST) {
    const kinds = spec.frame === 'spell' ? meta.spell_kinds : meta.trap_kinds;
    $('#f-spell').append(
      field(spec.frame === 'spell' ? '魔法卡类型' : '陷阱卡类型',
        select(Object.entries(kinds || {}).map(([k, v]) => [k, v.zh_cn || k]),
          spec.frame === 'spell' ? spec.spell_kind : spec.trap_kind,
          { onChange: (v) => patch(spec.frame === 'spell' ? { spell_kind: v } : { trap_kind: v }) }),
        { hint: '速攻魔法与反击陷阱会改变可发动时点' }),
    );
  }

  /* ── 归属 ── */
  clear($('#f-belong'));
  const archNames = new Set(((store.state && store.state.archetypes) || [])
    .map((a) => a.name).filter(Boolean));
  const archHint = h('span.hint');
  const archInput = h('input', {
    list: 'arch-list', value: spec.archetype || '',
    placeholder: '如 星奏',
    oninput: (e) => { patch({ archetype: e.target.value }); syncArchHint(e.target.value); },
  });
  // 「系列」这一栏是用户最容易踩坑的地方：卡上写了名字、圣经却没建，
  // 界面在此之前**一声不吭**，直到点 G4 才报「没有可审计的系列」。
  // 这里当场把结论说出来，并给一条直达的补救动作。
  function syncArchHint(v) {
    const name = String(v || '').trim();
    clear(archHint);
    if (!name) {
      archHint.appendChild(document.createTextNode(
        '留空 = 不归入任何系列（G4 会跳过这张卡）'));
      archHint.dataset.state = 'idle';
      return;
    }
    if (archNames.has(name)) {
      archHint.appendChild(document.createTextNode(`已有系列圣经「${name}」，G4 可审计`));
      archHint.dataset.state = 'ok';
      return;
    }
    archHint.dataset.state = 'warn';
    archHint.appendChild(document.createTextNode(`还没有系列「${name}」的圣经 —— `));
    archHint.appendChild(h('button.link-btn', {
      type: 'button',
      onclick: () => window.dispatchEvent(new CustomEvent('cardforge:new-archetype',
        { detail: { name } })),
    }, '现在创建'));
  }
  $('#f-belong').append(
    field('所属系列', archInput, { hint: '' }),
    h('div.field', {}, h('span.k', { text: ' ' }), archHint),
    field('字段码 setcode', textInput(spec.setcode || '0x0', {
      onChange: (v) => patch({ setcode: v })
    }), { hint: '十六进制；0x0 = 无字段' }),
    h('div.field', {}, h('span.k', { text: ' ' }),
      h('button.mini-btn.alt', { onclick: suggestSetcode, type: 'button' }, '建议一个未用码')),
    field('风味文本', textarea(spec.flavor || '', {
      rows: 3, onChange: (v) => patch({ flavor: v })
    }), { full: true, hint: '通常怪兽/魔陷没有效果文本时，这段会进文本框' }),
  );
  syncArchHint(spec.archetype || '');
  const archBox = h('datalist', { id: 'arch-list' });
  for (const a of (store.state && store.state.archetypes) || []) archBox.appendChild(h('option', { value: a.name }));
  $('#f-belong').appendChild(archBox);

  renderEffects();
  notice();
}

/** 属性/种族的候选：后端给的是数组（已是中文名），直接当选项用。 */
function selFrom(list, value, onChange) {
  const arr = Array.isArray(list) ? list : Object.keys(list || {});
  return select(arr.map((x) => [x, x]), value, { onChange });
}

function patch(obj, rerender = false) {
  store.patch(obj);
  if (rerender) renderForm();
  markDirty();
}
function patchI18n(lang, v) {
  const cur = Object.assign({}, store.spec.name_i18n || {});
  cur[lang] = v;
  store.patch({ name_i18n: cur });
  markDirty();
}
function markDirty() {
  const btn = $('#btn-save');
  if (btn) btn.classList.toggle('is-dirty', store.isDirty());
}

/* ══════════════ 效果编辑 ══════════════ */
function renderEffects() {
  const spec = store.spec; if (!spec) return;
  const box = clear($('#f-effects'));
  const kinds = (store.meta && store.meta.effect_kinds) || [];
  const meta = new Map(kinds.map((k) => [k.key, k]));
  const triggers = Object.entries((store.meta && store.meta.triggers) || {});
  const limits = Object.entries((store.meta && store.meta.effect_limits) || {});  spec.effects = spec.effects || [];
  $('#eff-count').textContent = String(spec.effects.length);

  spec.effects.forEach((eff, i) => {
    const km = meta.get(eff.kind) || {};
    box.appendChild(effectRow(eff, i, km, kinds, triggers, limits));
  });

  if (!spec.effects.length) {
    box.appendChild(h('div.notice', {},
      h('b', { text: '还没有效果。' }),
      ' 点上方「+ 添加效果」逐条结构化，或在「卡文 · 脚本」页写好后用「从卡文推断」。',
      h('br'),
      '两种做法最后都会落到同一份效果定义上，卡文与脚本都由它投影出来 —— 所以不会出现「文本说一套、脚本做一套」。'));
  }
}

function effectRow(eff, i, km, kinds, triggers, limits) {
  eff.params = eff.params || {};
  eff.target = eff.target || {};
  eff.cost = eff.cost || {};
  const spec = store.spec;
  const isPend = String(spec.frame).includes('pendulum');
  const pendIdx = spec.pendulum_effect_indices || [];
  const num = '①②③④⑤⑥⑦⑧⑨⑩'[i] || String(i + 1);

  const row = h('div.effect', {},
    h('div.effect-head', {},
      h('span.effect-no', { text: num }),
      h('span.effect-title', { text: km.zh || eff.kind || '未选种类' }),
      isPend ? h('label.chips', {},
        h('input', { type: 'checkbox', checked: pendIdx.includes(i),
          onchange: (e) => {
            const cur = new Set((store.spec.pendulum_effect_indices || []));
            e.target.checked ? cur.add(i) : cur.delete(i);
            store.patch({ pendulum_effect_indices: [...cur].sort() });
            markDirty();
          } }),
        h('span', { text: '进灵摆框' })) : null,
      h('button.mini-btn.del', { type: 'button', onclick: () => delEffect(i) }, '删除')),

    h('div.form-grid', {},
      field('效果种类', select([['', '（请选择）'], ...kinds.map((k) => [k.key, k.zh || k.key])],
        eff.kind || '', { onChange: (v) => setEff(i, { kind: v }) }), { req: true }),
      field('发动时点', select(triggers, eff.trigger || 'IGNITION',
        { onChange: (v) => setEff(i, { trigger: v }) })),
      field('次数限制', select(limits, eff.limit || 'once_per_turn',
        { onChange: (v) => setEff(i, { limit: v }) }),
        { hint: '「1回合1次」与「这个卡名的①②效果1回合各能使用1次」语义不同，不可互换' }),
      ...paramFields(i, eff, km)),

    h('div.effect-sub', {},
      h('h5', { text: '对象' }),
      field('从哪去', select(ZONES, eff.target.from_zone || '',
        { onChange: (v) => setEffTarget(i, { from_zone: v }) })),
      field('到哪去', select(ZONES, eff.target.to_zone || '',
        { onChange: (v) => setEffTarget(i, { to_zone: v }) })),
      field('筛选', select(FILTERS, eff.target.filter_kind || 'any',
        { onChange: (v) => setEffTarget(i, { filter_kind: v }) })),
      field('筛选值', textInput(String(eff.target.filter_value ?? ''), {
        onChange: (v) => setEffTarget(i, { filter_value: v })
      }), { hint: '种族填「龙族」，等级填「4」，字段留空则用所属系列' }),
      field('数量', h('input', { type: 'number', min: 0, value: eff.target.count ?? 1,
        oninput: (e) => setEffTarget(i, { count: parseInt(e.target.value || '0', 10) }) })),
      field('属于谁', select([['self', '自己'], ['opponent', '对方'], ['both', '双方']],
        eff.target.controller || 'self', { onChange: (v) => setEffTarget(i, { controller: v }) })),

      h('h5', { text: '代价' }),
      field('代价类型', select(COSTS, eff.cost.kind || 'none',
        { onChange: (v) => setEffCost(i, { kind: v }) }),
        { hint: km.cost_allowed === false ? '该种类官方不接受代价' : '' }),
      field('代价数量', h('input', { type: 'number', min: 0, value: eff.cost.count ?? 1,
        oninput: (e) => setEffCost(i, { count: parseInt(e.target.value || '0', 10) }) })),
      field('原文（可选）', textInput(eff.raw_text || '', {
        onChange: (v) => setEff(i, { raw_text: v })
      }), { hint: '留档你的原话，校验器会拿它对照' })));

  return row;
}

/** 种类声明过的参数 → 逐个生成输入框；再给一个高级 JSON 口子。 */
function paramFields(i, eff, km) {
  const out = [];
  const params = km.params || {};
  const known = Object.keys(params);
  if (known.length) {
    for (const key of known.slice(0, 4)) {
      const d = params[key] || {};
      const zh = d.zh || key;
      if (d.choices && d.choices.length) {
        out.push(field(zh, select(d.choices.map((c) => [String(c), String(c)]),
          String(eff.params[key] ?? d.default ?? ''),
          { onChange: (v) => setEffParam(i, key, v) }), { req: !!d.required }));
      } else if (d.type === 'int' || d.type === 'number') {
        out.push(field(zh, h('input', { type: 'number',
          value: eff.params[key] ?? d.default ?? '',
          oninput: (e) => setEffParam(i, key, parseInt(e.target.value || '0', 10)) }),
          { req: !!d.required }));
      } else {
        out.push(field(zh, textInput(String(eff.params[key] ?? d.default ?? ''), {
          onChange: (v) => setEffParam(i, key, v) }), { req: !!d.required }));
      }
    }
  } else {
    out.push(field('数量 n', h('input', { type: 'number', value: eff.params.n ?? '',
      oninput: (e) => setEffParam(i, 'n', parseInt(e.target.value || '0', 10)) })));
  }
  out.push(field('更多参数', h('button.mini-btn.alt', {
    type: 'button',
    onclick: () => editParams(i)
  }, `编辑 JSON（${Object.keys(eff.params).length} 项）`), { hint: '给高级玩法：直接改参数表' }));
  return out;
}

function editParams(i) {
  const eff = store.spec.effects[i];
  const ta = textarea(pretty(eff.params || {}), { rows: 12, mono: true });
  modal({
    title: `效果 ${'①②③④⑤⑥⑦⑧⑨⑩'[i] || i + 1} · 参数表`,
    body: h('div', {}, ta,
      h('p.footnote', { text: '键名要对应效果种类的参数定义；写错的键会原样带进卡文占位符，' +
        '卡文里出现 {xxx} 就说明这个键没被认出来。' })),
    actions: [{ label: '应用', class: 'mini-btn primary', onClick: () => {
      try {
        eff.params = JSON.parse(ta.value || '{}');
        store.emit('card', store.spec); markDirty();
      } catch (e) { toast('JSON 不合法：' + e.message, { kind: 'err' }); }
    } }, { label: '取消', class: 'mini-btn' }]
  });
}

function setEff(i, obj) {
  const eff = store.spec.effects[i];
  Object.assign(eff, obj);
  store.patch({ effects: [...store.spec.effects] });
  if ('kind' in obj) renderEffects();
  markDirty();
}
function setEffTarget(i, obj) {
  const eff = store.spec.effects[i];
  eff.target = Object.assign({}, eff.target || {}, obj);
  store.patch({ effects: [...store.spec.effects] }); markDirty();
}
function setEffCost(i, obj) {
  const eff = store.spec.effects[i];
  eff.cost = Object.assign({}, eff.cost || {}, obj);
  store.patch({ effects: [...store.spec.effects] }); markDirty();
}
function setEffParam(i, key, val) {
  const eff = store.spec.effects[i];
  eff.params = Object.assign({}, eff.params || {}, { [key]: val });
  store.patch({ effects: [...store.spec.effects] }); markDirty();
}
function addEffect() {
  if (!store.spec) { toast('先选中或新建一张卡', { kind: 'warn' }); return; }
  const effs = (store.spec.effects || []).concat([{
    kind: '', trigger: 'IGNITION', limit: 'once_per_turn',
    target: { filter_kind: 'any', count: 1, controller: 'self' },
    cost: { kind: 'none' }, params: {}, source: 'manual'
  }]);
  store.patch({ effects: effs });
  renderEffects(); markDirty();
}
function delEffect(i) {
  const effs = (store.spec.effects || []).slice();
  effs.splice(i, 1);
  store.patch({ effects: effs });
  renderEffects(); markDirty();
}

async function suggestSetcode() {
  const r = await api.get('/api/pool/setcode').catch((e) => ({ ok: false, error: e.message, hint: e.hint }));
  if (!r.ok) { toast(r.error || '取不到建议', { kind: 'err', hint: r.hint }); return; }
  const v = r.value && (r.value.suggested || r.value);
  patch({ setcode: typeof v === 'string' ? v : pretty(v) });
  toast('已填入建议字段码 ' + (typeof v === 'string' ? v : ''), { kind: 'ok' });
}

async function inferFromText() {
  const spec = store.spec;
  if (!spec) { toast('先选中一张卡', { kind: 'warn' }); return; }
  const text = spec.text_i18n && (spec.text_i18n.zh_cn || Object.values(spec.text_i18n)[0]);
  if (!text) { toast('这张卡还没有卡文可以推断', { kind: 'warn',
    hint: '先在「卡文 · 脚本」页写好卡文，或填入 text_i18n.zh_cn' }); return; }
  const r = await api.post('/api/psct/infer', { card: spec.id }).catch((e) => ({ ok: false, error: e.message, hint: e.hint }));
  if (!r.ok) { toast('推断失败：' + (r.error || ''), { kind: 'err', hint: r.hint }); return; }
  const effs = r.effects || [];
  if (!effs.length) { toast('没能从卡文里认出效果', { kind: 'warn', hint: r.hint || '可以在效果区手工添加' }); return; }
  store.patch({ effects: effs });
  store.emit('card', store.spec);
  toast(`认出 ${effs.length} 条效果，请逐条核对`, { kind: 'ok',
    hint: '推断只认关键词与句式，认不出「取对象／不取对象」这类细节' });
}

/* ══════════════ 保存与预览 ══════════════ */
export async function save() {
  const spec = store.spec;
  if (!spec) return null;
  const body = strip(spec);
  try {
    const r = store.cardExists
      ? await api.put(`/api/cards/${spec.id}`, body)
      : await api.post('/api/cards', body);
    store.spec = r.spec || body;
    store.cardExists = true;
    store.cardId = store.spec.id;
    store.markSaved();
    store.set('card', store.spec);
    toast('已保存', { kind: 'ok', ms: 2200 });
    window.dispatchEvent(new CustomEvent('cardforge:saved', { detail: r }));
    return r;
  } catch (e) {
    toast('保存失败：' + e.message, { kind: 'err', hint: e.hint });
    throw e;
  }
}

/** 去掉后端冗余写入的派生字段，避免前端把算出来的值当输入回传。 */
function strip(spec) {
  const s = JSON.parse(JSON.stringify(spec));
  ['race_bits', 'attr_bits', 'type_bits', 'link_bits', 'def_value', 'schema_version']
    .forEach((k) => delete s[k]);
  return s;
}

function schedulePreview(ms = 700) {
  clearTimeout(previewTimer);
  if (!store.spec) return;
  previewTimer = setTimeout(previewNow, ms);
}

export async function previewNow() {
  const spec = store.spec;
  const img = $('#preview-img');
  if (!spec || !img) return;
  const tag = $('#preview-tag');
  try {
    const blob = await api.blob('/api/render/preview',
      { spec: strip(spec), width: 420, ...renderQuery() });
    img.src = URL.createObjectURL(blob);
    img.alt = `卡面预览 · ${spec.display_name || spec.name}`;
    const vector = blob.type.includes('svg');
    tag.textContent = vector
      ? '矢量预览（近似，非最终出图）'
      : '卡面预览 · 所见即导出结果';
    tag.className = 'preview-tag' + (vector ? ' vector' : '');
  } catch (e) {
    tag.textContent = '预览失败：' + e.message;
    tag.className = 'preview-tag vector';
  }
}

/** 界面上的即时渲染参数（只影响预览，不落盘）。 */
let renderOverride = {};
export function setRenderOverride(obj) { renderOverride = Object.assign({}, obj); schedulePreview(0); }
export function getRenderOverride() { return renderOverride; }
function renderQuery() { return renderOverride; }

function notice() {
  const box = $('#spec-notice');
  if (!box || !store.spec) return;
  const spec = store.spec;
  const bits = spec.type_bits;
  clear(box);
  box.appendChild(h('div', {},
    h('b', { text: '引擎会看到：' }),
    h('br'),
    `type 0x${(bits ?? 0).toString(16).toUpperCase()} · 等级/箭头 ${spec.level ?? '-'} · `,
    `ATK ${spec.atk ?? '-'} / DEF ${spec.dfd ?? '-'} · setcode ${spec.setcode || '0x0'}`));
}
