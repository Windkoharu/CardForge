/* 一次性验收：召唤条件面板的「从卡文识别素材」按钮是否在位、接口是否真的回数据。
   用法：node _probe/cdp_infer_summon.js  （需先起服务与 headless chrome） */
const PORT = process.env.CDP_PORT || '9333';
const APP = process.env.APP_URL || 'http://127.0.0.1:8795';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const fs = require('fs');

async function connect() {
  const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
  const page = list.find((t) => t.type === 'page');
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  let id = 0; const pending = new Map();
  const send = (method, params = {}) => new Promise((res, rej) => {
    const mid = ++id; pending.set(mid, { res, rej });
    ws.send(JSON.stringify({ id: mid, method, params }));
  });
  await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) {
      const { res, rej } = pending.get(m.id); pending.delete(m.id);
      m.error ? rej(new Error(JSON.stringify(m.error))) : res(m.result);
    }
  };
  return { send, close: () => ws.close() };
}
async function ev(send, expr) {
  const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
  if (r.exceptionDetails) return 'EXC: ' + JSON.stringify(r.exceptionDetails.exception && r.exceptionDetails.exception.description);
  return r.result && r.result.value;
}

(async () => {
  const { send, close } = await connect();
  await send('Page.enable'); await send('Runtime.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 1400, height: 900, deviceScaleFactor: 1, mobile: false });
  await send('Page.navigate', { url: APP });
  for (let i = 0; i < 40; i++) {
    if ((await ev(send, "document.querySelector('.boot-overlay') ? 'booting' : 'ready'")) === 'ready') break;
    await sleep(400);
  }
  // 打开一张融合卡（工作区里的 210000021 圣痕龙骑士 露米艾尔）
  await send('Page.navigate', { url: `${APP}/?card=210000021&stage=spec&panel=summon` });
  await sleep(2600);
  // 等面板真的渲染出来（读卡是异步的），最多 20 秒
  let diag = '';
  for (let i = 0; i < 40; i++) {
    diag = await ev(send, `(() => {
      const box = document.querySelector('#f-summon');
      const blk = document.querySelector('#b-summon');
      return JSON.stringify({
        box: !!box, children: box ? box.children.length : -1,
        hidden: blk ? blk.hidden : null,
        card: (window.__ui_card__ || (document.querySelector('.card-current')||{}).textContent || ''),
        boot: !!document.querySelector('.boot-overlay'),
        toasts: [...document.querySelectorAll('.toast')].map(t => t.textContent.trim()).slice(0,2),
      });
    })()`);
    if (diag && diag.includes('"children":') && !diag.includes('"children":0') &&
        !diag.includes('"children":-1')) break;
    await sleep(500);
  }
  console.log('面板诊断:', diag);
  const btn = await ev(send, `(() => {
    const b = [...document.querySelectorAll('#f-summon button')]
      .map(x => x.textContent.trim());
    return JSON.stringify({ found: b.some(t => t.includes('从卡文识别素材')), buttons: b });
  })()`);
  console.log('按钮检查:', btn);
  // 直接从前端调接口，确认接线（不走 UI 覆盖，避免改动用户数据）
  const api = await ev(send, `(async () => {
    const r = await fetch('/api/psct/infer-summon', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ card: 210000021,
        text: '包含「圣痕」怪兽的战士族怪兽×3' }) });
    const j = await r.json();
    return JSON.stringify({ status: r.status, ok: j.ok, count: j.count,
      first: (j.materials||[])[0] || null, notes: j.notes || [] });
  })()`);
  console.log('接口检查:', api);
  const s = await send('Page.captureScreenshot', { format: 'png' });
  fs.writeFileSync(process.env.SHOT || '_probe/cdp_infer_summon.png', Buffer.from(s.data, 'base64'));
  console.log('截图已存');
  close();
})().catch((e) => { console.error('ERR', e.message); process.exit(1); });
