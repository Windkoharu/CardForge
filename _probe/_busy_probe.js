const sleep=ms=>new Promise(r=>setTimeout(r,ms)); const fs=require('fs');
(async()=>{
 const list=await (await fetch('http://127.0.0.1:9333/json/list')).json();
 const page=list.find(t=>t.type==='page'); const ws=new WebSocket(page.webSocketDebuggerUrl);
 let id=0; const pend=new Map();
 const send=(m,p={})=>new Promise((res,rej)=>{const i=++id;pend.set(i,{res,rej});ws.send(JSON.stringify({id:i,method:m,params:p}));});
 await new Promise((r,j)=>{ws.onopen=r;ws.onerror=j;});
 ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id&&pend.has(m.id)){const{res,rej}=pend.get(m.id);pend.delete(m.id);m.error?rej(new Error(JSON.stringify(m.error))):res(m.result);}};
 const ev=async x=>{const r=await send('Runtime.evaluate',{expression:x,returnByValue:true,awaitPromise:true});
   return r.exceptionDetails?('EXC:'+(r.exceptionDetails.exception?.description||'')):r.result?.value;};
 await send('Page.enable');await send('Runtime.enable');
 await send('Emulation.setDeviceMetricsOverride',{width:1440,height:900,deviceScaleFactor:2,mobile:false});
 await send('Page.navigate',{url:'http://127.0.0.1:8790'});
 await sleep(2500);
 for(let i=0;i<45;i++){if(await ev("document.querySelector('.boot-overlay')?'b':'r'")==='r')break;await sleep(700);}
 await sleep(1500);
 // 打开抽屉
 await ev("document.querySelector('#btn-assistant').click()");
 await sleep(1500);
 // 劫持 fetch：让 /api/assistant/chat 延迟 4 秒，模拟慢 LLM
 await ev(`(()=>{const of=window.fetch;window.fetch=(u,o)=>{const s=String(u);
   if(s.includes('/api/assistant/chat')) return new Promise(r=>setTimeout(()=>r(of(u,o)),4000));
   return of(u,o);};return 'hijacked'})()`);
 await ev(`(()=>{const i=document.querySelector('#chat-text');i.value='这张卡的打点合不合理？';
   document.querySelector('#chat-form').dispatchEvent(new Event('submit',{cancelable:true,bubbles:true}));return 'sent'})()`);
 await sleep(700);
 console.log('慢请求中 —— 输入禁用:', await ev("document.querySelector('#chat-text').disabled"));
 console.log('            发送键文案:', await ev("document.querySelector('#chat-form button[type=submit]').textContent"));
 console.log('            按钮 class:', await ev("document.querySelector('#chat-form button[type=submit]').className"));
 console.log('            思考中气泡:', await ev("!!document.querySelector('#chat-log .msg.thinking')"));
 console.log('            聊天区 is-busy:', await ev("document.querySelector('#chat-log').classList.contains('is-busy')"));
 const s=await send('Page.captureScreenshot',{format:'png'});
 fs.writeFileSync('_probe/ui_chat_8_busy_real.png',Buffer.from(s.data,'base64'));
 console.log('  saved _probe/ui_chat_8_busy_real.png');
 // 测试「停止」
 await ev("document.querySelector('#chat-form button[type=submit]').click()");
 await sleep(900);
 console.log('点停止后 —— 输入禁用:', await ev("document.querySelector('#chat-text').disabled"));
 console.log('          末条气泡:', await ev("(()=>{const b=[...document.querySelectorAll('#chat-log .msg.bot .body')];return (b[b.length-1]||{}).textContent})()"));
 ws.close();process.exit(0);
})().catch(e=>{console.error('ERR',e.message);process.exit(1)});
