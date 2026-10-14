/* 全局状态。刻意做小：只有「跨面板共享」的东西才进来，
   面板内部状态留在各自模块里。 */

import { api } from './api.js';

// 界面各处统一从 state.js 取数据入口，少一层 import 噪声。
export { api };
export { ApiError, followJob, waitJob } from './api.js';

const listeners = new Map();

export const store = {
  meta: null,            // /api/meta
  state: null,           // /api/state
  caps: null,            // /api/render/capabilities
  cardId: 0,
  spec: null,            // 当前 CardSpec（前端可编辑副本）
  saved: null,           // 上次落盘的 spec，用来算 dirty
  session: '',
  persona: 'professional',
  gates: {},             // {G1:{status,...}}

  on(evt, fn) {
    if (!listeners.has(evt)) listeners.set(evt, new Set());
    listeners.get(evt).add(fn);
    return () => listeners.get(evt).delete(fn);
  },
  emit(evt, payload) {
    (listeners.get(evt) || []).forEach((fn) => {
      try { fn(payload); } catch (e) { console.error('监听器出错', evt, e); }
    });
  },

  set(key, value) {
    this[key] = value;
    this.emit(key, value);
  },

  isDirty() {
    if (!this.spec) return false;
    const a = JSON.stringify(this.spec), b = JSON.stringify(this.saved);
    return a !== b;
  },

  markSaved() { this.saved = JSON.parse(JSON.stringify(this.spec || null)); },

  /** 当前卡的关键字段，表单绑定时用。 */
  patch(obj) {
    if (!this.spec) return;
    Object.assign(this.spec, obj);
    this.emit('spec:patch', this.spec);
  },
  patchRender(obj) {
    if (!this.spec) return;
    this.spec.render = Object.assign({}, this.spec.render || {}, obj);
    this.emit('spec:patch', this.spec);
  },
};

export async function boot() {
  const [meta, state, caps] = await Promise.all([
    api.get('/api/meta'),
    api.get('/api/state'),
    api.get('/api/render/capabilities').catch(() => null),
  ]);
  // 档案表单独取一次，取不到不阻塞启动
  try { meta.art_profiles = await profiles(); } catch { meta.art_profiles = []; }
  store.set('meta', meta);
  store.set('state', state);
  store.set('caps', caps);
  return { meta, state, caps };
}

/** 档案下拉的选项（key → 中文名）。失败时返回空数组，让后端 auto 去选。 */
export async function profiles() {
  const r = await api.get('/api/art/models').catch(() => null);
  if (!r || !r.profiles) return [];
  return r.profiles.map((p) => [p.key, `${p.zh || p.key}（${p.chain || '?'}）`]);
}

/** 后端可能还没实现的模块会返回 501/503；这里只取「有没有」，不报错。 */
export async function probe(path, params) {
  try { return await api.get(path, params); }
  catch (e) { return { ok: false, unavailable: true, error: e.message, hint: e.hint }; }
}

export function zhMeta(table, key, fallback = '') {
  const row = (store.meta && store.meta[table] || {})[key];
  if (!row) return fallback || key;
  return row.zh || row.zh_cn || row.label || fallback || key;
}
