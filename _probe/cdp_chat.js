/* 艾莉娅抽屉聊天体验验收。
   覆盖：打开抽屉 → 问候 → 提问（忙碌态）→ 回答带操作条 →
         切人格保留历史 → 切回来看得见 → 刷新页面历史仍在 → 清空 →
         出口建议 → 重试 → 选中卡后「这张卡」能解出卡（缺陷 #34）。 */
const PORT = process.env.CDP_PORT || '9333';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const fs = require('fs');
const OUT = process.argv[2] || '_probe';

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
  const r = await send('Runtime.evaluate',
    { expression: expr, returnByValue: true, awaitPromise: true });
  if (r.exceptionDetails) {
    return 'EXC: ' + (r.exceptionDetails.exception
      && r.exceptionDetails.exception.description || JSON.stringify(r.exceptionDetails));
  }
  return r.result && r.result.value;
}

async function shot(send, p) {
  const s = await send('Page.captureScreenshot', { format: 'png' });
  fs.writeFileSync(p, Buffer.from(s.data, 'base64'));
  console.log('  saved', p);
}

async function waitReady(send) {
  for (let i = 0; i < 45; i++) {
    if ((await ev(send, "document.querySelector('.boot-overlay')?'b':'r'")) === 'r') return true;
    await sleep(700);
  }
  return false;
}

async function main() {
  const { send, close } = await connect();
  await send('Page.enable'); await send('Runtime.enable');
  await send('Emulation.setDeviceMetricsOverride',
    { width: 1440, height: 900, deviceScaleFactor: 2, mobile: false });
  // 从干净状态开始
  await send('Page.navigate', { url: 'http://127.0.0.1:8790' });
  await sleep(1500);
  await ev(send, "localStorage.removeItem('cardforge.chat.v1')");

  await send('Page.navigate', { url: 'http://127.0.0.1:8790' });
  await sleep(2500);
  console.log('就绪:', await waitReady(send));
  await sleep(1500);

  console.log('\n── A. 清空按钮存在 ──');
  console.log('  #btn-clear-chat:', await ev(send, "!!document.querySelector('#btn-clear-chat')"));

  console.log('\n── B. 打开抽屉 → 问候 ──');
  await ev(send, "document.querySelector('#btn-assistant').click()");
  await sleep(2000);
  console.log('  抽屉可见:', await ev(send, "document.querySelector('#drawer').classList.contains('is-open')"));
  console.log('  消息数:', await ev(send, "document.querySelectorAll('#chat-log .msg').length"));
  console.log('  第一条:', await ev(send,
    "(document.querySelector('#chat-log .msg .body')||{}).textContent"));
  await shot(send, `${OUT}/ui_chat_1_greet.png`);

  console.log('\n── C. 提问 → 忙碌态 → 回答 ──');
  await ev(send, `(()=>{const i=document.querySelector('#chat-text');i.value='这个系列还缺什么卡？';document.querySelector('#chat-form').dispatchEvent(new Event('submit',{cancelable:true,bubbles:true}));return 'sent'})()`);
  await sleep(300);
  console.log('  忙碌态（输入禁用）:', await ev(send, "document.querySelector('#chat-text').disabled"));
  console.log('  发送键文案:', await ev(send, "document.querySelector('#chat-form button[type=submit]').textContent"));
  await shot(send, `${OUT}/ui_chat_2_busy.png`);
  // 等回答
  for (let i = 0; i < 40; i++) {
    if (!(await ev(send, "document.querySelector('#chat-text').disabled"))) break;
    await sleep(500);
  }
  await sleep(800);
  console.log('  回答条数:', await ev(send, "document.querySelectorAll('#chat-log .msg.bot').length"));
  console.log('  末条回答:', await ev(send,
    "(()=>{const b=[...document.querySelectorAll('#chat-log .msg.bot .body')];return (b[b.length-1]||{}).textContent})()"));
  console.log('  操作条（复制/重试）:', await ev(send,
    "(()=>{const a=[...document.querySelectorAll('#chat-log .msg.bot .msg-acts')];return a.length?[...a[a.length-1].querySelectorAll('button')].map(x=>x.textContent).join(','):'无'})()"));
  await shot(send, `${OUT}/ui_chat_3_answer.png`);

  console.log('\n── D. 切人格 → 历史保留 → 切回 ──');
  console.log('  切前消息数:', await ev(send, "document.querySelectorAll('#chat-log .msg').length"));
  await ev(send, "(()=>{const b=[...document.querySelectorAll('#persona-row button')].find(x=>x.dataset.key!=='professional');if(b)b.click();return b?b.textContent:'nobtn'})()");
  await sleep(2200);
  console.log('  切后（新人格）消息数:', await ev(send, "document.querySelectorAll('#chat-log .msg').length"));
  console.log('  切后消息数（应=1，仅问候）:', await ev(send, "document.querySelectorAll('#chat-log .msg').length"));
  await ev(send, "(()=>{const b=[...document.querySelectorAll('#persona-row button')].find(x=>x.dataset.key==='professional');if(b)b.click();return 'back'})()");
  await sleep(2200);
  const back = await ev(send, "document.querySelectorAll('#chat-log .msg').length");
  console.log('  切回 professional 后消息数:', back, back >= 3 ? '✓ 历史保留' : '✗ 历史丢了');
  await shot(send, `${OUT}/ui_chat_4_persona.png`);

  console.log('\n── E. 刷新页面 → 历史仍在 ──');
  await send('Page.navigate', { url: 'http://127.0.0.1:8790' });
  await sleep(2500);
  await waitReady(send);
  await sleep(1500);
  await ev(send, "document.querySelector('#btn-assistant').click()");
  await sleep(1500);
  const after = await ev(send, "document.querySelectorAll('#chat-log .msg').length");
  console.log('  刷新后消息数:', after, after >= 3 ? '✓ 持久化生效' : '✗ 丢了');
  await shot(send, `${OUT}/ui_chat_5_persist.png`);

  console.log('\n── F. 清空 ──');
  await ev(send, "window.confirm = () => true; document.querySelector('#btn-clear-chat').click()");
  await sleep(1800);
  console.log('  清空后消息数:', await ev(send, "document.querySelectorAll('#chat-log .msg').length"));

  console.log('\n── G. 答不上来 → 出口建议 ──');
  await ev(send, `(()=>{const i=document.querySelector('#chat-text');i.value='今天天气怎么样';document.querySelector('#chat-form').dispatchEvent(new Event('submit',{cancelable:true,bubbles:true}));return 'sent'})()`);
  for (let i = 0; i < 40; i++) {
    if (!(await ev(send, "document.querySelector('#chat-text').disabled"))) break;
    await sleep(500);
  }
  await sleep(800);
  console.log('  出口建议条数:', await ev(send, "document.querySelectorAll('#chat-log .msg-suggest button').length"));
  console.log('  建议:', await ev(send,
    "(()=>{const a=[...document.querySelectorAll('#chat-log .msg-suggest button')];return a.map(x=>x.textContent).join(' | ')})()"));
  await shot(send, `${OUT}/ui_chat_6_suggest.png`);

  console.log('\n── H. 重试按钮可用 ──');
  await ev(send, "(()=>{const a=[...document.querySelectorAll('#chat-log .msg.bot .msg-acts button')].filter(x=>x.textContent==='重试');a[0].click();return 'retried'})()");
  await sleep(3000);
  console.log('  重试后消息数:', await ev(send, "document.querySelectorAll('#chat-log .msg').length"));
  await shot(send, `${OUT}/ui_chat_7_retry.png`);

  console.log('\n── I. 选中卡 → 问「这张卡」能解出卡（缺陷 #34）──');
  // 抽屉保持打开，点左栏的卡 → 输入框提示应换成这张卡
  await ev(send, "(()=>{const li=document.querySelector('#card-list li[data-id=\"210000011\"]');if(li){li.click();return 'clicked'}return 'not-in-list'})()");
  await sleep(2000);
  console.log('  选中卡的 placeholder:',
    await ev(send, "document.querySelector('#chat-text').placeholder"));
  await ev(send, `(()=>{const i=document.querySelector('#chat-text');i.value='这张卡的打点合理吗';document.querySelector('#chat-form').dispatchEvent(new Event('submit',{cancelable:true,bubbles:true}));return 'sent'})()`);
  for (let i = 0; i < 40; i++) {
    if (!(await ev(send, "document.querySelector('#chat-text').disabled"))) break;
    await sleep(500);
  }
  await sleep(800);
  const last34 = await ev(send,
    "(()=>{const b=[...document.querySelectorAll('#chat-log .msg.bot .body')];return (b[b.length-1]||{}).textContent})()");
  console.log('  末条回答（前 70 字）:', String(last34).slice(0, 70).replace(/\n/g, ' / '));
  console.log('  解出了选中的卡:',
    /见习指挥/.test(String(last34)) && /计数：/.test(String(last34))
      ? '✓ 缺陷 #34 已修' : '✗ 仍答不出这张卡');
  await shot(send, `${OUT}/ui_chat_8_cardref.png`);

  close();
  process.exit(0);
}
main().catch((e) => { console.error('ERR', e.message); process.exit(1); });
