/* ══════════════════════════════════════════════════════════════════
   阶段 3 · 卡图（本机 ComfyUI）与卡面合成
   ──────────────────────────────────────────────────────────────────
   出图是本项目唯一会长时间占用机器的动作，所以：
   * 提交前先「预览工作流」（dry_run），让人看清要用哪些模型、什么尺寸；
   * 走后台任务 + SSE，界面不冻结；
   * ComfyUI 不在时明确说「不在了」，同时保留「上传自己的图」这条路。
   ══════════════════════════════════════════════════════════════════ */

import { api, store, waitJob, profiles } from './state.js';
import { $, clear, h, field, select, textInput, toast, modal, pretty } from './ui.js';
import { setRenderOverride, getRenderOverride, previewNow, save } from './spec.js';

const PRESETS = [
  ['t2i_single', '单张文生图'],
  ['t2i_layers', '分层出图（背景 + 主体）'],
  ['t2i_series', '系列批量（共享风格）'],
  ['style_ref', '画风参考（垫图）'],
  ['ipadapter_consistency', 'IPAdapter 一致性'],
  ['character_sheet', '角色设定图'],
  ['upscale', '放大'],
  ['remove_bg', '抠底'],
  ['inpaint_edit', '局部重绘'],
];

let artReq = {
  subject: '', background: '', style: '', preset: 't2i_single', profile: 'auto',
  seed: -1, count: 1, upscale: false, remove_bg: false, layers: false,
  cutout_bg: 'grey',
  extra_positive: '', extra_negative: '', loras: [],
};

let profileOpts = [['auto', '自动（按本机模型选）']];

export function initArt() {
  profiles().then((rows) => { if (rows && rows.length) { profileOpts = [['auto', '自动（按本机模型选）'], ...rows]; buildArtForm(); } })
    .catch(() => {});
  buildArtForm();
  buildRenderForm();
  checkComfy();
  store.on('card', () => {
    if (!artReq.subject && store.spec) artReq.subject = store.spec.display_name || store.spec.name;
    $('#f-art') && fillArtSubject();
    renderArtStrip();
    refreshArtPreview();
  });
  $('#btn-dryrun').addEventListener('click', () => generate({ dryRun: true }));
  $('#btn-generate').addEventListener('click', () => generate({ dryRun: false }));
  $('#btn-interrupt').addEventListener('click', interrupt);
  $('#btn-render').addEventListener('click', () => { previewNow(); refreshArtPreview(); });
  $('#btn-export-pics').addEventListener('click', exportPics);
  $('#btn-export-card') && $('#btn-export-card').addEventListener('click', exportCard);
}

/* ══════════════ 出图表单 ══════════════ */
function buildArtForm() {
  const meta = store.meta || {};
  const box = clear($('#f-art'));
  box.append(
    field('主体（画什么）', textInput(artReq.subject, {
      onChange: (v) => { artReq.subject = v; }
    }), { full: true, hint: '中文可以直接写；要精准控物种时建议直接写英文标签，' +
      '如 unicorn, single horn, horse body' }),
    field('风格描述', textInput(artReq.style, { onChange: (v) => { artReq.style = v; } }),
      { full: true }),
    field('背景（画在主体后面）', textInput(artReq.background, {
      onChange: (v) => { artReq.background = v; }
    }), { full: true, hint: '只在「分层出图」里用：先出这张**没有人**的环境，' +
      '再单独出主体并抠底。留空则按主体自动补一句空场景描述' }),
    field('工作流', select(PRESETS, artReq.preset, {
      onChange: (v) => {
        artReq.preset = v;
        if (v === 't2i_layers') artReq.layers = true;
        buildArtForm();
      }
    }), { hint: '「分层出图」= 背景与主体分两次生成，出框时只有主体越出卡图窗' }),
    field('主体纯色底', select([['grey', '灰（默认，最稳）'], ['white', '白'],
      ['black', '黑'], ['green', '绿幕'], ['magenta', '品红']],
      artReq.cutout_bg, { onChange: (v) => { artReq.cutout_bg = v; } }),
      { hint: '主体 pass 用这块纯色底再抠底。主体是白色就换灰/黑，别用白底' }),
    field('模型档案', select(profileOpts, artReq.profile,
      { onChange: (v) => { artReq.profile = v; } }),
      { hint: '自动选择会给出理由，见「本机模型」' }),
    field('种子', h('input', { type: 'number', value: artReq.seed,
      oninput: (e) => { artReq.seed = parseInt(e.target.value || '-1', 10); } }),
      { hint: '-1 = 随机。批量时**每张必须换 seed**，同 seed 会让构图雷同' }),
    field('张数', h('input', { type: 'number', min: 1, max: 8, value: artReq.count,
      oninput: (e) => { artReq.count = parseInt(e.target.value || '1', 10); } })),
    field('附加正向', textInput(artReq.extra_positive, { onChange: (v) => { artReq.extra_positive = v; } })),
    field('附加负向', textInput(artReq.extra_negative, { onChange: (v) => { artReq.extra_negative = v; } })),
    field('增强', h('div.chips', {},
      h('label', {}, checkbox('upscale', '放大', artReq.upscale, (v) => { artReq.upscale = v; })),
      h('label', {}, checkbox('remove_bg', '抠底', artReq.remove_bg, (v) => { artReq.remove_bg = v; })),
      h('label', {}, checkbox('layers', '分层（背景+主体两次生成）', artReq.layers,
        (v) => { artReq.layers = v; }))
    ), { full: true, hint: '本机没有 clip_vision / controlnet 模型时，' +
      'IPAdapter 与 ControlNet 链路不可用，界面会自动跳过这些环节' }),
    field('工具', h('div', {},
      h('button.mini-btn', { onclick: showModels, type: 'button' }, '本机模型'),
      h('button.mini-btn.alt', { onclick: uploadArt, type: 'button' }, '上传我自己的图'),
      h('button.mini-btn.alt', { onclick: exportWorkflow, type: 'button' }, '导出工作流 JSON')
    ), { full: true }),
  );
  fillArtSubject();
}

function checkbox(key, label, checked, onChange) {
  const cb = document.createElement('input');
  cb.type = 'checkbox'; cb.checked = !!checked;
  cb.addEventListener('change', () => onChange(cb.checked));
  return h('span', {}, cb, h('span', { text: label }));
}

function fillArtSubject() {
  const inp = $('#f-art input');
  if (inp && store.spec && !artReq.subject) inp.value = store.spec.display_name || store.spec.name || '';
}

/* ══════════════ 卡面表单 ══════════════ */
function buildRenderForm() {
  const meta = store.meta || {};
  const box = $('#f-render');
  if (!box) return;
  clear(box);
  const rar = Object.entries(meta.rarities || {}).map(([k, v]) => [k, v.zh_cn || v.zh || k]);
  const fa = Object.entries(meta.fullart_modes || {}).map(([k, v]) => [k, v.zh || v.zh_cn || k]);
  const lg = Object.entries(meta.langs || {}).map(([k, v]) => [k, v.zh_cn || k]);
  const spec = store.spec || {};
  const r = spec.render || {};
  box.append(
    field('罕贵度', select(rar, r.rarity || 'common',
      { onChange: (v) => setRender(Object.assign({}, getRenderOverride(), { rarity: v })) }),
      { hint: '25 种罕贵按「五层可叠加」实现：卡名/卡图/属性/文本框/卡框各自独立参与' }),
    field('出框档位', select(fa, (r.fullart || {}).mode || 'none',
      { onChange: (v) => setRender(Object.assign({}, getRenderOverride(), { fullart: v })) }),
      { hint: '出框是设计处理，与罕贵正交，可任意叠加' }),
    field('卡面文字语言', select(lg, r.lang_text || 'zh_cn',
      { onChange: (v) => setRender(Object.assign({}, getRenderOverride(), { lang_text: v })) })),
    field('卡名语言', select(lg, r.lang_name || 'zh_cn',
      { onChange: (v) => setRender(Object.assign({}, getRenderOverride(), { lang_name: v })) })),
    field('插画位置', h('input', { type: 'range', min: -0.5, max: 0.5, step: 0.02,
      value: r.art_offset_y || 0,
      oninput: (e) => setRender(Object.assign({}, getRenderOverride(), { art_offset_y: +e.target.value })) }),
      { hint: '微调垂直构图，不影响卡图文件本身' }),
    field('插画缩放', h('input', { type: 'range', min: 1, max: 1.6, step: 0.02,
      value: r.art_scale || 1,
      oninput: (e) => setRender(Object.assign({}, getRenderOverride(), { art_scale: +e.target.value })) })),
    field('卡图窗斜切框', h('input', { type: 'range', min: 0, max: 1.5, step: 0.05,
      value: (r.bezel === undefined || r.bezel === null) ? 1 : r.bezel,
      oninput: (e) => setRender(Object.assign({}, getRenderOverride(), { bezel: +e.target.value })) }),
      { hint: '官方印刷卡实测的那圈钢色斜切带 + 窗沿暗线 + 内侧亮发丝。' +
        '1 = 官方量，0 = 关掉；出框类档位不画这层（官方由画面破坏窗边界）' }),
    field('主体出框·放大', h('input', { type: 'range', min: 1, max: 1.8, step: 0.02,
      value: ((r.fullart || {}).subject_scale) || 1.3,
      oninput: (e) => setRender(Object.assign({}, getRenderOverride(), { subject_scale: +e.target.value })) }),
      { hint: '只在「主体出框」档生效：主体相对卡图窗的放大倍率。' +
        '溢出量有上限，最多顶到卡名栏上沿，不会捅破卡框' }),
    field('主体出框·上移', h('input', { type: 'range', min: -0.3, max: 0.1, step: 0.01,
      value: ((r.fullart || {}).subject_offset_y) || -0.1,
      oninput: (e) => setRender(Object.assign({}, getRenderOverride(), { subject_offset_y: +e.target.value })) }),
      { hint: '负值 = 上移，让头/武器越出窗沿' }),
  );
}

function setRender(obj) {
  setRenderOverride(obj);
  if (!store.spec) return;
  // 预览接口吃的是**平铺**参数（fullart=档位字符串、subject_scale=数字），
  // 但落盘的 spec 必须是 render.fullart = {mode, ...} 对象 —— 直接把平铺值
  // 塞进 spec 会让保存报 "FullArtOptions.from_dict 需要 dict，收到 str"。
  const next = Object.assign({}, store.spec.render, obj);
  if (typeof next.fullart === 'string') next.fullart = { mode: next.fullart };
  const nested = Object.assign({}, (typeof next.fullart === 'object' && next.fullart) || {});
  for (const k of ['subject_scale', 'subject_offset_y', 'bleed_top', 'bleed_bottom',
                   'panel_opacity', 'name_stroke', 'fade_px']) {
    if (k in next) { nested[k] = next[k]; delete next[k]; }
  }
  next.fullart = nested;
  store.spec.render = next;
}

/* ══════════════ 状态 / 任务 ══════════════ */
async function checkComfy() {
  const chip = $('#comfy-chip');
  if (!chip) return;
  chip.textContent = '检测中…'; chip.className = 'chip';
  try {
    const r = await api.get('/api/art/capabilities');
    if (r.available === false || r.ok === false) {
      chip.textContent = 'ComfyUI 不在线'; chip.className = 'chip bad';
      chip.title = (r.reason || r.error || '') + '\n→ ' + (r.hint || '可以用「上传我自己的图」');
      setGenerateEnabled(false);
      return;
    }
    const n = Object.entries(r.counts || r.models || {}).map(([k, v]) => `${k} ${v}`).join('，');
    chip.textContent = 'ComfyUI 已连接';
    chip.className = 'chip ok';
    chip.title = n;
    setGenerateEnabled(true);
  } catch (e) {
    chip.textContent = 'ComfyUI 检测失败'; chip.className = 'chip warn';
    chip.title = e.message;
    setGenerateEnabled(true);  // 检测失败不等于不能试
  }
}

function setGenerateEnabled(on) {
  const b = $('#btn-generate'); if (b) b.disabled = !on;
  const d = $('#btn-dryrun'); if (d) d.disabled = false;
}

async function generate({ dryRun }) {
  if (!store.spec) { toast('先选中一张卡', { kind: 'warn' }); return; }
  if (!dryRun && store.isDirty()) {
    toast('规格还没保存，先保存再出图', { kind: 'warn', hint: '出图按卡号入库，卡号得先存在' });
    return;
  }
  const body = { card: store.spec.id, dry_run: dryRun, ...artReq };
  if (dryRun) {
    try {
      const r = await api.post('/api/art/generate', body);
      showDryRun(r.result || r);
    } catch (e) { toast('工作流预演失败：' + e.message, { kind: 'err', hint: e.hint }); }
    return;
  }
  const bar = $('#art-progress'), fill = $('#art-bar'), msg = $('#art-msg');
  bar.hidden = false; fill.style.width = '4%'; msg.textContent = '排队中…';
  setGenerateEnabled(false);
  // 艾莉娅（立绘陪伴栏）进「工作」态
  window.dispatchEvent(new CustomEvent('cardforge:job',
    { detail: { state: 'working', label: '卡图生成' } }));
  try {
    const res = await waitJob('/api/art/generate', body, (ev) => {
      if (ev.event === 'progress' || ev.event === 'started') {
        fill.style.width = Math.max(4, (ev.progress || 0) * 100) + '%';
        msg.textContent = ev.message || '出图中…';
      }
    });
    fill.style.width = '100%';
    msg.textContent = res.ok ? `完成 · 用时 ${Math.round((res.took_ms || 0) / 100) / 10}s`
      : (res.timeout ? '还在跑（已超时断开，产物会落盘）' : '没跑成');
    if (res.ok) {
      toast('卡图已生成并入库', { kind: 'ok' });
      await renderArtStrip();
      refreshArtPreview();
      window.dispatchEvent(new CustomEvent('cardforge:job', { detail: {
        state: 'pass', label: '卡图生成',
        facts: `卡图已生成并入库${res.took_ms ? `（用时 ${Math.round(res.took_ms / 100) / 10} 秒）` : ''}。` } }));
    } else {
      toast(res.error || '出图失败', { kind: 'err', hint: res.hint ||
        'ComfyUI 的 400 会带节点错误详情；界面「本机模型」能看到有哪些可用' });
      window.dispatchEvent(new CustomEvent('cardforge:job', { detail: {
        state: 'alert', label: '卡图生成',
        facts: String(res.error || '出图失败') + '。' } }));
    }
  } catch (e) {
    msg.textContent = '失败';
    toast('出图失败：' + e.message, { kind: 'err', hint: e.hint });
    window.dispatchEvent(new CustomEvent('cardforge:job', { detail: {
      state: 'alert', label: '卡图生成', facts: '出图请求失败：' + e.message } }));
  } finally {
    setGenerateEnabled(true);
  }
}

function showDryRun(r) {
  const meta = r.meta || {};
  modal({
    title: '将要执行的工作流（未提交）',
    body: h('div', {},
      h('div.notice', {},
        h('b', { text: '模型：' }), (meta.profile || meta.checkpoint || meta.unet || '（未定）'), h('br'),
        h('b', { text: '尺寸：' }), `${meta.width || '?'} × ${meta.height || '?'}`,
        ` · 步数 ${meta.steps || '?'} · CFG ${meta.cfg || '?'} · 种子 ${meta.seed ?? '?'}`, h('br'),
        h('b', { text: '节点数：' }), String(r.workflow_nodes ?? (r.workflow ? Object.keys(r.workflow).length : '?'))),
      h('h4', { text: '正向提示词' }),
      h('pre.code-view.small', { text: meta.positive || '(未见)' }),
      h('h4', { text: '负向提示词' }),
      h('pre.code-view.small', { text: meta.negative || '(未见)' }),
      h('p.footnote', { text: '确认无误后点「开始出图」提交。dry_run 不会占用显存。' })),
  });
}

async function showModels() {
  const r = await api.get('/api/art/models').catch((e) => ({ ok: false, error: e.message }));
  if (!r.ok) { toast(r.error || '取不到模型', { kind: 'err', hint: r.hint }); return; }
  const counts = Object.entries(r.counts || {}).map(([k, v]) => `${k} ${v}`).join(' · ');
  const det = r.detected || {};
  modal({
    title: '本机模型与自动选型',
    body: h('div', {},
      h('div.notice', {}, h('b', { text: '已探测：' }), counts || '（空）', h('br'),
        h('b', { text: '自动选中档案：' }), `${det.zh || '?'}（${det.key || '?'}）`, h('br'),
        h('span', { text: det.notes || '' })),
      h('pre.code-view.small', { text: pretty(r.detected_why || {}) }),
      h('h4', { text: '可用档案' }),
      h('table.grid', {}, h('thead', {}, h('tr', {},
        ['档案', '链路', '步数', 'CFG', '采样', '许可说明'].map((x) => h('th', { text: x })))),
        h('tbody', {}, (r.profiles || []).map((p) => h('tr', {},
          h('td', { text: p.zh || p.key }), h('td', { text: p.chain }),
          h('td', { text: String(p.steps) }), h('td', { text: String(p.cfg) }),
          h('td', { text: p.sampler }), h('td', { text: p.notes || '' }))))),
      h('p.footnote', { text: '许可差异极大：pony / noobai / illustrious 明确禁止商业化，' +
        'animagine 与 qwen_image 可商用。要出可卖的卡先看这一列。' })),
  });
}

async function exportWorkflow() {
  try {
    const r = await api.post('/api/art/workflow', {
      preset: artReq.preset, profile: artReq.profile,
      card: store.spec ? store.spec.id : undefined
    });
    toast('工作流已导出', { kind: 'ok',
      hint: r.path + ' · ComfyUI 里直接拖进画布即可导入' });
    modal({ title: '导出的工作流', body: h('pre.code-view.small', { text: pretty(r.workflow).slice(0, 6000) }) });
  } catch (e) { toast('导出失败：' + e.message, { kind: 'err', hint: e.hint }); }
}

async function uploadArt() {
  if (!store.spec) { toast('先选中一张卡', { kind: 'warn' }); return; }
  const inp = h('input', { type: 'file', accept: 'image/*' });
  modal({
    title: '上传自己的卡图',
    body: h('div', {}, inp,
      h('p.footnote', { text: '图会进「卡图资产库」并设为当前版本。' +
        '建议 842×1228 以上；卡图窗是 880×677 的横构图，太方的图会被裁。' })),
    actions: [{ label: '上传', class: 'mini-btn primary', keepOpen: true, onClick: async () => {
      const f = inp.files && inp.files[0];
      if (!f) { toast('还没选文件', { kind: 'warn' }); return; }
      const dataUrl = await new Promise((res) => {
        const fr = new FileReader(); fr.onload = () => res(fr.result); fr.readAsDataURL(f);
      });
      try {
        const r = await api.post('/api/render/upload-art', { card: store.spec.id, image: dataUrl });
        toast('已入库为 v' + (r.saved && r.saved.version), { kind: 'ok' });
        await renderArtStrip(); refreshArtPreview();
      } catch (e) { toast('上传失败：' + e.message, { kind: 'err', hint: e.hint }); }
    } }]
  });
}

async function interrupt() {
  try {
    const r = await api.post('/api/art/interrupt', {});
    toast(r.note || '已发送打断请求', { kind: 'warn' });
  } catch (e) { toast('打断失败：' + e.message, { kind: 'err', hint: e.hint }); }
}

/* ══════════════ 展示 ══════════════ */
async function renderArtStrip() {
  const box = $('#art-strip');
  if (!box || !store.spec) return;
  clear(box);
  try {
    const r = await api.get(`/api/art/library/${store.spec.id}`);
    const cur = (r.current || {}).version;
    for (const v of (r.versions || []).slice().reverse().slice(0, 8)) {
      box.appendChild(h(`figure${v.version === cur ? '.is-current' : ''}`, {
        onclick: () => useVersion(v.version), title: `点我设为当前 v${v.version}`
      },
        h('img', { src: v.url || '', loading: 'lazy', alt: `卡图 v${v.version}` }),
        h('figcaption', { text: 'v' + v.version + (v.version === cur ? ' ·' : '') })));
    }
    if (!(r.versions || []).length) {
      box.appendChild(h('p.footnote', { text: '这张卡还没有卡图。出图或上传后会出现在这里。' }));
    }
  } catch (e) {
    box.appendChild(h('p.footnote', { text: '卡图库读取失败：' + e.message }));
  }
}

async function useVersion(v) {
  try {
    await api.post(`/api/art/library/${store.spec.id}/use`, { version: v });
    toast('已切换到 v' + v, { kind: 'ok' });
    renderArtStrip(); refreshArtPreview(); previewNow();
  } catch (e) { toast('切换失败：' + e.message, { kind: 'err', hint: e.hint }); }
}

async function refreshArtPreview() {
  const img = $('#art-preview-img');
  if (!img || !store.spec) return;
  try {
    const blob = await api.blob('/api/render/preview', { card: store.spec.id, width: 421,
      ...getRenderOverride() });
    img.src = URL.createObjectURL(blob);
    img.alt = `卡面 · ${store.spec.display_name}`;
  } catch (e) {
    img.removeAttribute('src');
    toast('卡面渲染失败：' + e.message, { kind: 'err', hint: e.hint });
  }
}

async function exportPics() {
  if (!store.spec) { toast('先选中一张卡', { kind: 'warn' }); return; }
  try {
    const r = await api.post('/api/render/export', { card: store.spec.id,
      sizes: ['edopro', 'mdpro3', 'share'], ...getRenderOverride() });
    toast('已导出 ' + (r.files || []).length + ' 张', { kind: 'ok', hint: (r.files || []).join('、') });
  } catch (e) { toast('导出失败：' + e.message, { kind: 'err', hint: e.hint }); }
}

/**
 * 直接导出卡面 —— 走浏览器的原生下载，拿到的就是成品图本体。
 * 多尺寸时后端打成 zip 一起给，不用点好几次。
 */
async function exportCard() {
  if (!store.spec) { toast('先选中一张卡', { kind: 'warn' }); return; }
  const size = ($('#export-size') || {}).value || 'edopro';
  const fmt = ($('#export-fmt') || {}).value || 'jpg';
  const btn = $('#btn-export-card');
  if (btn) btn.disabled = true;
  window.dispatchEvent(new CustomEvent('cardforge:job',
    { detail: { state: 'working', label: '导出卡面' } }));
  try {
    const url = api.url('/api/render/card-image', {
      card: store.spec.id, size, fmt, ...getRenderOverride(),
    });
    const res = await fetch(url, { credentials: 'same-origin' });
    if (!res.ok) {
      let d = {};
      try { d = await res.json(); } catch { /* 错误体少见 */ }
      throw new Error(d.error || `HTTP ${res.status}`);
    }
    const blob = await res.blob();
    const cd = res.headers.get('content-disposition') || '';
    const m = /filename\*=UTF-8''([^;]+)/i.exec(cd) || /filename="([^"]+)"/i.exec(cd);
    const name = m ? decodeURIComponent(m[1]) : `${store.spec.id}.${fmt}`;
    triggerDownload(blob, name);
    const kb = Math.round(blob.size / 1024);
    toast(`已导出 ${name}（${kb} KB）`, { kind: 'ok', ms: 4000,
      hint: '文件已存到浏览器的默认下载目录' });
    window.dispatchEvent(new CustomEvent('cardforge:job', { detail: {
      state: 'pass', label: '导出卡面',
      facts: `卡面已导出：${name}，${kb} KB。` } }));
  } catch (e) {
    toast('导出卡面失败：' + e.message, { kind: 'err',
      hint: e.hint || '确认已保存规格、且渲染层可用（见「自检」）' });
    window.dispatchEvent(new CustomEvent('cardforge:job', { detail: {
      state: 'alert', label: '导出卡面', facts: '导出失败：' + e.message } }));
  } finally {
    if (btn) btn.disabled = false;
  }
}

function triggerDownload(blob, filename) {
  const u = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = u; a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(u), 4000);
}
