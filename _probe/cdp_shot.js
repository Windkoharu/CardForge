/* 极简 CDP 驱动 —— 绕开 agent-browser 的 daemon（本机代理会把它卡死）。
   用法: node _probe/cdp_shot.js <url> <out.png> [点击选择器] [前置等待ms]
   内置 WebSocket（Node 22+），零依赖。 */
const url = process.argv[2];
const out = process.argv[3];
const clickSel = process.argv[4] || '';
const settleMs = parseInt(process.argv[5] || '1500', 10);
const PORT = process.env.CDP_PORT || '9333';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
  const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
  const page = list.find((t) => t.type === 'page');
  if (!page) throw new Error('没有可用 page');
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  let id = 0;
  const pending = new Map();
  const send = (method, params = {}) => new Promise((res, rej) => {
    const mid = ++id;
    pending.set(mid, { res, rej });
    ws.send(JSON.stringify({ id: mid, method, params }));
  });
  await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) {
      const { res, rej } = pending.get(m.id);
      pending.delete(m.id);
      m.error ? rej(new Error(JSON.stringify(m.error))) : res(m.result);
    }
  };

  await send('Page.enable');
  await send('Runtime.enable');
  await send('Emulation.setDeviceMetricsOverride',
    { width: 1280, height: 760, deviceScaleFactor: 2, mobile: false });
  await send('Page.navigate', { url });
  await sleep(settleMs);

  // 等启动面板消失
  for (let i = 0; i < 40; i++) {
    const r = await send('Runtime.evaluate', {
      expression: "document.querySelector('.boot-overlay') ? 'booting' : 'ready'",
      returnByValue: true,
    });
    const v = r.result && r.result.value;
    if (v === 'ready') { console.log(`ready after ${i} polls`); break; }
    await sleep(700);
  }
  await sleep(1200);

  if (clickSel) {
    const r = await send('Runtime.evaluate', {
      expression: `(() => { const el = document.querySelector(${JSON.stringify(clickSel)});
        if (!el) return 'MISSING'; el.click(); return 'CLICKED'; })()`,
      returnByValue: true,
    });
    console.log('click:', r.result && r.result.value);
    await sleep(2200);
    const txt = await send('Runtime.evaluate', {
      expression: "(document.querySelector('#modal-body')||{}).innerText || 'NO MODAL'",
      returnByValue: true,
    });
    console.log('--- modal text ---');
    console.log(txt.result && txt.result.value);
    console.log('--- /modal ---');
  }

  const shot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
  require('fs').writeFileSync(out, Buffer.from(shot.data, 'base64'));
  console.log('saved:', out);
  ws.close();
  process.exit(0);
}
main().catch((e) => { console.error('ERR', e.message); process.exit(1); });
