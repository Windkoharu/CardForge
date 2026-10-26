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
    ['f-basic', 'f-monster', 'f-spell', 'f-belong', 'f-effects', 'f-summon']
      .forEach((id) => clear($('#' + id)));
    $('#f-markers') && clear($('#f-markers'));
    $('#eff-count') && ($('#eff-count').textContent = '0');
    $('#b-monster').hidden = true; $('#b-spell').hidden = true;
    $('#b-summon') && ($('#b-summon').hidden = true);
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
    field('卡种', select(frames, spec.frame, { onChange: (v) => {
      patch({ frame: v });
      maybeResetSummonForFrame(v);
      renderForm();
    } }), { hint: '决定卡框、版式与 type 位掩码' }),
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

  renderSummon();
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

/* ══════════════ 召唤条件（额外卡组 / 仪式）══════════════ */
const SUMMON_WORD = {
  fusion: '融合召唤', synchro: '同步召唤', xyz: '超量召唤',
  link: '连接召唤', ritual: '仪式召唤',
};

function copyPart(m) {
  const p = Object.assign({}, m || {});
  p.also = Array.isArray(m && m.also) ? m.also.map((c) => Object.assign({}, c)) : [];
  return p;
}

function copyMethod(m) {
  const o = Object.assign({}, m || {});
  o.parts = Array.isArray(m && m.parts) ? m.parts.map(copyPart) : [];
  o.use_materials = m && m.use_materials === false ? false : true;
  return o;
}

function summonOf(spec) {
  const cur = (spec && spec.summon) || {};
  return {
    materials: Array.isArray(cur.materials) ? cur.materials.map(copyPart) : [],
    methods: Array.isArray(cur.methods) ? cur.methods.map(copyMethod) : [],
    limit: cur.limit || '',
    cannot_normal_summon: !!cur.cannot_normal_summon,
    cannot_be_material: Array.isArray(cur.cannot_be_material)
      ? [...cur.cannot_be_material] : [],
    ritual_spell: cur.ritual_spell || '',
    ritual_spell_code: cur.ritual_spell_code || 0,
    ritual_spell_archetype: !!cur.ritual_spell_archetype,
    text_i18n: cur.text_i18n || {},
  };
}

function patchSummon(obj, rerender = false) {
  if (!store.spec) return;
  const next = Object.assign(summonOf(store.spec), obj);
  store.patch({ summon: next });
  markDirty();
  schedulePreview();
  if (rerender) renderSummon();
  scheduleSummonPreview();
}

function frameInfo() {
  const spec = store.spec;
  return ((store.meta || {}).frames || {})[spec && spec.frame] || {};
}

function summonApplies() {
  const fd = frameInfo();
  return !!fd.is_monster && (!!fd.extra_deck || fd.base === 'ritual');
}

function defaultPart(base, index, spec) {
  const arch = String(spec.archetype || '').trim();
  const p = { kind: arch ? 'archetype' : 'any', count: 1, count_max: 0 };
  if (arch) p.value = arch;
  if (base === 'synchro') p.tuner = index === 0 ? 'tuner' : 'non_tuner';
  if (base === 'link') {
    p.kind = arch ? 'archetype' : 'any';
    p.count = Math.max(1, Math.min(2, Number(spec.level) || 2));
    p.count_max = 99;
  }
  if (base === 'xyz') p.count = 2;
  if (base === 'fusion' && arch) p.count = 2;
  return p;
}

function summonShapeMatches(base, mats) {
  if (!mats.length) return true;
  if (base === 'synchro') return mats.length === 2;
  if (base === 'xyz' || base === 'link') return mats.length === 1;
  return true;
}

function askReplaceSummon(title, onYes) {
  modal({
    title,
    body: h('p', { text: '换成模板会覆盖当前素材段（卡名/字段/数量/角色）。取消则保留原数据，之后可以手动改。' }),
    actions: [
      { label: '保留原素材' },
      { label: '换成新模板', class: 'mini-btn alt', onClick: onYes },
    ],
  });
}

function maybeResetSummonForFrame(frame) {
  const fd = ((store.meta || {}).frames || {})[frame] || {};
  if (!fd.is_monster || !(fd.extra_deck || fd.base === 'ritual')) return;
  const s = summonOf(store.spec);
  if (!s.materials.length) { ensureSummonTemplate(false); return; }
  if (summonShapeMatches(fd.base, s.materials)) return;
  askReplaceSummon(`${fd.zh_cn || '新卡种'}的素材段不匹配`, () => {
    ensureSummonTemplate(true);
    renderSummon();
  });
}

function ensureSummonTemplate(force = false) {
  const spec = store.spec;
  if (!spec || !summonApplies()) return;
  const fd = frameInfo();
  const s = summonOf(spec);
  if (!force && (s.materials.length || s.ritual_spell)) return;
  const base = fd.base;
  let mats = [];
  if (base === 'synchro') {
    mats = [defaultPart(base, 0, spec), defaultPart(base, 1, spec)];
  } else if (base === 'fusion') {
    mats = String(spec.archetype || '').trim()
      ? [defaultPart(base, 0, spec)]
      : [defaultPart(base, 0, spec), defaultPart(base, 1, spec)];
  } else if (base === 'xyz' || base === 'link') {
    mats = [defaultPart(base, 0, spec)];
  }
  patchSummon({ materials: mats }, false);
}

function setPart(i, obj, rerender = false) {
  const s = summonOf(store.spec);
  s.materials[i] = Object.assign({}, s.materials[i] || {}, obj);
  patchSummon({ materials: s.materials }, rerender);
}

function removePart(i) {
  const s = summonOf(store.spec);
  s.materials.splice(i, 1);
  patchSummon({ materials: s.materials }, true);
}

function addPart() {
  const spec = store.spec;
  const fd = frameInfo();
  const base = fd.base;
  const s = summonOf(spec);
  const max = base === 'synchro' ? 2 : (base === 'xyz' || base === 'link' ? 1 : 5);
  if (s.materials.length >= max) return;
  const idx = s.materials.length;
  const p = defaultPart(base, idx, spec);
  p.kind = 'any';
  delete p.value;
  p.count = 1; p.count_max = 0;
  if (base === 'synchro') p.tuner = idx === 0 ? 'tuner' : 'non_tuner';
  s.materials.push(p);
  patchSummon({ materials: s.materials }, true);
}

function materialKinds() {
  const table = ((store.meta || {}).summon || {}).material_kinds || {};
  return Object.entries(table);
}

function materialTypes() {
  const table = ((store.meta || {}).summon || {}).material_types || {};
  return Object.entries(table);
}

function materialRoles() {
  const table = ((store.meta || {}).summon || {}).material_roles || {};
  return Object.entries(table);
}

function materialLocks() {
  const table = ((store.meta || {}).summon || {}).material_locks || {};
  return Object.entries(table);
}

function summonLimits(base) {
  const table = ((store.meta || {}).summon || {}).limits || {};
  const word = SUMMON_WORD[base] || '本卡种召唤';
  const labels = {
    '': '按规则召唤',
    must_be: `只能用${word}特殊召唤`,
    must_be_with_materials: `只能用以上素材的${word}`,
    cannot_spsummon: '不能特殊召唤',
  };
  return Object.keys(table).map((k) => [k, labels[k] || table[k] || k]);
}

function renderSummon() {
  const spec = store.spec;
  const block = $('#b-summon');
  const box = $('#f-summon');
  if (!block || !box) return;
  clear(box);
  if (!spec || !summonApplies()) { block.hidden = true; return; }
  block.hidden = false;
  const fd = frameInfo();
  const base = fd.base;
  const isSyn = base === 'synchro';
  const isLink = base === 'link';
  const isXyz = base === 'xyz';
  const isRitual = base === 'ritual';
  const s = summonOf(spec);
  const maxParts = isSyn ? 2 : (isXyz || isLink ? 1 : 5);
  const canRemove = s.materials.length > 1;

  box.appendChild(h('div.summon-tools', {},
    h('button.mini-btn.alt', { type: 'button', onclick: () => {
      const cur = summonOf(spec);
      if (cur.materials.length || cur.ritual_spell) {
        askReplaceSummon('覆盖当前召唤条件？', () => {
          ensureSummonTemplate(true);
          renderSummon();
        });
        return;
      }
      ensureSummonTemplate(true);
      renderSummon();
    } }, '按卡种填入模板'),
    h('span.hint', { text: isSyn
      ? '同调素材 = 协调段 + 协调以外段；数量可以写成「协调2只」'
      : isXyz
        ? '超量素材只有一段筛选条件；数量对应的就是阶级'
        : isLink
          ? '连接值是箭头数量；素材上限不会超过连接值'
          : isRitual
            ? '仪式怪兽需要有仪式魔法卡名，卡文第一行才会写成「「XX」降临」'
            : '融合素材每一段都用「＋」连接；同一段的数量写成 ×N' })));

  if (isRitual) {
    if (s.materials.length) {
      box.appendChild(h('div.notice', {},
        h('b', { text: '仪式怪兽不使用素材段。' }),
        ' 旧版遗留的素材数据会被忽略；仪式魔法卡名与召唤限制仍然生效。',
        h('button.mini-btn.del', { type: 'button',
          onclick: () => patchSummon({ materials: [] }, true),
        }, '清空素材数据')));
    }
  } else {
    if (!s.materials.length) {
      box.appendChild(h('div.notice', {},
        h('b', { text: '还没有素材条件。' }),
        '额外卡组的卡文第一行与 Lua 召唤流程都由这里生成；点「按卡种填入模板」可以快速开始。'));
    }
    s.materials.forEach((part, i) => box.appendChild(materialRow(part, i, {
      base, isSyn, isLink, canRemove,
    })));
    if (s.materials.length < maxParts) {
      box.appendChild(h('div.summon-tools', {},
        h('button.mini-btn', { type: 'button', onclick: addPart },
          '+ 添加素材段')));
    }
  }

  if (isRitual) {
    const grid = h('div.form-grid.summon-extra');
    grid.appendChild(field('仪式魔法卡名', textInput(s.ritual_spell, {
      onChange: (v) => patchSummon({ ritual_spell: v }),
    }), { hint: '例：星奏的仪式 → 卡文「「星奏的仪式」降临」' }));
    grid.appendChild(field('当作字段使用', h('div.chips', {},
      h('label', {},
        h('input', { type: 'checkbox', checked: s.ritual_spell_archetype,
          onchange: (e) => patchSummon({ ritual_spell_archetype: e.target.checked }) }),
        h('span', { text: '「XX」仪式魔法卡（字段）' }))),
      { hint: '勾选后卡文写成「「XX」仪式魔法卡降临」' }));
    box.appendChild(grid);
  }

  const grid2 = h('div.form-grid.summon-extra');
  grid2.appendChild(field('召唤限制', select(summonLimits(base), s.limit, {
    onChange: (v) => patchSummon({ limit: v }),
  }), { hint: '对应卡文的「不用X召唤不能特殊召唤」与 Lua 的 SPSUMMON_CONDITION' }));

  const lockBox = h('div.chips');
  for (const [k, label] of materialLocks()) {
    const cb = h('input', { type: 'checkbox',
      checked: s.cannot_be_material.includes(k),
      onchange: (e) => {
        const cur = new Set(summonOf(store.spec).cannot_be_material);
        e.target.checked ? cur.add(k) : cur.delete(k);
        patchSummon({ cannot_be_material: [...cur] });
      } });
    lockBox.appendChild(h('label', {}, cb, h('span', { text: `不能作为${label}` })));
  }
  grid2.appendChild(field('素材锁定', lockBox, {
    full: true, hint: '写入 EFFECT_CANNOT_BE_*_MATERIAL；与卡文「这张卡不能作为…素材」一一对应',
  }));
  box.appendChild(grid2);

  // ── 额外召唤方法（官方的「以及以下方法」+ ● 条目）──
  if (!isRitual) {
    const mHead = h('div.summon-tools', {},
      h('span.k', { text: '额外召唤方法（接触召唤那类「以下方法」）' }));
    box.appendChild(mHead);
    (s.methods || []).forEach((m, i) => box.appendChild(methodRow(m, i, base)));
    if ((s.methods || []).length < 3) {
      box.appendChild(h('div.summon-tools', {},
        h('button.mini-btn', { type: 'button', onclick: addMethod },
          '+ 添加召唤方法'),
        h('span.hint', { text: s.methods.length
          ? '召唤限制选「只能用本卡种的召唤方式特殊召唤」时，'
            + '卡文会自动写成「…以及以下方法才能特殊召唤」并列出 ● 条目'
          : '不填就是普通额外召唤；填了才需要把召唤限制选成「只能用本卡种的召唤方式特殊召唤」' })));
    }
  }

  const pre = h('pre.summon-preview', { text: '生成中…' });
  box.appendChild(h('div.field.full', {},
    h('span.k', { text: '召唤条件预览（简体中文）' }), pre,
    h('span.hint', { text: '这只是召唤条件段；完整卡文点「卡文 · 脚本」页的「生成」。' })));
  scheduleSummonPreview(pre);
}

function materialRow(part, i, opt) {
  const spec = store.spec;
  const meta = store.meta || {};
  const kind = String(part.kind || 'any');
  const set = (obj, rerender = false) => setPart(i, obj, rerender);
  const row = h('div.effect.summon-row', {});
  const title = opt.isSyn
    ? (part.tuner === 'tuner' ? '协调段' : part.tuner === 'non_tuner' ? '协调以外段' : '同调素材')
    : `第 ${i + 1} 段素材`;
  row.appendChild(h('div.effect-head', {},
    h('span.effect-no', { text: `素材 ${i + 1}` }),
    h('span.effect-title', { text: title }),
    opt.canRemove ? h('button.mini-btn.del', {
      type: 'button', onclick: () => removePart(i),
    }, '删除') : null));

  const grid = h('div.effect-sub');
  grid.appendChild(field('素材种类', select(materialKinds(), kind, {
    onChange: (v) => {
      const clean = Object.assign({}, part, {
        kind: v, value: null, code: 0, setcode: '',
      });
      if (v === 'race') clean.value = '龙族';
      if (v === 'attribute') clean.value = '暗';
      if (v === 'type') clean.value = 'effect';
      if (v === 'level' || v === 'rank') clean.value = 4;
      set(clean, true);
    },
  })));

  if (kind === 'name') {
    const hint = h('span.hint', { text: part.code
      ? `卡号 ${part.code}` : '未解析卡号（G1 会拦；点右侧解析）' });
    const input = h('input', {
      value: part.value || '', placeholder: '完整的官方卡名',
      oninput: (e) => {
        // 卡名改了就作废旧卡号，避免 Lua 继续按上一张卡过滤
        set({ value: e.target.value, code: 0 });
        hint.textContent = '卡号已失效，请重新解析';
      },
    });
    const btn = h('button.mini-btn', {
      type: 'button', onclick: () => resolveMaterialName(i, input.value, hint),
    }, '解析卡号');
    grid.appendChild(field('卡名', input, { full: true }));
    grid.appendChild(h('div.field', {}, h('span.k', { text: '卡号' }),
      h('div.inline-tools', {}, btn, hint)));
  } else if (kind === 'archetype') {
    const input = h('input', {
      value: part.value || '', placeholder: '字段名，如 星奏',
      oninput: (e) => set({ value: e.target.value, setcode: '' }),
    });
    const sc = h('input', {
      value: part.setcode || '', placeholder: '留空 = 本卡字段码',
      oninput: (e) => set({ setcode: e.target.value }),
    });
    grid.appendChild(field('字段名', input));
    grid.appendChild(field('字段码 setcode', sc, {
      hint: part.value && part.value === spec.archetype
        ? '本家字段：留空会自动用本卡 setcode' : '其他字段必须填字段码，Lua 才有过滤器',
    }));
  } else if (kind === 'race') {
    const v = Array.isArray(part.value) ? part.value[0] : part.value;
    grid.appendChild(field('种族', selFrom(meta.races || [], v || '龙族',
      (x) => set({ value: x }, true))));
  } else if (kind === 'attribute') {
    const v = Array.isArray(part.value) ? part.value[0] : part.value;
    grid.appendChild(field('属性', selFrom(meta.attributes || [], v || '暗',
      (x) => set({ value: x }, true))));
  } else if (kind === 'type') {
    grid.appendChild(field('卡种', select(materialTypes(), part.value || 'effect',
      { onChange: (x) => set({ value: x }, true) })));
  } else if (kind === 'level' || kind === 'rank') {
    grid.appendChild(field(kind === 'level' ? '等级' : '阶级', h('input', {
      type: 'number', min: 1, max: 13, value: part.value ?? 4,
      oninput: (e) => set({ value: parseInt(e.target.value || '0', 10) }),
    })));
  }

  grid.appendChild(field('数量', h('input', {
    type: 'number', min: 1, max: 99, value: part.count || 1,
    oninput: (e) => set({ count: parseInt(e.target.value || '1', 10) }),
  })));
  grid.appendChild(field('以上', h('div.chips', {}, h('label', {},
    h('input', { type: 'checkbox', checked: Number(part.count_max || 0) > Number(part.count || 1),
      onchange: (e) => set({ count_max: e.target.checked ? 99 : 0 }, true) }),
    h('span', { text: 'N 只以上' }))), { hint: '连接/超量的上限会按连接值/无限素材处理' }));

  if (opt.isSyn) {
    grid.appendChild(field('同调角色', select(materialRoles(), part.tuner || '', {
      onChange: (x) => set({ tuner: x }, true),
    }), { hint: '每张同调怪兽必须有 1 段协调 + 1 段协调以外' }));
  }

  const flags = h('div.chips');
  flags.appendChild(h('label', {}, h('input', {
    type: 'checkbox', checked: !!part.exclude_token,
    onchange: (e) => set({ exclude_token: e.target.checked }, true),
  }), h('span', { text: '衍生物以外' })));
  if (opt.isLink) {
    flags.appendChild(h('label', {}, h('input', {
      type: 'checkbox', checked: !!part.include_link,
      onchange: (e) => set({ include_link: e.target.checked }, true),
    }), h('span', { text: '包含连接怪兽' })));
    flags.appendChild(h('label', {}, h('input', {
      type: 'checkbox', checked: !!part.exclude_link,
      onchange: (e) => set({ exclude_link: e.target.checked }, true),
    }), h('span', { text: '连接怪兽以外' })));
  }
  grid.appendChild(field('附加筛选', flags, { full: true }));

  row.appendChild(grid);
  // 附加条件（官方素材一段里可以叠多个筛选：字段＋种族、种族＋等级…）
  // 放在本段自己的控件后面，读起来才是「这一段素材 = 主条件 + 附加条件」。
  row.appendChild(alsoBlock(part, i, set));
  return row;
}

function alsoValue(cond, onSet) {
  /** 单个附加条件的取值控件（种族 / 属性 / 卡种 / 等级 / 阶级 / 字段 / 卡名）。 */
  const meta = store.meta || {};
  const kind = String(cond.kind || 'race');
  const wrap = h('div.inline-tools');
  if (kind === 'race') {
    const v = Array.isArray(cond.value) ? cond.value[0] : cond.value;
    wrap.appendChild(selFrom(meta.races || [], v || '龙族', onSet));
  } else if (kind === 'attribute') {
    const v = Array.isArray(cond.value) ? cond.value[0] : cond.value;
    wrap.appendChild(selFrom(meta.attributes || [], v || '暗', onSet));
  } else if (kind === 'type') {
    wrap.appendChild(select(materialTypes(), cond.value || 'effect',
      { onChange: onSet }));
  } else if (kind === 'level' || kind === 'rank') {
    wrap.appendChild(h('input', {
      type: 'number', min: 1, max: 13, value: cond.value ?? 4,
      style: 'width:5.5em',
      oninput: (e) => onSet(parseInt(e.target.value || '0', 10)),
    }));
  } else if (kind === 'archetype' || kind === 'name') {
    wrap.appendChild(h('input', {
      value: cond.value || '', placeholder: kind === 'name' ? '完整卡名' : '字段名',
      oninput: (e) => onSet(e.target.value),
    }));
    if (kind === 'archetype') {
      wrap.appendChild(h('input', {
        value: cond.setcode || '', placeholder: '字段码 0x…', style: 'width:8em',
        oninput: (e) => setAlsoRaw(cond, { setcode: e.target.value }),
      }));
    } else {
      wrap.appendChild(h('input', {
        value: cond.code || '', placeholder: '卡号', style: 'width:7.5em',
        oninput: (e) => setAlsoRaw(cond, { code: parseInt(e.target.value || '0', 10) }),
      }));
    }
  }
  return wrap;
}

function setAlsoRaw(cond, obj) {
  // 附加条件对象是 copy 出来的，写回要靠 index（调用方已绑好 commit）
  Object.assign(cond, obj);
}

function alsoBlock(part, i, set) {
  const kinds = materialKinds().filter(([k]) => k !== 'any');
  const list = Array.isArray(part.also) ? part.also : [];
  const box = h('div.field.full.also-box', {},
    h('span.k', { text: '附加条件（同一段素材里同时成立）' }));
  const hint = h('span.hint', {
    text: '官方把「字段＋种族」写在同一段里：包含「六武众」怪兽的战士族怪兽2只。'
      + '拆成两段会变成 2＋2 只素材，脚本就要 4 张卡。',
  });
  box.appendChild(hint);
  const rows = h('div.also-rows');
  list.forEach((cond, ci) => {
    const commit = (obj) => {
      const next = list.map((c) => Object.assign({}, c));
      next[ci] = Object.assign({}, cond, obj);
      set({ also: next }, true);
    };
    const row = h('div.also-row');
    row.appendChild(select(kinds, String(cond.kind || 'race'), {
      onChange: (v) => {
        const clean = { kind: v, value: v === 'race' ? '龙族'
          : v === 'attribute' ? '暗' : v === 'type' ? 'effect'
            : (v === 'level' || v === 'rank') ? 4 : '' };
        commit(clean);
      },
    }));
    row.appendChild(alsoValue(cond, (val) => {
      const keep = { setcode: cond.setcode || '', code: cond.code || 0 };
      commit(Object.assign({ value: val }, keep));
    }));
    row.appendChild(h('button.mini-btn.del', {
      type: 'button', onclick: () => {
        const next = list.map((c) => Object.assign({}, c));
        next.splice(ci, 1);
        set({ also: next }, true);
      },
    }, '删'));
    rows.appendChild(row);
  });
  box.appendChild(rows);
  box.appendChild(h('button.mini-btn', {
    type: 'button', onclick: () => {
      const next = list.map((c) => Object.assign({}, c));
      next.push({ kind: 'race', value: '龙族' });
      set({ also: next }, true);
    },
  }, '+ 附加条件'));
  return box;
}

function methodActions() {
  const table = ((store.meta || {}).summon || {}).method_actions || {};
  return Object.entries(table);
}

function methodZones() {
  const table = ((store.meta || {}).summon || {}).method_zones || {};
  return Object.entries(table);
}

function setMethod(i, obj, rerender = false) {
  const s = summonOf(store.spec);
  s.methods[i] = Object.assign({}, s.methods[i] || {}, obj);
  patchSummon({ methods: s.methods }, rerender);
}

function addMethod() {
  const s = summonOf(store.spec);
  if (s.methods.length >= 3) return;
  s.methods.push({ action: 'banish', zone: 'mz', use_materials: true });
  patchSummon({ methods: s.methods }, true);
}

function removeMethod(i) {
  const s = summonOf(store.spec);
  s.methods.splice(i, 1);
  patchSummon({ methods: s.methods }, true);
}

function methodRow(m, i, base) {
  const isFusion = base === 'fusion';
  const set = (obj, rerender = false) => setMethod(i, obj, rerender);
  const row = h('div.effect.summon-row', {});
  row.appendChild(h('div.effect-head', {},
    h('span.effect-no', { text: `方法 ${i + 1}` }),
    h('span.effect-title', { text: '额外特殊召唤方法（●）' }),
    h('button.mini-btn.del', { type: 'button', onclick: () => removeMethod(i) }, '删除')));
  const grid = h('div.effect-sub');
  grid.appendChild(field('素材所在区域', select(methodZones(), m.zone || 'mz', {
    onChange: (v) => set({ zone: v }),
  }), { hint: '对应卡文「把自己场上的…」「从自己墓地把…」' }));
  grid.appendChild(field('怎么处理素材', select(methodActions(), m.action || 'banish', {
    onChange: (v) => set({ action: v }, true),
  }), { hint: 'Lua：Duel.Remove / SendtoGrave / Release / SendtoDeck / SendtoHand' }));
  grid.appendChild(field('用哪些卡', h('div.chips', {}, h('label', {},
    h('input', { type: 'checkbox', checked: m.use_materials !== false,
      onchange: (e) => set({ use_materials: e.target.checked }, true) }),
    h('span', { text: '素材行里记的卡（卡文写「上记的卡」）' }))),
    { full: true, hint: m.use_materials !== false
      ? '接触召唤的候选组就是素材行的条件，由官方召唤流程校验'
      : '不勾选时在下面自己写这套方法的素材条件' }));
  if (m.use_materials === false) {
    const parts = Array.isArray(m.parts) ? m.parts : [];
    parts.forEach((cond, ci) => {
      const commit = (obj) => {
        const next = parts.map((c) => Object.assign({}, c));
        next[ci] = Object.assign({}, cond, obj);
        set({ parts: next }, true);
      };
      const line = h('div.also-row');
      line.appendChild(select(materialKinds().filter(([k]) => k !== 'any'),
        String(cond.kind || 'race'), {
          onChange: (v) => commit({ kind: v, value: v === 'race' ? '龙族'
            : v === 'attribute' ? '暗' : v === 'type' ? 'effect'
              : (v === 'level' || v === 'rank') ? 4 : '' }),
        }));
      line.appendChild(alsoValue(cond, (val) => commit({ value: val })));
      line.appendChild(h('button.mini-btn.del', {
        type: 'button', onclick: () => {
          const next = parts.map((c) => Object.assign({}, c));
          next.splice(ci, 1);
          set({ parts: next }, true);
        },
      }, '删'));
      grid.appendChild(h('div.field.full', {},
        h('span.k', { text: `方法素材 ${ci + 1}` }), line));
    });
    grid.appendChild(h('div.field.full', {},
      h('button.mini-btn', {
        type: 'button', onclick: () => set({
          parts: parts.concat([{ kind: 'race', value: '龙族' }]),
        }, true),
      }, '+ 方法素材条件')));
  }
  grid.appendChild(field('只处理固定张数', h('input', {
    type: 'number', min: 0, max: 99, value: m.count || 0,
    oninput: (e) => set({ count: parseInt(e.target.value || '0', 10) }),
  }), { hint: '0 = 全部（上记的卡都用上）；填数字则卡文写「把自己场上2只…除外」' }));
  grid.appendChild(field('前提条件（可选）', textInput(
    typeof m.trigger === 'string' ? m.trigger : '', {
      onChange: (v) => set({ trigger: v }),
    }), { full: true, hint: '官方例句：「雷族怪兽的效果在手卡发动的回合，…」——'
      + '结构化表达不了的前提写在这里，会接在 ● 条目最前面' }));
  if (isFusion) {
    grid.appendChild(field('不需要「融合」', h('div.chips', {}, h('label', {},
      h('input', { type: 'checkbox', checked: !!m.no_spelling,
        onchange: (e) => set({ no_spelling: e.target.checked }) }),
      h('span', { text: '卡文末尾补「（不需要「融合」）」' }))),
      { full: true, hint: '冰狱龙 三叉龙那类写法；脚本本来就不经过「融合」，'
        + '这里只影响卡面文本' }));
  }
  row.appendChild(grid);
  if (!isFusion) {
    row.appendChild(h('div.notice', {},
      h('b', { text: '卡文会生成，脚本还要人工补写。' }),
      ' 接触召唤目前只有融合卡能自动生成 Fusion.AddContactProc；'
      + '同调/超量/连接需要手写 EFFECT_SPSUMMON_PROC。G1 会把这件事列成 WARN。'));
  }
  return row;
}

async function resolveMaterialName(i, name, hintEl) {
  const q = String(name || '').trim();
  if (!q) { toast('先填卡名', { kind: 'warn' }); return; }
  const r = await api.get('/api/pool/name', { name: q })
    .catch((e) => ({ ok: false, error: e.message, hint: e.hint }));
  if (r.ok) {
    setPart(i, { value: r.name || q, code: r.id }, true);
    toast(`已解析：${r.name || q} → ${r.id}`, { kind: 'ok',
      hint: r.source === 'workspace' ? '来自本工作区' : '来自官方卡池' });
    return;
  }
  const cands = r.candidates || [];
  if (!cands.length) {
    toast(r.error || '没找到这个卡名', { kind: 'err', hint: r.hint });
    return;
  }
  const body = h('div', {},
    h('p', { text: r.error || '没有精确同名卡' }),
    h('p.footnote', { text: '官方卡池里相近的卡名：' }));
  const list = h('div.chips');
  for (const c of cands) {
    list.appendChild(h('button.mini-btn', {
      type: 'button', onclick: () => {
        setPart(i, { value: c.name, code: c.id }, true);
        m.close();
        toast(`已选：${c.name}`, { kind: 'ok' });
      },
    }, `${c.name} · ${c.id}`));
  }
  body.appendChild(list);
  const m = modal({ title: '卡名没有精确匹配', body, actions: [{ label: '关闭' }] });
}

let summonPreviewTimer = null;
function scheduleSummonPreview(pre, ms = 450) {
  clearTimeout(summonPreviewTimer);
  const target = pre || $('#f-summon .summon-preview');
  if (!target || !store.spec) return;
  summonPreviewTimer = setTimeout(async () => {
    const el = target.isConnected ? target : $('#f-summon .summon-preview');
    if (!el || !store.spec) return;
    el.textContent = '生成中…';
    try {
      const r = await api.post('/api/psct/summon', { spec: strip(store.spec), langs: ['zh_cn'] }, {});
      const m = ((r.langs || {}).zh_cn) || {};
      el.textContent = m.text || '（还没有素材或召唤限制）';
      if (m.notes && m.notes.length) el.textContent += '\n\n⚠ ' + m.notes.join('\n⚠ ');
    } catch (e) {
      el.textContent = '预览失败：' + e.message;
    }
  }, ms);
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
