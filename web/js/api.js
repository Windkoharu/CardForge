/* ══════════════════════════════════════════════════════════════════
   与本地内核对话的唯一通道。
   ──────────────────────────────────────────────────────────────────
   后端所有失败都返回 {ok:false, error, hint, kind}。这里统一抛成
   ApiError，并把 hint 一起带上去 —— 界面上的错误提示必须包含
   「下一步做什么」，只说「失败了」等于没说。
   ══════════════════════════════════════════════════════════════════ */

export class ApiError extends Error {
  constructor(message, { kind = 'internal', hint = '', status = 0, detail = null } = {}) {
    super(message);
    this.name = 'ApiError';
    this.kind = kind;
    this.hint = hint;
    this.status = status;
    this.detail = detail;
  }
}

function qs(params) {
  if (!params) return '';
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue;
    u.set(k, Array.isArray(v) ? v.join(',') : String(v));
  }
  const s = u.toString();
  return s ? '?' + s : '';
}

/**
 * 发一个请求。
 *
 * ``extra`` 里除了查询参数 ``params``，还可以带 ``signal`` —— 用于**取消**。
 * 取消时不要把它当错误吞掉：调用方要能区分「用户主动停」和「真的失败了」，
 * 所以这里原样把 AbortError 抛出去（它的 name 是 'AbortError'）。
 */
async function send(method, path, { params, body, signal } = {}) {
  const url = path + qs(params);
  const opt = { method, headers: {}, credentials: 'same-origin' };
  if (signal) opt.signal = signal;
  if (body !== undefined) {
    opt.headers['content-type'] = 'application/json';
    opt.body = typeof body === 'string' ? body : JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(url, opt);
  } catch (e) {
    if (e && e.name === 'AbortError') throw e;      // 主动取消，不是故障
    throw new ApiError('连不上本地服务（CardForge 可能已经关了）',
      { kind: 'offline', hint: '重新双击「启动.bat」，或运行 python -m cardforge serve' });
  }
  const text = await res.text();
  let data = null;
  if (text) { try { data = JSON.parse(text); } catch { data = { raw: text }; } }
  if (!res.ok) {
    const d = data || {};
    throw new ApiError(d.error || `请求失败（HTTP ${res.status}）`, {
      kind: d.kind || 'http', hint: d.hint || '', status: res.status, detail: d.detail
    });
  }
  return data;
}

export const api = {
  get: (p, params) => send('GET', p, { params }),
  post: (p, body, extra) => send('POST', p, { body: body ?? {}, ...(extra || {}) }),
  put: (p, body, extra) => send('PUT', p, { body: body ?? {}, ...(extra || {}) }),
  del: (p, params) => send('DELETE', p, { params }),
  url: (p, params) => p + qs(params),

  /** 取二进制（卡面预览）。未提交到磁盘的规格也能预览 —— 直接把 spec 对象 POST 过去。 */
  blob: async (p, body, params) => {
    const res = await fetch(p + qs(params), {
      method: 'POST', credentials: 'same-origin',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body ?? {})
    });
    if (!res.ok) {
      let d = {}; try { d = await res.json(); } catch { /* 二进制错误体少见 */ }
      throw new ApiError(d.error || `请求失败（HTTP ${res.status}）`,
        { kind: d.kind || 'http', hint: d.hint || '' });
    }
    return res.blob();
  },
};

/* ── 长任务：提交 → SSE 跟进度 → 拿结果 ───────────────────────── */

/**
 * 打开一个任务的 SSE 流。返回关闭函数。
 * 断线自动续读（带 since 游标），最多重试 5 次 —— 出图几分钟里
 * 浏览器偶发断连是常态，不能让用户从头等。
 */
export function followJob(jobId, onEvent, { onDead } = {}) {
  let closed = false, since = 0, tries = 0, es = null;
  const terminal = new Set(['done', 'error', 'cancelled']);

  const open = () => {
    if (closed) return;
    es = new EventSource(`/api/events?job=${encodeURIComponent(jobId)}&since=${since}`);
    es.onmessage = (ev) => {
      let data;
      try { data = JSON.parse(ev.data); } catch { return; }
      if (typeof data.seq === 'number') since = Math.max(since, data.seq);
      if (data.event === 'ping') return;
      onEvent(data);
      if (terminal.has(data.event) || terminal.has(data.status)) {
        closed = true; es.close();
      }
    };
    es.onerror = () => {
      es.close();
      if (closed) return;
      if (++tries > 5) { onDead && onDead(jobId); return; }
      setTimeout(open, 600 * tries);
    };
  };
  open();
  return () => { closed = true; if (es) es.close(); };
}

/** 提交一个任务并等它跑完（带进度回调）。 */
export async function waitJob(submitPath, body, onProgress) {
  const r = await api.post(submitPath, body);
  if (!r.job) return r;
  const params = new URLSearchParams({ job: r.job });
  const final = await new Promise((resolve, reject) => {
    const close = followJob(r.job, (ev) => {
      if (onProgress) onProgress(ev);
      if (ev.event === 'done') resolve(ev.result || { ok: true });
      else if (ev.event === 'error') reject(new ApiError(ev.error || '任务失败',
        { kind: ev.kind || 'job', hint: ev.hint || '' }));
      else if (ev.event === 'cancelled') resolve({ ok: false, cancelled: true });
      else if (ev.event === 'timeout') resolve({ ok: false, timeout: true, job: r.job });
    }, { onDead: (id) => reject(new ApiError(`进度连接断了，任务 ${id} 可能还在跑`,
      { kind: 'offline', hint: `产物仍会写到工作区，刷新列表即可看到` })) });
  });
  return { ...final, job: r.job };
}
