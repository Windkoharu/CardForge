#!/usr/bin/env node
/* Browser-only regression checks using Node's built-in WebSocket + Chromium CDP. */
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';

const args = process.argv.slice(2);
const arg = (name) => args[args.indexOf(name) + 1];
const base = arg('--url');
const edge = arg('--edge');
const out = arg('--out');
if (!base || !edge || !out) throw new Error('usage: --url URL --edge BIN --out DIR');
fs.mkdirSync(out, { recursive: true });
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const assert = (ok, message) => { if (!ok) throw new Error(message); };

async function freePort() {
  const server = net.createServer();
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  const port = server.address().port;
  server.close();
  await once(server, 'close');
  return port;
}

class CDP {
  constructor(url) {
    this.ws = new WebSocket(url);
    this.seq = 0;
    this.pending = new Map();
    this.handlers = new Map();
  }
  async open() {
    if (this.ws.readyState === WebSocket.OPEN) return;
    await new Promise((resolve, reject) => {
      this.ws.addEventListener('open', resolve, { once: true });
      this.ws.addEventListener('error', reject, { once: true });
    });
    this.ws.addEventListener('message', (event) => {
      const msg = JSON.parse(event.data);
      if (msg.id) {
        const pending = this.pending.get(msg.id);
        if (!pending) return;
        this.pending.delete(msg.id);
        clearTimeout(pending.timer);
        if (msg.error) pending.reject(new Error(JSON.stringify(msg.error)));
        else pending.resolve(msg.result || {});
      } else if (msg.method) {
        for (const fn of this.handlers.get(msg.method) || []) fn(msg.params || {});
      }
    });
  }
  send(method, params = {}) {
    const id = ++this.seq;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`CDP timeout: ${method}`));
      }, 35000);
      this.pending.set(id, { resolve, reject, timer });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }
  on(method, fn) {
    if (!this.handlers.has(method)) this.handlers.set(method, []);
    this.handlers.get(method).push(fn);
  }
}

const port = await freePort();
const profile = path.join(out, 'chromium-profile');
fs.rmSync(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 150 });
const browser = spawn(edge, [
  '--headless=new', '--disable-gpu', '--no-first-run', '--disable-extensions',
  '--hide-scrollbars', `--remote-debugging-port=${port}`,
  `--user-data-dir=${profile}`, '--window-size=1680,960', 'about:blank',
], { stdio: ['ignore', 'ignore', 'ignore'] });

let cdp;
let originalId = 0;
const tempIds = [];
const tests = [];
const exceptions = [];
const requests = [];
let failCardList = false;

async function evaluate(expression) {
  const r = await cdp.send('Runtime.evaluate', {
    expression, awaitPromise: true, returnByValue: true, userGesture: true,
  });
  if (r.exceptionDetails) {
    const description = r.exceptionDetails.exception?.description || r.exceptionDetails.text || '页面表达式执行失败';
    throw new Error(`${description}\n表达式：${expression.slice(0, 500)}\n${JSON.stringify(r.exceptionDetails.stackTrace || {})}`);
  }
  return r.result?.value;
}

async function waitFor(expression, label = expression, timeout = 15000) {
  const deadline = Date.now() + timeout;
  let last;
  while (Date.now() < deadline) {
    try {
      const value = await evaluate(expression);
      if (value) return value;
      last = value;
    } catch (error) { last = error.message; }
    await delay(100);
  }
  throw new Error(`等待超时：${label}；最后结果：${JSON.stringify(last)}`);
}

async function test(name, fn) {
  try {
    await fn();
    tests.push({ name, ok: true });
    console.log(`PASS ${name}`);
  } catch (error) {
    tests.push({ name, ok: false, error: error.message });
    console.error(`FAIL ${name}: ${error.message}`);
  }
}

async function clickButton(label) {
    const clicked = await evaluate(`(() => {
      const b = [...document.querySelectorAll('button')]
        .find((x) => x.textContent.trim() === ${JSON.stringify(label)});
      if (!b) return false; b.click(); return true;
    })()`);
    assert(clicked, `找不到按钮：${label}`);
}

async function closeModal() {
  await evaluate(`document.dispatchEvent(new KeyboardEvent('keydown', {key:'Escape', bubbles:true}))`);
  await waitFor(`document.querySelector('#modal-backdrop').hidden`, '弹窗关闭');
}

async function openClean(id) {
  await evaluate(`(async () => {
    const {store} = await import('/js/state.js');
    const app = await import('/js/app.js');
    // 仅在隔离测试工作区里清理当前状态；空工作区的初始草稿也要能退出。
    if (store.isDirty() && store.saved) store.spec = JSON.parse(JSON.stringify(store.saved));
    store.markSaved();
    await app.openCard(${id});
  })()`);
  await waitFor(`(async()=>{const {store}=await import('/js/state.js');return store.cardId===${id}})()`, `打开卡 ${id}`);
}

try {
  let page;
  const deadline = Date.now() + 12000;
  while (Date.now() < deadline) {
    try {
      const pages = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
      page = pages.find((p) => p.type === 'page');
      if (page) break;
    } catch { /* Chromium is still starting. */ }
    await delay(100);
  }
  assert(page, 'Chromium 调试页面未就绪');
  cdp = new CDP(page.webSocketDebuggerUrl);
  await cdp.open();
  await Promise.all([
    cdp.send('Page.enable'), cdp.send('Runtime.enable'),
    cdp.send('Network.enable', { maxPostDataSize: 1024 * 1024 }),
  ]);
  cdp.on('Runtime.exceptionThrown', (p) => exceptions.push(p.exceptionDetails));
  cdp.on('Network.requestWillBeSent', (p) => {
    if (p.request?.postData) requests.push({ url: p.request.url, body: p.request.postData });
  });
  cdp.on('Fetch.requestPaused', (p) => {
    const pathname = new URL(p.request.url).pathname;
    if (failCardList && pathname === '/api/cards') {
      cdp.send('Fetch.failRequest', { requestId: p.requestId, errorReason: 'ConnectionRefused' }).catch(() => {});
    } else {
      cdp.send('Fetch.continueRequest', { requestId: p.requestId }).catch(() => {});
    }
  });

  await cdp.send('Page.navigate', { url: `${base}/?stage=spec` });
  await waitFor(`(async()=>{const {store}=await import('/js/state.js');
    return !!store.spec && !document.querySelector('#app-boot')})()`, '应用启动', 30000);
  originalId = await evaluate(`(async()=>{const {store}=await import('/js/state.js');return store.cardId})()`);

  await test('四阶段与键盘页签', async () => {
    await evaluate(`document.querySelector('#tab-spec').focus()`);
    await evaluate(`document.querySelector('#tab-spec').dispatchEvent(
      new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}))`);
    const state = await evaluate(`({
      active: document.querySelector('.stage-tab.is-active').dataset.stage,
      selected: document.querySelector('#tab-text').getAttribute('aria-selected'),
      visible: !document.querySelector('#panel-text').hidden,
    })`);
    assert(state.active === 'text' && state.selected === 'true' && state.visible, JSON.stringify(state));
    await evaluate(`(async()=>{(await import('/js/app.js')).switchStage('spec')})()`);
  });

  await test('弹窗焦点进入、Escape 关闭与焦点恢复', async () => {
    await evaluate(`(async()=>{
      document.querySelector('#tab-spec').focus();
      const {modal,h}=await import('/js/ui.js');
      window.__focusModal=modal({title:'焦点测试',body:h('input#focus-test'),actions:[{label:'关闭'}]});
    })()`);
    await waitFor(`document.activeElement && document.activeElement.id==='focus-test'`, '焦点进入弹窗');
    await closeModal();
    assert(await evaluate(`document.activeElement.id==='tab-spec'`), '焦点没有回到触发页签');
  });

  await test('空白草稿不会阻挡第一次新建', async () => {
    assert(originalId === 0, '页面测试必须从隔离空工作区开始');
    assert(!(await evaluate(`(async()=>{const {store}=await import('/js/state.js');return store.isDirty()})()`)),
      '空白初始草稿被误报为未保存');
    await evaluate(`(()=>{
      window.__oldPrompt=window.prompt;
      window.prompt=()=>{window.__promptCalled=true;return null};
      document.querySelector('#btn-new-card').click();
    })()`);
    await delay(200);
    const state = await evaluate(`({called:!!window.__promptCalled,
      modal:!document.querySelector('#modal-backdrop').hidden})`);
    await evaluate(`(()=>{window.prompt=window.__oldPrompt;
      delete window.__oldPrompt;delete window.__promptCalled;})()`);
    assert(state.called && !state.modal, JSON.stringify(state));
  });

  await test('建立隔离测试卡', async () => {
    const ids = await evaluate(`(async()=>{
      const {api}=await import('/js/state.js');
      const make=(name,lang)=>({id:0,name,frame:'effect',attribute:'暗',race:'魔法师族',
        level:4,atk:1600,dfd:1200,setcode:'0x0',archetype:'',name_i18n:{},
        text_i18n:{},pendulum_text_i18n:{},flavor:'',tags:[],link_markers:[],
        pendulum_effect_indices:[],summon:{materials:[],methods:[],limit:'',cannot_be_material:[]},
        effects:[{kind:'draw',trigger:'IGNITION',limit:'once_per_turn',params:{count:1},
          target:{filter_kind:'any',count:1,controller:'self'},cost:{kind:'none'},source:'manual'}],
        render:{rarity:'common',lang_name:'zh_cn',lang_text:lang,lang_flavor:'zh_cn',
          fullart:{mode:'none'},art_fit:'cover',art_scale:1,art_offset_y:0}});
      const a=await api.post('/api/cards',make('UI 临时 A','zh_cn'));
      const b=await api.post('/api/cards',make('UI 临时 B','en'));
      return [a.spec.id,b.spec.id];
    })()`);
    tempIds.push(...ids);
    assert(ids.every(Boolean), JSON.stringify(ids));
    await evaluate(`(async()=>{(await import('/js/app.js')).refreshCards()})()`);
    await openClean(tempIds[0]);
  });

  await test('取消新卡命名不会清空当前卡', async () => {
    await evaluate(`(()=>{
      window.__oldPrompt=window.prompt;
      window.prompt=()=>{window.__promptCalled=true;return null};
      document.querySelector('#btn-new-card').click();
    })()`);
    await delay(200);
    const state = await evaluate(`(async()=>{const {store}=await import('/js/state.js');return {
      called:!!window.__promptCalled,id:store.cardId,name:store.spec.name,
      modal:!document.querySelector('#modal-backdrop').hidden}})()`);
    await evaluate(`(()=>{window.prompt=window.__oldPrompt;
      delete window.__oldPrompt;delete window.__promptCalled;})()`);
    assert(state.called && !state.modal && state.id === tempIds[0] && state.name === 'UI 临时 A',
      JSON.stringify(state));
  });

  await test('未保存切卡：继续编辑保留输入', async () => {
    await evaluate(`(()=>{
      const f=[...document.querySelectorAll('#f-basic .field')]
        .find((x)=>x.querySelector('.k')?.textContent.trim().startsWith('卡名'));
      const i=f.querySelector('input'); i.value='UI 未保存输入'; i.dispatchEvent(new Event('input',{bubbles:true}));
      window.__cardNav=(window.__appPromise ||= import('/js/app.js')).then((app)=>app.openCard(${tempIds[1]}));
    })()`);
    await waitFor(`!document.querySelector('#modal-backdrop').hidden`, '未保存确认弹窗');
    await clickButton('继续编辑');
    const state = await evaluate(`(async()=>{const {store}=await import('/js/state.js');
      return {id:store.cardId,name:store.spec.name,dirty:store.isDirty()}})()`);
    assert(state.id === tempIds[0] && state.name === 'UI 未保存输入' && state.dirty, JSON.stringify(state));
  });

  await test('未保存切卡：放弃后才替换当前卡', async () => {
    await evaluate(`(()=>{window.__cardNav=import('/js/app.js').then((app)=>app.openCard(${tempIds[1]}));})()`);
    await waitFor(`!document.querySelector('#modal-backdrop').hidden`, '放弃修改弹窗');
    await clickButton('放弃修改');
    await waitFor(`(async()=>{const {store}=await import('/js/state.js');return store.cardId===${tempIds[1]}})()`, '放弃后切卡');
    assert(!(await evaluate(`(async()=>{const {store}=await import('/js/state.js');return store.isDirty()})()`)), '放弃后仍为 dirty');
    await openClean(tempIds[0]);
    assert(await evaluate(`(async()=>{const {store}=await import('/js/state.js');return store.spec.name==='UI 临时 A'})()`), '旧输入没有被丢弃');
  });

  await test('未保存切卡：保存并继续真正落盘', async () => {
    await evaluate(`(()=>{
      const f=[...document.querySelectorAll('#f-basic .field')]
        .find((x)=>x.querySelector('.k')?.textContent.trim().startsWith('卡名'));
      const i=f.querySelector('input'); i.value='UI 临时 A 已保存'; i.dispatchEvent(new Event('input',{bubbles:true}));
      window.__cardNav=(window.__appPromise ||= import('/js/app.js')).then((app)=>app.openCard(${tempIds[1]}));
    })()`);
    await waitFor(`!document.querySelector('#modal-backdrop').hidden`, '保存继续弹窗');
    await clickButton('保存并继续');
    await waitFor(`(async()=>{const {store}=await import('/js/state.js');return store.cardId===${tempIds[1]}})()`, '保存后切卡');
    const saved = await evaluate(`(async()=>{const {api}=await import('/js/state.js');
      return (await api.get('/api/cards/${tempIds[0]}')).spec.name})()`);
    assert(saved === 'UI 临时 A 已保存', `实际落盘：${saved}`);
  });

  await test('卡面设置与卡图主体按卡隔离', async () => {
    const langB = await evaluate(`[...document.querySelectorAll('#f-render .field')]
      .find((x)=>x.querySelector('.k')?.textContent.trim()==='卡面文字语言').querySelector('select').value`);
    assert(langB === 'en', `B 卡显示 ${langB}`);
    const subjectB = await evaluate(`document.querySelector('#f-art input').value`);
    assert(subjectB === 'UI 临时 B', `B 卡主体残留：${subjectB}`);
    await openClean(tempIds[0]);
    const langA = await evaluate(`[...document.querySelectorAll('#f-render .field')]
      .find((x)=>x.querySelector('.k')?.textContent.trim()==='卡面文字语言').querySelector('select').value`);
    assert(langA === 'zh_cn', `A 卡显示 ${langA}`);
    await evaluate(`(()=>{
      const s=[...document.querySelectorAll('#f-render .field')]
        .find((x)=>x.querySelector('.k')?.textContent.trim()==='卡面文字语言').querySelector('select');
      s.value='ja';s.dispatchEvent(new Event('change',{bubbles:true}));
    })()`);
    assert(await evaluate(`(async()=>{const {store}=await import('/js/state.js');
      return store.isDirty() && document.querySelector('#btn-save').classList.contains('is-dirty')})()`), '卡面变更未进入 dirty');
    await openClean(tempIds[1]);
    await openClean(tempIds[0]);
    const restored = await evaluate(`[...document.querySelectorAll('#f-render .field')]
      .find((x)=>x.querySelector('.k')?.textContent.trim()==='卡面文字语言').querySelector('select').value`);
    assert(restored === 'zh_cn', `换卡后设置残留：${restored}`);
  });

  await test('灵摆只有一个真实保存的左右共用刻度', async () => {
    await evaluate(`(()=>{
      const s=[...document.querySelectorAll('#f-basic .field')]
        .find((x)=>x.querySelector('.k')?.textContent.trim()==='卡种').querySelector('select');
      s.value=[...s.options].find((o)=>o.value.includes('pendulum')).value;
      s.dispatchEvent(new Event('change',{bubbles:true}));
    })()`);
    const count = await evaluate(`[...document.querySelectorAll('#f-monster .field')]
      .filter((x)=>x.querySelector('.k')?.textContent.trim().startsWith('灵摆刻度')).length`);
    assert(count === 1, `灵摆刻度输入框数量：${count}`);
    await evaluate(`(()=>{
      const i=[...document.querySelectorAll('#f-monster .field')]
        .find((x)=>x.querySelector('.k')?.textContent.trim().startsWith('灵摆刻度')).querySelector('input');
      i.value='7';i.dispatchEvent(new Event('input',{bubbles:true}));
    })()`);
    const state = await evaluate(`(async()=>{const {store}=await import('/js/state.js');return store.spec})()`);
    assert(state.pendulum_scale === 7 && !('pendulum_scale_right' in state), JSON.stringify(state));
    await openClean(tempIds[0]);
  });

  await test('卡文与脚本生成提交当前编辑规格', async () => {
    await evaluate(`(async()=>{
      const {store}=await import('/js/state.js');
      store.patch({name:'UI 当前编辑名'});
      (await import('/js/app.js')).switchStage('text');
      document.querySelector('#btn-compose').click();
    })()`);
    await waitFor(`!document.querySelector('#modal-backdrop').hidden`, '卡文生成结果');
    await closeModal();
    await evaluate(`document.querySelector('#btn-tidy-text').click()`);
    await waitFor(`!document.querySelector('#modal-backdrop').hidden`, '卡文整理结果');
    await closeModal();
    await evaluate(`document.querySelector('#btn-emit').click()`);
    const deadline = Date.now() + 15000;
    let relevant = [];
    while (Date.now() < deadline) {
      relevant = requests.filter((r) => /\/api\/(psct\/(compose|tidy)|lua\/emit)/.test(r.url));
      if (['compose', 'tidy', 'emit'].every((kind) => relevant.some((r) => r.url.includes(kind)))) break;
      await delay(100);
    }
    for (const kind of ['compose', 'tidy', 'emit']) {
      const r = relevant.find((x) => x.url.includes(kind));
      assert(r, `缺少 ${kind} 请求`);
      const body = JSON.parse(r.body);
      assert(body.spec?.name === 'UI 当前编辑名', `${kind} 仍提交旧卡号或旧规格`);
    }
    await openClean(tempIds[1]);
  });

  await test('列表读取失败不会伪装成空工作区', async () => {
    const message = await evaluate(`(async()=>{
      const {api}=await import('/js/state.js');const app=await import('/js/app.js');
      const original=api.get;api.get=async(p)=>{if(p==='/api/cards')throw new Error('UI 模拟读取失败');return original(p)};
      try{await app.refreshCards();return '没有抛出错误'}catch(e){return e.message}finally{api.get=original}
    })()`);
    assert(message === 'UI 模拟读取失败', message);
    assert(await evaluate(`!!document.querySelector('#card-list .list-error') && document.querySelector('#studio-hero').hidden`), '错误被显示成空列表');
    await evaluate(`(async()=>{(await import('/js/app.js')).refreshCards()})()`);
  });

  await test('启动时列表失败显示错误页并可重试', async () => {
    await cdp.send('Fetch.enable', { patterns: [{ urlPattern: '*', requestStage: 'Request' }] });
    failCardList = true;
    await cdp.send('Page.reload', { ignoreCache: true });
    await waitFor(`document.querySelector('#workspace-error')?.hidden===false`, '启动错误页', 30000);
    assert(await evaluate(`document.querySelector('#studio-hero').hidden`), '错误页同时显示空工作区欢迎页');
    failCardList = false;
    await evaluate(`document.querySelector('#btn-retry-cards').click()`);
    await waitFor(`(async()=>{const {store}=await import('/js/state.js');
      return !!store.spec && !document.querySelector('#app-boot')})()`, '重试恢复', 30000);
    await cdp.send('Fetch.disable');
  });

  await test('窄屏无页面级横向溢出', async () => {
    await cdp.send('Emulation.setDeviceMetricsOverride', {
      width: 390, height: 844, deviceScaleFactor: 1, mobile: false,
    });
    await evaluate(`(async()=>{(await import('/js/app.js')).switchStage('spec')})()`);
    await delay(300);
    const size = await evaluate(`({vw:innerWidth,doc:document.documentElement.scrollWidth,
      rail:document.querySelector('#rail').getBoundingClientRect().width,
      workspace:document.querySelector('#workspace').getBoundingClientRect().width})`);
    assert(size.doc <= size.vw && size.rail <= size.vw && size.workspace <= size.vw, JSON.stringify(size));
    await cdp.send('Emulation.clearDeviceMetricsOverride');
  });

  await evaluate(`(async()=>{
    const {api}=await import('/js/state.js');
    for(const id of ${JSON.stringify(tempIds)}) await api.post('/api/cards/'+id+'/delete',{});
  })()`);
  tempIds.length = 0;

  await test('浏览器无未捕获脚本异常', async () => {
    assert(!exceptions.length, JSON.stringify(exceptions).slice(0, 2000));
  });
} finally {
  failCardList = false;
  if (cdp && tempIds.length) {
    try {
      await evaluate(`(async()=>{const {api}=await import('/js/state.js');
        for(const id of ${JSON.stringify(tempIds)}) await api.post('/api/cards/'+id+'/delete',{});})()`);
    } catch { /* The Python harness also stops cleanly; report the original failure. */ }
  }
  if (cdp) cdp.ws.close();
  browser.kill('SIGTERM');
  await Promise.race([once(browser, 'exit'), delay(3000)]);
  if (browser.exitCode === null && browser.signalCode === null) browser.kill('SIGKILL');
  fs.writeFileSync(path.join(out, 'results.json'), JSON.stringify({ tests, exceptions }, null, 2));
}

const failed = tests.filter((t) => !t.ok);
console.log(`UI_CHECK_${failed.length ? 'FAIL' : 'PASS'} ${tests.length - failed.length}/${tests.length}`);
if (failed.length) process.exitCode = 1;
