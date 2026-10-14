/* ══════════════════════════════════════════════════════════════════
   阶段 4 · 上桌（导出包 → 自检 → 安装）
   ──────────────────────────────────────────────────────────────────
   这一段会写用户的 EDOPro 目录，所以真安装之前必须先预演、再二次确认。
   ══════════════════════════════════════════════════════════════════ */

import { api, store } from './state.js';
import { $, $$, clear, h, field, select, textInput, renderIssues, toast, modal, pretty } from './ui.js';

let packDir = '';

export function initPack() {
  buildScope();
  loadPackages();
  loadTargets();
  $('#btn-build').addEventListener('click', build);
  $('#btn-verify').addEventListener('click', verify);
  $('#btn-dryinstall').addEventListener('click', () => install(true));
  $('#btn-install').addEventListener('click', () => install(false));
  initMdpro3();
}

/* ══════════════════════════════════════════════════════════════════
   MDPro3 / MDPro4 —— .ypk 扩展卡包
   ══════════════════════════════════════════════════════════════════ */
function initMdpro3() {
  $('#target-bar').addEventListener('click', (e) => {
    const b = e.target.closest('.tb-btn');
    if (!b) return;
    const t = b.dataset.target;
    $$('#target-bar .tb-btn').forEach(x => x.classList.toggle('is-active', x === b));
    $$('.target-pane').forEach(x => { x.hidden = x.dataset.target !== t; });
    $('#tb-note').textContent = t === 'mdpro3'
      ? 'Unity 客户端，布局与 EDOPro 完全不同：只认 .ypk，不认 expansions/'
      : '标准 ygopro 系客户端，expansions/ 目录结构';
  });
  const sel = $('#md-scope');
  const fill = () => {
    clear(sel);
    sel.appendChild(h('option', { value: 'current' }, '当前这张卡'));
    sel.appendChild(h('option', { value: 'all' }, '工作区全部卡'));
    for (const a of ((store.state && store.state.archetypes) || []))
      sel.appendChild(h('option', { value: 'arch:' + a.name }, `系列：${a.name}`));
  };
  fill();
  buildMdForm();
  detectMd();
  $('#btn-md-build').addEventListener('click', buildMd);
  $('#btn-md-detect').addEventListener('click', detectMd);
}

let mdForm = { name: 'CardForge', author: '', deck: '' };

function buildMdForm() {
  const box = clear($('#f-md'));
  box.append(
    field('卡包名', textInput(mdForm.name, { onChange: v => { mdForm.name = v; } }),
      { hint: '决定 .ypk 文件名与包内 cdb 名' }),
    field('作者', textInput(mdForm.author, { onChange: v => { mdForm.author = v; } }),
      { hint: '写进包内 README.txt，别人拿到包能知道是谁做的' }),
    h('div.field', {}, h('span.k', { text: '卡图' }),
      h('label.chips', {},
        h('input', { type: 'checkbox', checked: true, id: 'md-pics' }),
        h('span', { text: '打包时现场渲 704×1024 整卡图' })),
      h('span.hint', { text: 'MDPro3 的 pics/ 要的是整卡图 704×1024（实测其 ' +
        'SavedCardSize 与社区卡包都是这个尺寸）；Picture/Art/ 那套 624×624 是纯插画，两条通路别混' })),
  );
}

async function detectMd() {
  const box = $('#md-client-notice');
  clear(box); box.className = 'notice';
  box.appendChild(h('span', { text: '正在探测本机 MDPro3…' }));
  try {
    const r = await api.get('/api/export/mdpro3/detect');
    clear(box);
    if (!(r.clients || []).length) {
      box.className = 'notice warn';
      box.innerHTML = `<b>没找到 MDPro3 客户端。</b><br>不影响生成 .ypk —— ` +
        `游戏里「导入导出 → 导入」手动选文件就行。探测的作用是能顺手帮你查<b>卡号撞车</b>。`;
      return;
    }
    box.className = 'notice ok';
    for (const c of r.clients) {
      box.insertAdjacentHTML('beforeend',
        `<b>找到客户端</b> <code>${c.path}</code><br>` +
        `官方卡 ${c.n_official} · 脚本 ${c.n_scripts} · 卡图 ${c.n_pics} · ` +
        `语言包 ${c.langs.length} 个 · 整卡图尺寸 ${JSON.stringify(c.saved_size)}` +
        (c.id_in_use ? `<br><span style="color:var(--fail)">注意：官方池里已有 ` +
          `${c.id_in_use} 张卡在 2.1 亿号段，导出会逐个核</span>` : '') +
        (c.warnings || []).map(w => `<br><span style="color:var(--warn)">→ ${w}</span>`).join(''));
    }
  } catch (e) {
    box.className = 'notice bad';
    box.textContent = '探测失败：' + e.message;
  }
}

function mdScope() {
  const v = $('#md-scope').value || 'current';
  if (v === 'current') return store.spec ? { card: store.spec.id } : {};
  if (v === 'all') return {};
  return { archetype: v.slice(4) };
}

async function buildMd() {
  const wantPics = $('#md-pics') ? $('#md-pics').checked : true;
  window.dispatchEvent(new CustomEvent('cardforge:job',
    { detail: { state: 'working', label: '.ypk 打包' } }));
  try {
    const r = await api.post('/api/export/mdpro3/build', {
      name: mdForm.name, author: mdForm.author, langs: ['zh_cn'],
      render_pics: wantPics, deep: true, ...mdScope()
    });
    const NL = String.fromCharCode(10);
    const lines = [
      '包：' + r.rel + '　' + (r.bytes || 0).toLocaleString() + ' 字节',
      '卡 ' + r.n_cards + ' · cdb 行 ' + r.n_cdb_rows + ' · 脚本 ' + r.n_scripts +
        ' · 卡图 ' + r.n_pics + '（现场渲 ' + r.n_rendered + '）· 演示卡组 ' + r.n_deck,
      '',
      '包内结构：',
      '  ' + r.members.cdb + '　　' + r.members.strings,
      '  script/c<卡号>.lua　pics/<卡号>.jpg　pack/<卡组>.ydk',
    ];
    if ((r.cards_without_script || []).length) {
      lines.push('', '⚠ 这些卡没脚本，进游戏只能看不能用：' + r.cards_without_script.join(', '));
    }
    const ver = r.verify || [];
    lines.push('', ver.length ? '自检 ' + ver.length + ' 条：' + ver.map(function (i) {
      return '[' + i.level + '] ' + i.code + ' ' + i.message;
    }).join(NL) : '自检：干净');
    $('#md-view').textContent = lines.join(NL);
    renderIssues($('#md-issues'), (r.issues || []).concat(ver),
      { emptyText: '包结构自检通过' });
    const note = $('#md-result-notice');
    note.className = 'notice ' + (r.ok ? 'ok' : 'bad');
    clear(note);
    note.appendChild(document.createElement('b')).textContent =
      r.ok ? '已生成，可以导入了。' : '生成了，但有错误，先修再导。';
    note.appendChild(document.createElement('br'));
    const a = h('a', { href: r.download, download: '' },
      '⬇ 下载 ' + (r.filename || String(r.rel).split("/").pop()));
    note.appendChild(a);
    note.appendChild(document.createElement('br'));
    note.appendChild(document.createTextNode(r.hint || ''));
    toast(r.ok ? 'MDPro3 卡包已生成' : '卡包有错误',
      { kind: r.ok ? 'ok' : 'err', hint: r.hint });
    window.dispatchEvent(new CustomEvent('cardforge:job', { detail: {
      state: r.ok ? 'pass' : 'alert', label: '.ypk 打包',
      facts: r.ok
        ? `包已生成：${r.n_cards} 张卡、cdb ${r.n_cdb_rows} 行、脚本 ${r.n_scripts} 个、卡图 ${r.n_pics} 张；深检见下方清单。`
        : '包生成了，但自检有 ERROR —— 先别导进游戏。' } }));
  } catch (e) {
    toast('生成失败：' + e.message, { kind: 'err', hint: e.hint });
    window.dispatchEvent(new CustomEvent('cardforge:job', { detail: {
      state: 'alert', label: '.ypk 打包', facts: '打包失败：' + e.message } }));
  }
}

function buildScope() {
  const box = clear($('#f-pack'));
  box.append(
    field('扩展包名', textInput('CardForge', { onChange: (v) => { packName = v; } }),
      { hint: '决定 cdb 文件名与 expansions/ 下的目录名' }),
    field('语言', select([['zh_cn', '简体中文'], ['ja', '日文'], ['en', '英文'],
      ['zh_tw', '繁体中文'], ['ko', '韩文']], 'zh_cn', { onChange: (v) => { packLang = v; } }),
      { hint: '基础包用所选语言；多语言会另出 <name>-xx.cdb 覆盖包' }),
    field('带上卡图', select([['1', '是（复制 pics/）'], ['0', '否']], '1',
      { onChange: (v) => { copyPics = v === '1'; } })),
  );
  const sel = $('#pack-scope');
  clear(sel);
  sel.appendChild(h('option', { value: 'current' }, '当前这张卡'));
  sel.appendChild(h('option', { value: 'all' }, '工作区全部卡'));
  const archs = (store.state && store.state.archetypes) || [];
  for (const a of archs) sel.appendChild(h('option', { value: 'arch:' + a.name }, `系列：${a.name}`));
}

let packName = 'CardForge', packLang = 'zh_cn', copyPics = true;

function scopeParams() {
  const v = $('#pack-scope').value || 'current';
  if (v === 'current') return store.spec ? { card: store.spec.id } : {};
  if (v === 'all') return {};
  return { archetype: v.slice(4) };
}

/* ══════════════ 构建 ══════════════ */
async function build() {
  try {
    const r = await api.post('/api/export/build', {
      name: packName, langs: [packLang], copy_pics: copyPics, verify: true, gate5: true,
      ...scopeParams()
    });
    packDir = r.pack_dir;
    showTree(r);
    const bad = (r.issues || []).filter((i) => i.level === 'ERROR').length;
    toast(bad ? `已导出，但自检发现 ${bad} 个错误` : '导出包已生成',
      { kind: bad ? 'warn' : 'ok', hint: r.next || '' });
    loadPackages();
    window.dispatchEvent(new CustomEvent('cardforge:pack', { detail: r }));
    window.dispatchEvent(new CustomEvent('cardforge:job', { detail: {
      state: bad ? 'alert' : 'pass', label: '导出 EDOPro 包',
      facts: bad ? `导出完成但自检有 ${bad} 个错误。` : '导出包已生成，自检没有报错。' } }));
  } catch (e) {
    toast('导出失败：' + e.message, { kind: 'err', hint: e.hint });
    window.dispatchEvent(new CustomEvent('cardforge:job', { detail: {
      state: 'alert', label: '导出 EDOPro 包', facts: '导出失败：' + e.message } }));
  }
}

function showTree(r) {
  const box = $('#pack-tree');
  const lines = [];
  lines.push('导出包 ' + (r.pack_dir || '') + ' ─────');
  const st = r.stats || {};
  lines.push(pretty(st).split('\n').slice(0, 22).join('\n'));
  if (r.g5 && r.g5.status) lines.push(`\nG5 自检：${r.g5.status}` +
    (r.g5.degraded ? `（${r.g5.degraded}）` : ''));
  const iss = r.issues || [];
  if (iss.length) {
    lines.push('\n问题：');
    for (const i of iss.slice(0, 20)) lines.push(`  [${i.level}] ${i.code} ${i.message}`);
  } else lines.push('\n自检：没有问题');
  box.textContent = lines.join('\n');
  renderIssues($('#pack-issues'), iss, { emptyText: '自检通过，包结构干净' });
}

/* ══════════════ 已有包 ══════════════ */
async function loadPackages() {
  try {
    const r = await api.get('/api/export/packages');
    if ((r.packages || []).length && !packDir) packDir = r.packages[0].path;
    const box = $('#pack-tree');
    if (!box.textContent || box.textContent.includes('还没有导出包')) {
      box.textContent = (r.packages || []).length
        ? (r.packages || []).map((p) =>
          `${p.path}\n  cdb: ${p.cdb.join(', ') || '（无）'} · 脚本 ${p.n_scripts} · 卡图 ${p.n_pics}`
          + ` · strings.conf ${p.strings_conf ? '有' : '无'}`).join('\n\n')
        : '还没有导出包';
    }
  } catch (e) { /* 列表失败不影响主流程 */ }
}

async function verify() {
  try {
    const r = await api.get('/api/export/verify', { pack_dir: packDir });
    showTree({ pack_dir: r.pack_dir, stats: r.stats || {}, issues: r.issues || [],
      g5: { status: r.ok ? 'pass' : 'fail' } });
    toast(r.summary || '自检完成', { kind: r.ok ? 'ok' : 'warn' });
  } catch (e) { toast('自检失败：' + e.message, { kind: 'err', hint: e.hint }); }
}

/* ══════════════ 安装 ══════════════ */
async function loadTargets() {
  const sel = $('#edopro-target');
  clear(sel);
  sel.appendChild(h('option', { value: '' }, '自动探测…'));
  try {
    const r = await api.get('/api/export/targets');
    for (const t of (r.targets || [])) {
      sel.appendChild(h('option', { value: t.path },
        `${t.path}${t.expansions ? ' ✓有 expansions' : '（没有 expansions 目录）'}`));
    }
    if (!(r.targets || []).length) {
      sel.appendChild(h('option', { value: '' }, r.hint || '没找到 EDOPro'));
    }
  } catch (e) { sel.appendChild(h('option', { value: '' }, '探测失败：' + e.message)); }
}

async function install(dry) {
  const target = $('#edopro-target').value || undefined;
  if (!dry) {
    const ok = confirm('真安装会写入 EDOPro 目录。\n\n' +
      '同名文件会先备份到 .cardforge_backup/，可以回退。\n' +
      '建议先跑一次「预演」看清要写哪些文件。\n\n现在继续？');
    if (!ok) return;
  }
  try {
    const r = await api.post('/api/export/install', {
      pack_dir: packDir, target, dry_run: dry, merge_strings: true, backup: true
    });
    const res = r.result || {};
    $('#install-view').textContent = pretty(res).slice(0, 8000);
    const note = $('#install-notice');
    clear(note);
    note.className = 'notice ' + (dry ? 'warn' : res.ok ? 'ok' : 'bad');
    note.append(h('b', { text: dry ? '这是预演，什么都没写。' : (res.ok ? '安装完成。' : '安装没成功。') }),
      h('br'), (res.hint || ''),
      res.backup_dir ? h('div', {}, h('br'), '备份在：' + res.backup_dir) : null,
      res.will_write ? h('div', {}, h('br'), '将写入 ' +
        (Array.isArray(res.will_write) ? res.will_write.length : '?') + ' 项') : null);
    if (!dry && res.ok) toast('已安装，重启 EDOPro 生效', { kind: 'ok' });
    else if (dry) toast('预演完成，看右侧清单', { kind: 'ok' });
  } catch (e) {
    toast('安装失败：' + e.message, { kind: 'err', hint: e.hint });
  }
}
