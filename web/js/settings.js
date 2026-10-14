/* ══════════════════════════════════════════════════════════════════
   大模型接入设置 —— 「艾莉娅挂在哪」的总装面板。
   ──────────────────────────────────────────────────────────────────
   它回答三个问题：
   1. 现在用哪个模型？（顶栏 chip + 面板第一屏，都来自 GET /api/llm）
   2. 怎么换/加/删？（列表行内操作 + 预设一键落账 + 表单）
   3. 连不连得通？（保存前试连 / 对已存配置试连，真问一句话）

   红线（和内核一致）：这里只配「谁提议」。艾莉娅的结论永远来自
   确定性内核（质量门 / 规则 / 知识库），LLM 只影响表达层。
   密钥只进不出：列表里是打码的，表单空着提交 = 保持旧 Key。
   ══════════════════════════════════════════════════════════════════ */

import { api } from './state.js';
import {
  $, clear, h, toast, modal, field, textInput, select, textarea, pretty,
} from './ui.js';

/** 与内核 ``llm_config.KINDS`` 一一对应。 */
const KINDS = [
  ['openai_compat', 'OpenAI 兼容（云端/本地通用）'],
  ['ollama', 'Ollama（原生 /api/chat）'],
  ['lmstudio', 'LM Studio'],
];

let inited = false;
let last = null;          // 最近一次 GET /api/llm 的完整响应

export function initSettings() {
  if (inited) return;
  inited = true;
  const btn = $('#btn-settings');
  if (btn) btn.addEventListener('click', openPanel);
  // 顶栏 chip 也能点 —— 看见当前模型不顺眼，一键就去改
  const chip = $('#llm-chip');
  if (chip) chip.addEventListener('click', openPanel);
  refreshChip();
}

/* ══════════════ 顶栏 chip：当前接入的模型 ══════════════ */

export async function refreshChip() {
  const chip = $('#llm-chip');
  if (!chip) return;
  let r = null;
  try { r = await api.get('/api/llm', { timeout_ms: 1200 }); last = r; }
  catch { return; }                     // 读不到就保持原样，不拿红字吓人
  const d = r.describe || {};
  if (d.active) {
    chip.textContent = d.model ? `${d.active} · ${d.model}` : d.active;
    chip.className = 'llm-chip llm';
    chip.title = `${d.active}（${d.base_url || '?'}）\n模型：${d.model || '未指定'}` +
      `\nKey：${d.masked_key || '无'}\n点我改接入`;
  } else {
    chip.textContent = '规则通路';
    chip.className = 'llm-chip rule';
    chip.title = '未接入大模型 —— 艾莉娅走规则引擎，功能不缺\n点我接一个（本地/云端均可）';
  }
}

/* ══════════════ 面板 ══════════════ */

async function openPanel() {
  const body = h('div.llm-panel', {},
    h('p.footnote', { text: '正在读接入配置…' }));
  const m = modal({
    title: '大模型接入',
    body,
    actions: [
      { label: '断开 LLM（回到规则通路）', class: 'mini-btn', keepOpen: true,
        onClick: async () => {
          try {
            await api.post('/api/llm', { action: 'off' });
            toast('已断开大模型 —— 艾莉娅回到规则通路', { kind: 'ok' });
            await reload(body);
            refreshChip();
          } catch (e) { toast('断开失败：' + e.message, { kind: 'err', hint: e.hint }); }
        } },
      { label: '关闭', class: 'mini-btn', onClick: () => m.close() },
    ],
  });
  await reload(body);
}

/** 重拉 status 并整屏重绘。任何 mutation 之后都走这里 —— 一个响应一屏，
 *  不会出现「改了但列表没动」。 */
async function reload(body) {
  let r;
  try { r = await api.get('/api/llm'); last = r; }
  catch (e) {
    clear(body).appendChild(h('div.notice.bad', {},
      h('b', { text: '接入配置读不出来：' }), e.message,
      h('div.hint', { text: '→ ' + (e.hint || '服务可能刚重启，刷新试试') })));
    return;
  }
  clear(body);
  body.appendChild(nowBox(r));
  body.appendChild(h('h4', { text: `已保存的接入（${(r.providers || []).length}）` }));
  body.appendChild(rowsBox(r, body));
  body.appendChild(h('h4', { text: '一键预设' }));
  body.appendChild(presetsBox(r, body));
  body.appendChild(h('h4', { text: '添加 / 编辑' }));
  body.appendChild(formBox(r, body));
  refreshChip();
  // 告诉别处「接入可能变了」：抽屉芯片重读 status，艾莉娅下一条消息
  // 就会走新模型（providers.detect_provider 的缓存键带配置版本+mtime）。
  window.dispatchEvent(new CustomEvent('cardforge:llm-changed'));
}

/* ── 第一屏：现在谁在说话 ───────────────────────────────────── */

function nowBox(r) {
  const d = r.describe || {};
  const det = r.detected || {};
  const box = h('div.llm-now');
  if (d.active) {
    box.appendChild(h('div', {},
      h('b', { text: `当前生效：${d.active}` }),
      d.model ? h('span', { text: ` · 模型 ${d.model}` }) : null));
    box.appendChild(h('div.llm-now-sub', { text: `${d.base_url || '?'}` +
      (d.masked_key ? ` · Key ${d.masked_key}` : ' · 无 Key（本地免鉴权）') }));
  } else {
    box.appendChild(h('div', {}, h('b', { text: '当前生效：规则通路' }),
      h('span', { text: '（没接大模型，艾莉娅照常给结论）' })));
  }
  const dp = det.provider || '';
  const dd = det.detail || {};
  const line = dp && dp !== 'none'
    ? `auto 实测：${dp}` + (dd.model ? ` · ${dd.model}` : '') +
      (dd.base_url ? ` · ${dd.base_url}` : '')
    : `auto 实测：无可用端点${dd.reason ? ' —— ' + dd.reason : ''}`;
  box.appendChild(h('div.llm-now-sub', { text: line }));
  return box;
}

/* ── 已存列表 ───────────────────────────────────────────────── */

function rowsBox(r, body) {
  const box = h('div.llm-rows');
  const rows = r.providers || [];
  if (!rows.length) {
    box.appendChild(h('p.footnote', { text: '还没有存过任何接入。下面的预设一键就能落账。' }));
    return box;
  }
  for (const p of rows) box.appendChild(row(p, r, body));
  return box;
}

function row(p, r, body) {
  const online = p.online;                 // true / false / null（云端不探）
  const dotCls = online === true ? 'on' : online === false ? 'off' : 'unk';
  const dotTitle = online === true ? '在线' : online === false ? '不在线'
    : '云端端点不探测（信任配置）';
  const el = h(`div.llm-row${p.active ? '.is-active' : ''}`, {},
    h('span.dot', { class: dotCls, title: dotTitle }),
    h('div.llm-row-main', {},
      h('b', { text: p.name }),
      p.active ? h('span.badge', { text: '使用中' }) : null,
      h('div.llm-row-sub', {
        text: `${kindZh(p.kind)} · ${p.base_url || '?'}` +
          (p.model ? ` · ${p.model}` : ' · 模型未指定') +
          (p.masked_key ? ` · Key ${p.masked_key}` : ''),
      })),
    h('div.llm-row-acts', {},
      p.active ? null : h('button.mini-btn', {
        text: '使用',
        onclick: async () => {
          try {
            await api.post('/api/llm', { action: 'use', name: p.name });
            toast(`已切到「${p.name}」`, { kind: 'ok' });
            await reload(body);
          } catch (e) { toast('切换失败：' + e.message, { kind: 'err', hint: e.hint }); }
        },
      }),
      h('button.mini-btn', {
        text: '测试',
        onclick: (ev) => testRow(p, ev.target, body),
      }),
      h('button.mini-btn', {
        text: '编辑',
        onclick: () => { fillForm(p); },
      }),
      h('button.mini-btn', {
        text: '删除',
        onclick: async (ev) => {
          // 二次确认内联完成 —— 不弹 blocking 对话框
          if (ev.target.dataset.armed !== '1') {
            ev.target.dataset.armed = '1';
            ev.target.textContent = '确认删除？';
            setTimeout(() => { if (ev.target.isConnected) {
              ev.target.dataset.armed = ''; ev.target.textContent = '删除';
            } }, 2600);
            return;
          }
          try {
            await api.post('/api/llm', { action: 'rm', name: p.name });
            toast(`已删除「${p.name}」`, { kind: 'ok' });
            await reload(body);
          } catch (e) { toast('删除失败：' + e.message, { kind: 'err', hint: e.hint }); }
        },
      })));
  return el;
}

/* ── 预设 ───────────────────────────────────────────────────── */

function presetsBox(r, body) {
  const box = h('div.llm-presets');
  for (const p of r.presets || []) {
    const cloud = !String(p.base_url || '').includes('127.0.0.1')
      && !String(p.base_url || '').includes('localhost');
    box.appendChild(h('button.mini-btn', {
      text: p.label || p.key,
      title: `${p.base_url || ''}${p.model ? ' · 默认模型 ' + p.model : ''}` +
        (cloud ? '\n云端：保存后记得填 API Key' : '\n本机：免鉴权'),
      onclick: async () => {
        try {
          const resp = await api.post('/api/llm', { action: 'preset', preset: p.key });
          if (resp.warn) toast(resp.warn, { kind: 'warn', ms: 9000 });
          toast(`已接入「${p.label || p.key}」并设为当前`, { kind: 'ok' });
          await reload(body);
        } catch (e) {
          toast('预设落账失败：' + e.message, { kind: 'err', hint: e.hint });
        }
      },
    }));
  }
  return box;
}

/* ── 表单 ───────────────────────────────────────────────────── */

const draft = { name: '', kind: 'openai_compat', base_url: '', api_key: '',
                model: '', note: '', timeout: 30, set_active: true };

function formBox(r, body) {
  const box = h('div.llm-form');
  const out = h('div.llm-test-out', { text: '试连结果会显示在这里。' });
  const kindSel = select(KINDS, draft.kind, { onChange: (v) => { draft.kind = v; } });
  const nameIn = textInput(draft.name, {
    placeholder: '配置名，如「本地LM」「DeepSeek」',
    onChange: (v) => { draft.name = v; },
  });
  const baseIn = textInput(draft.base_url, {
    placeholder: 'http://127.0.0.1:1234/v1 或 https://api.deepseek.com/v1',
    onChange: (v) => { draft.base_url = v; },
  });
  const keyIn = textInput(draft.api_key, {
    type: 'password', placeholder: '不填 = 保存时保持原有 Key 不变',
    onChange: (v) => { draft.api_key = v; },
  });
  const modelIn = textInput(draft.model, {
    placeholder: '留空 = 用服务返回的第一个模型',
    onChange: (v) => { draft.model = v; },
  });
  const noteIn = textInput(draft.note, {
    placeholder: '备注（给自己看的）',
    onChange: (v) => { draft.note = v; },
  });
  const timeoutIn = textInput(String(draft.timeout), {
    type: 'number', placeholder: '30',
    onChange: (v) => { draft.timeout = parseInt(v, 10) || 30; },
  });

  box.appendChild(field('配置名', nameIn, { req: true, hint: '改这个名字 = 新建一笔；同名 = 更新' }));
  box.appendChild(field('类型', kindSel));
  box.appendChild(field('地址 base_url', baseIn, { req: true,
    hint: '本地服务形如 http://127.0.0.1:1234/v1；云端多以 /v1 结尾' }));
  box.appendChild(field('API Key', keyIn, { hint: '只存本机 workspace/config/llm.json，不上传' }));
  box.appendChild(field('模型', modelIn, { hint: '本地服务可留空自动选；云端填服务商给的模型名' }));
  box.appendChild(field('备注', noteIn));
  box.appendChild(field('超时（秒）', timeoutIn));
  box.appendChild(out);

  const acts = h('div', { style: 'display:flex;gap:6px;flex-wrap:wrap;' },
    h('button.mini-btn', {
      text: '测试连接',
      onclick: async (ev) => {
        const base = (draft.base_url || '').trim();
        if (!base) { toast('先填地址再测', { kind: 'warn' }); return; }
        ev.target.disabled = true;
        out.className = 'llm-test-out';
        out.textContent = '正在试连…';
        try {
          const r2 = await api.post('/api/llm/test', {
            base_url: base, api_key: draft.api_key, model: draft.model,
            kind: draft.kind, timeout_ms: 8000,
          });
          paintTest(out, r2);
        } catch (e) {
          out.className = 'llm-test-out bad';
          out.textContent = `连不上：${e.message}\n→ ${e.hint || ''}`;
        } finally { ev.target.disabled = false; }
      },
    }),
    h('button.mini-btn.primary', {
      text: '保存并启用',
      onclick: async (ev) => {
        if (!(draft.name || '').trim()) { toast('配置名不能为空', { kind: 'warn' }); return; }
        if (!(draft.base_url || '').trim()) { toast('地址不能为空', { kind: 'warn' }); return; }
        ev.target.disabled = true;
        try {
          const resp = await api.post('/api/llm', {
            action: 'upsert',
            name: draft.name.trim(), kind: draft.kind,
            base_url: draft.base_url.trim(), api_key: draft.api_key,
            model: draft.model, note: draft.note, timeout: draft.timeout,
            set_active: true,
          });
          if (resp.warn) toast(resp.warn, { kind: 'warn', ms: 9000 });
          toast(`已保存「${draft.name.trim()}」并设为当前`, { kind: 'ok' });
          draft.api_key = '';            // 保存后清空密码框，不留明文在 DOM 里
          await reload(body);
        } catch (e) {
          toast('保存失败：' + e.message, { kind: 'err', hint: e.hint });
        } finally { ev.target.disabled = false; }
      },
    }));
  box.appendChild(acts);
  return box;
}

/** 点某一行的「编辑」= 把表单填成那笔账（密钥格留空）。 */
function fillForm(p) {
  draft.name = p.name || '';
  draft.kind = p.kind || 'openai_compat';
  draft.base_url = p.base_url || '';
  draft.api_key = '';
  draft.model = p.model || '';
  draft.note = p.note || '';
  draft.timeout = p.timeout || 30;
  const btn = $('#btn-settings');
  if (btn) btn.click();                 // 面板已开 → 重绘；没开 → 打开
}

/* ── 试连结果渲染 ───────────────────────────────────────────── */

async function testRow(p, btn, body) {
  btn.disabled = true;
  const old = btn.textContent;
  btn.textContent = '测…';
  try {
    const r = await api.post('/api/llm/test', { name: p.name, timeout_ms: 8000 });
    const line = r.ok
      ? `「${p.name}」连通 · ${r.ms}ms · 模型 ${(r.models || []).join('、') || '?'}` +
        (r.greet ? `\n它说：${r.greet}` : '')
      : `「${p.name}」不通：${r.error || '未知原因'}` +
        (r.hint ? `\n→ ${r.hint}` : '');
    toast(r.ok ? `「${p.name}」连通` : `「${p.name}」不通`, {
      kind: r.ok ? 'ok' : 'err', hint: line.replace(/\n/g, '；'), ms: 9000,
    });
  } catch (e) {
    toast('测试失败：' + e.message, { kind: 'err', hint: e.hint });
  } finally { btn.disabled = false; btn.textContent = old; }
}

function paintTest(out, r) {
  if (r.ok) {
    out.className = 'llm-test-out ok';
    out.textContent = `连通 · ${r.ms}ms\n模型：${(r.models || []).join('、') || '（未返回）'}` +
      (r.greet ? `\n它说：${r.greet}` : '');
  } else {
    out.className = 'llm-test-out bad';
    out.textContent = `不通：${r.error || '未知原因'}` + (r.hint ? `\n→ ${r.hint}` : '');
  }
}

/* ══════════════ 小工具 ══════════════ */

function kindZh(k) {
  const hit = KINDS.find(([v]) => v === k);
  return hit ? hit[1].split('（')[0] : (k || '?');
}
