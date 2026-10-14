/* 一次跑三个场景的 CDP 验收。 */
const PORT = process.env.CDP_PORT || '9333';
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

async function shot(send, path) {
  const s = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
  fs.writeFileSync(path, Buffer.from(s.data, 'base64'));
  console.log('  saved', path);
}

async function main() {
  const { send, close } = await connect();
  await send('Page.enable'); await send('Runtime.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 1280, height: 800, deviceScaleFactor: 2, mobile: false });
  await send('Page.navigate', { url: 'http://127.0.0.1:8790' });
  await sleep(2500);
  for (let i = 0; i < 40; i++) {
    if ((await ev(send, "document.querySelector('.boot-overlay') ? 'booting' : 'ready'")) === 'ready') break;
    await sleep(700);
  }
  await sleep(1500);

  // 场景 1：顶栏系列按钮存在
  console.log('S1 顶栏系列按钮:', await ev(send, "!!document.querySelector('#btn-archetypes')"));

  // 场景 2：打开系列面板，看卡数与审计按钮
  await ev(send, "document.querySelector('#btn-archetypes').click()");
  await sleep(2500);
  console.log('S2 面板文本:');
  console.log(await ev(send, "(document.querySelector('#modal-body')||{}).innerText"));
  await shot(send, '_probe/ui_arch_2_panel.png');

  // 场景 3：点「G4 审计」，看真实报告
  await ev(send, "(()=>{const b=[...document.querySelectorAll('#modal-foot button, .arch-acts button')].find(x=>x.textContent.includes('G4')); if(b){b.click();return 'ok'}return 'nobtn'})()");
  await sleep(3000);
  console.log('S3 审计结果:');
  console.log(await ev(send, "(document.querySelector('.arch-out')||{}).innerText || (document.querySelector('#modal-body')||{}).innerText"));
  await shot(send, '_probe/ui_arch_3_audit.png');

  // 场景 4：关闭面板，看规格页「所属系列」的实时提示
  await ev(send, "document.querySelector('#modal-backdrop').hidden = true");
  await sleep(600);
  console.log('S4 规格页系列提示:');
  console.log(await ev(send, "(()=>{const hs=[...document.querySelectorAll('#f-belong .hint')];return hs.map(h=>h.dataset.state+': '+h.textContent).join('\\n')})()"));
  await shot(send, '_probe/ui_arch_4_spechint.png');

  close();
  process.exit(0);
}
main().catch((e) => { console.error('ERR', e.message); process.exit(1); });
