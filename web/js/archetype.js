/* ══════════════════════════════════════════════════════════════════
   系列圣经 —— G4 的审计对象。
   ──────────────────────────────────────────────────────────────────
   为什么必须有这块界面
   --------------------
   卡上有 ``archetype`` 字段，系列圣经却是**独立的一份文件**
   （``workspace/archetypes/<名>/archetype.json``）。只给卡写系列名、
   不建圣经，G4 会诚实地拒绝跑：

       这张卡没有可审计的系列「星奏」— 先创建系列并把它归入系列

   这是**正确防护而不是 bug** —— G4 审的是「一个系列作为整体成不成立」
   （有没有初动、够不够展开点、终端强不强），不是单张卡。没有圣经就
   没有审计对象，此时报「通过」才叫谎报。

   但旧版前端**完全没有创建系列的入口**，用户只能敲命令行。这个模块
   把那条路径搬进界面：建系列 → 看卡表 → 跑 G4 → 看还缺什么。
   ══════════════════════════════════════════════════════════════════ */

import { api, store } from './state.js';
import {
  $, clear, h, toast, modal, field, textInput, select, pretty,
} from './ui.js';

/** 制胜手段 —— 与内核 ``Archetype.win_method`` 取值一一对应。 */
const WIN_METHODS = [
  ['BATTLE', '战斗（靠怪兽平推）'],
  ['EFFECT', '效果（靠效果压制／烧血）'],
  ['BURN', '削血（靠伤害获胜）'],
  ['MIX', '混合'],
];

/** 王牌召唤法 —— 对应 ``Archetype.trumps``。 */
const TRUMPS = [
  ['MAIN', '主卡组'],
  ['FUSION', '融合'],
  ['SYNCHRO', '同步'],
  ['XYZ', '超量'],
  ['LINK', '连接'],
  ['RITUAL', '仪式'],
];

/** 强度定位 —— 对应 ``Archetype.target_power``。 */
const POWERS = [
  ['casual', '休闲'],
  ['rogue', '准一线'],
  ['competitive', '竞技'],
];

const STATUS_ZH = {
  pass: '通过', warn: '警告', fail: '拦截', waived: '已放行',
  skipped: '未运行', pending: '未检查', error: '出错',
};

let inited = false;

/** 内核里当前有哪些系列（名字集合）。规格页的实时校验要用它。 */
let known = new Set();

export function initArchetype() {
  if (inited) return;
  inited = true;
  const btn = $('#btn-archetypes');
  if (btn) btn.addEventListener('click', openPanel);
  // 规格页「所属系列」填了不存在的名字时，那里的「现在创建」按钮会把名字带过来
  window.addEventListener('cardforge:new-archetype', (e) => {
    newArchetypeDialog(null, (e.detail && e.detail.name) || '');
  });
  // 卡存盘（含改系列名）后，系列的卡数会变，刷新一次列表脚注
  window.addEventListener('cardforge:saved', () => { refreshFoot(); });
  refreshKnown();
}

/** 把系列名单同步到 ``store.state.archetypes``（规格页的 datalist 与校验共用）。 */
async function refreshKnown() {
  try {
    const r = await api.get('/api/archetypes');
    const items = r.archetypes || [];
    known = new Set(items.map((a) => a.name).filter(Boolean));
    if (store.state) {
      store.state.archetypes = items;
      const c = store.state.counts || (store.state.counts = {});
      c.archetypes = items.length;
    }
    return items;
  } catch { return []; }
}

/* ══════════════ 面板 ══════════════ */

async function openPanel() {
  const body = h('div.arch-panel', {},
    h('p.footnote', { text: '系列圣经是 G4 的审计对象。卡上写了系列名还不够 —— ' +
      '这里建的那份文件，才是 G4 真正看的东西。' }));
  const listBox = h('div.arch-list', {}, h('p.footnote', { text: '读系列列表…' }));
  body.appendChild(listBox);

  const m = modal({
    title: '系列圣经',
    body,
    actions: [{
      label: '+ 新建系列', class: 'mini-btn primary', keepOpen: true,
      onClick: () => newArchetypeDialog(() => loadList(listBox)),
    }],
  });
  loadList(listBox);
}

async function loadList(box) {
  clear(box);
  let items = [];
  try {
    const r = await api.get('/api/archetypes');
    items = r.archetypes || [];
  } catch (e) {
    box.appendChild(h('div.notice.bad', {},
      h('b', { text: '系列列表读不出来：' }), e.message,
      h('div.hint', { text: '→ ' + (e.hint || '') })));
    return;
  }
  if (!items.length) {
    box.appendChild(h('div.notice.warn', {},
      h('b', { text: '还没有任何系列。' }),
      ' 卡上填了系列名但这里为空时，G4 会报「没有可审计的系列」—— ',
      '点右下角「+ 新建系列」建一份即可。'));
    return;
  }
  for (const it of items) box.appendChild(archRow(it, box));
}

function archRow(it, listBox) {
  const name = it.name || '';
  const row = h('div.arch-row', {},
    h('div.arch-main', {},
      h('b', { text: name }),
      h('span.arch-meta', { text: `setcode=${it.setcode || '?'} · 卡数 ${it.n_cards || 0}` +
        (it.target_power ? ` · ${powerLabel(it.target_power)}` : '') })),
    h('div.arch-acts', {},
      h('button.mini-btn', { text: 'G4 审计',
        onclick: () => audit(name, row) }),
      h('button.mini-btn', { text: '看卡表',
        onclick: () => showDetail(name) })));
  const out = h('div.arch-out');
  row.appendChild(out);
  return row;
}

/* ══════════════ 新建 ══════════════ */

function newArchetypeDialog(onDone, presetName = '') {
  const draft = {
    name: '', setcode: '', concept: '',
    win_method: 'BATTLE', trumps: ['MAIN'], target_power: 'casual',
  };
  // 当前卡上已经写了系列名的话，默认带过来 —— 这正是用户卡住的场景。
  // 规格页的「现在创建」会显式传 presetName，优先级更高。
  const cur = presetName || (store.spec && store.spec.archetype) || '';
  if (cur) draft.name = cur;

  const nameIn = textInput(draft.name, {
    placeholder: '系列名，也是本家字段名，如「星奏」',
    onChange: (v) => { draft.name = v; },
  });
  const setIn = textInput(draft.setcode, {
    placeholder: '留空自动分配，如 0x1000',
    onChange: (v) => { draft.setcode = v; },
  });
  const conIn = textInput(draft.concept, {
    placeholder: '一句话概念（会影响卡表建议）',
    onChange: (v) => { draft.concept = v; },
  });
  const winSel = select(WIN_METHODS.map(([k, v]) => [k, v]), draft.win_method,
    { onChange: (v) => { draft.win_method = v; } });
  const trumpSel = select(TRUMPS.map(([k, v]) => [k, v]), 'MAIN',
    { onChange: (v) => { draft.trumps = [v]; } });
  const powSel = select(POWERS.map(([k, v]) => [k, v]), draft.target_power,
    { onChange: (v) => { draft.target_power = v; } });

  const body = h('div', {},
    h('p.footnote', { text: '建好之后，卡上的「系列」字段填这个名字，G4 才有对象可审。' }),
    field('系列名', nameIn, { req: true, hint: '就是本家字段，卡文里「「星奏」卡」引用的那个名字' }),
    field('setcode', setIn, { hint: '留空由内核分配一个未占用的段' }),
    field('概念', conIn, { hint: '一句话说明这个系列怎么赢、打什么手感' }),
    field('制胜手段', winSel),
    field('王牌召唤法', trumpSel),
    field('强度定位', powSel));

  const m = modal({
    title: '新建系列圣经',
    body,
    actions: [
      { label: '创建', class: 'mini-btn primary', keepOpen: true,
        onClick: async () => {
          const name = (draft.name || '').trim();
          if (!name) { toast('系列名不能为空', { kind: 'warn' }); return; }
          const payload = {
            name,
            concept: draft.concept || '',
            win_method: draft.win_method,
            trumps: draft.trumps,
            target_power: draft.target_power,
          };
          if (draft.setcode && draft.setcode.trim()) payload.setcode = draft.setcode.trim();
          try {
            const r = await api.post('/api/archetypes', payload);
            toast(`已建立系列「${name}」`, {
              kind: 'ok',
              hint: r.path ? '圣经：' + r.path : '',
            });
            m.close();
            // 名单变了：同步给规格页（datalist 与「所属系列」的实时校验都要用），
            // 再让规格页重绘一次 —— 刚才那句「还没有系列」现在应该变成绿字。
            await refreshKnown();
            window.dispatchEvent(new CustomEvent('cardforge:archetypes-changed',
              { detail: { name } }));
            onDone && onDone();
            refreshFoot();
          } catch (e) {
            toast('建系列失败：' + e.message, { kind: 'err', hint: e.hint });
          }
        } },
      { label: '取消', class: 'mini-btn', onClick: () => m.close() },
    ],
  });
}

/* ══════════════ 审计 ══════════════ */

async function audit(name, row) {
  const out = row.querySelector('.arch-out') || row;
  clear(out).appendChild(h('p.footnote', { text: `正在审计「${name}」…` }));
  try {
    const r = await api.post(`/api/archetypes/${encodeURIComponent(name)}/audit`, {});
    renderAudit(out, name, r);
  } catch (e) {
    clear(out).appendChild(h('div.notice.bad', {},
      h('b', { text: 'G4 跑不起来：' }), e.message,
      h('div.hint', { text: '→ ' + (e.hint || '') })));
  }
}

function renderAudit(box, name, r) {
  clear(box);
  const rep = r.report || {};
  const s = rep.status || 'pending';
  const tone = s === 'pass' ? 'ok' : (s === 'fail' || s === 'error') ? 'bad' : 'warn';

  const issues = rep.issues || [];
  const errors = issues.filter((i) => i.level === 'ERROR');
  const warns = issues.filter((i) => i.level !== 'ERROR');

  box.appendChild(h(`div.notice.${tone}`, {},
    h('b', { text: `G4 系列一致性：${STATUS_ZH[s] || s}` }),
    h('br'), rep.summary || '',
    h('div.hint', { text: `系列「${name}」现有 ${r.n_cards ?? '?'} 张卡` }),
    rep.degraded ? h('div', {}, h('b', { text: '降级说明：' }), rep.degraded) : null));

  if (s === 'skipped') {
    box.appendChild(h('div.notice.warn', {},
      h('b', { text: '这一门没有真的运行。' }),
      ' 「未运行」不等于「通过」——别把它当绿灯。'));
  }

  if (issues.length) {
    const ul = h('ul.arch-issues');
    for (const it of issues) {
      ul.appendChild(h(`li.${it.level === 'ERROR' ? 'is-err' : 'is-warn'}`, {},
        h('b', { text: it.code || '' }), ' ',
        h('span', { text: it.message || '' }),
        it.hint ? h('div.hint', { text: '→ ' + it.hint }) : null));
    }
    box.appendChild(ul);
  } else if (s === 'pass') {
    box.appendChild(h('p.footnote', { text: '这一门没发现问题。' }));
  }

  if (errors.length) {
    box.appendChild(h('p.footnote', { text:
      'ERROR 是卡表还没填满，不是圣经本身写错了 —— 点「看卡表」能看到每个位置缺几张。' }));
  }
  return { errors, warns };
}

/* ══════════════ 详情 ══════════════ */

async function showDetail(name) {
  const body = h('div', {}, h('p.footnote', { text: '读系列详情…' }));
  const m = modal({
    title: `系列 · ${name}`,
    body,
    actions: [
      { label: 'G4 审计', class: 'mini-btn', keepOpen: true,
        onClick: async () => {
          const out = h('div');
          clear(body).appendChild(out);
          try {
            const r = await api.post(`/api/archetypes/${encodeURIComponent(name)}/audit`, {});
            renderAudit(out, name, r);
          } catch (e) {
            clear(out).appendChild(h('div.notice.bad', { text: e.message }));
          }
        } },
      { label: '原始 JSON', class: 'mini-btn alt', keepOpen: true,
        onClick: () => {
          const out = h('div');
          clear(body).appendChild(out);
          renderRaw(out, name);
        } },
      { label: '关闭', class: 'mini-btn', onClick: () => m.close() },
    ],
  });

  try {
    const r = await api.get(`/api/archetypes/${encodeURIComponent(name)}`, { plan: 1 });
    renderDetail(body, r);
  } catch (e) {
    clear(body).appendChild(h('div.notice.bad', {},
      h('b', { text: '读不到系列：' }), e.message,
      h('div.hint', { text: '→ ' + (e.hint || '') })));
  }
}

function renderDetail(box, r) {
  clear(box);
  const arch = r.archetype || {};
  box.appendChild(h('div.notice', {},
    h('b', { text: arch.name || '' }), h('br'),
    arch.concept || '（没写概念）',
    h('div.hint', { text: `setcode=${arch.setcode || '?'} · ` +
      `${powerLabel(arch.target_power)} · ${(arch.trumps || []).join('/') || '?'} · ` +
      `制胜 ${(arch.win_method || '?')}` })));

  // 卡表：每个位置要几张、现有几张。
  // 完成度的**权威来源是 roster[i].done**（内核存在这里的卡 id 列表），
  // 不是从卡身上反推 —— `summary()` 根本不返回 roles。
  const roster = arch.roster || [];
  if (roster.length) {
    const ul = h('ul.arch-roster');
    for (const s of roster) {
      const got = (s.done || []).length;
      const need = s.count || 0;
      ul.appendChild(h(`li.${got >= need ? 'is-full' : 'is-gap'}`, {},
        h('b', { text: `${roleLabel(s.role)} ${got}/${need}` }),
        h('span', { text: s.brief || '' })));
    }
    box.appendChild(h('h4', { text: '卡表（每个位置要几张）' }));
    box.appendChild(ul);
  }

  if ((r.cards || []).length) {
    box.appendChild(h('h4', { text: `系列内的卡（${r.cards.length}）` }));
    const ul = h('ul.arch-cards');
    for (const c of r.cards) {
      ul.appendChild(h('li', {}, h('b', { text: c.name || '（无名）' }),
        h('span', { text: ` ${c.id} · ${c.frame_label || c.frame}` })));
    }
    box.appendChild(ul);
  } else {
    box.appendChild(h('div.notice.warn', {},
      h('b', { text: '这个系列下还没有卡。' }),
      ' 把卡的「系列」字段填成这个名字并保存，它就会归入这里。'));
  }
}

async function renderRaw(box, name) {
  clear(box).appendChild(h('p.footnote', { text: '读取…' }));
  try {
    const r = await api.get(`/api/archetypes/${encodeURIComponent(name)}`);
    clear(box).appendChild(h('pre.code-view', { text: pretty(r.archetype || r) }));
  } catch (e) {
    clear(box).appendChild(h('div.notice.bad', { text: e.message }));
  }
}

/* ══════════════ 小工具 ══════════════ */

const ROLE_ZH = {
  starter: '初动点', extender: '展开点', trump: '王牌终端',
  support: '支援', recovery: '回收',
};
function roleLabel(r) { return ROLE_ZH[r] || r || '?'; }

const POWER_ZH = { casual: '休闲', rogue: '准一线', competitive: '竞技' };
function powerLabel(p) { return POWER_ZH[p] || p || ''; }

/** 侧栏脚注里的「系列 N」跟着圣经数量走（复用 refreshKnown，不重复发请求）。 */
async function refreshFoot() {
  const box = $('#rail-foot');
  if (!box) return;
  const items = await refreshKnown();
  const c = (store.state && store.state.counts) || {};
  const line = box.children[0];
  if (line) {
    line.textContent = `卡 ${c.cards || 0} · 系列 ${items.length || 0} · 卡组 ${c.decks || 0}`;
  }
}
