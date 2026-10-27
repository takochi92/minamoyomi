// Real rendering + simulated authentication/PushManager/database. No real push is sent.
const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
const page=await browser.newPage({viewport:{width:390,height:1000}}),errors=[];
page.on('pageerror',e=>errors.push(e.message));
const css=fs.readFileSync('site/style.css','utf8'),js=fs.readFileSync('site/race-notifications.js','utf8');
await page.route('https://teilog.com/**',r=>{
 if(r.request().url().includes('fav-today.json'))return r.fulfill({json:{date:'20261027',racers:{'1234':[['平和島',6,'race/20261027/heiwajima-6.html','13:00',4]]}}});
 return r.fulfill({contentType:'text/html',body:'<!doctype html><html lang="ja"><meta charset="utf-8"><style>'+css+'</style><main><section class="panel" id="race-notifications"></section></main></html>'});
});
await page.goto('https://teilog.com/mynote');
await page.evaluate(()=>{
 window.testUser='A';window.testReady=true;window.calls=[];window.rows={};window.subscribed=false;window.denied=false;window.fail=false;
 window.SITE_CONFIG={notifications:{enabled:true,vapidPublicKey:'BAAAAA'}};
 window.testSub={toJSON:()=>({endpoint:'https://fcm.googleapis.com/test',keys:{}}),unsubscribe:async()=>{window.subscribed=false;return true;}};
 window.testReg={pushManager:{getSubscription:async()=>window.subscribed?window.testSub:null,subscribe:async()=>{window.subscribed=true;return window.testSub;}}};
 Object.defineProperty(navigator,'serviceWorker',{value:{register:async()=>{},ready:Promise.resolve(window.testReg),getRegistration:async()=>window.testReg},configurable:true});
 window.PushManager=function(){};window.Notification={permission:'granted',requestPermission:async()=>window.denied?'denied':'granted'};
 window.TeiNoteAccount={identity:()=>window.testUser,state:()=>({ready:window.testReady,user:!!window.testUser}),data:()=>({fav:window.testUser==='B'?{'5678':{name:'別アカウント'}}:Object.assign({'1234':{name:'確認用選手'}},window.extraFavorites||{})}),subscribe:f=>window.notify=f,
 notificationCall:async(name,args)=>{if(window.fail)throw Error('保存失敗');window.calls.push({name,args});if(name==='read')return window.rows[window.testUser]||null;if(name==='test')return {sent:1};window.rows[window.testUser]={subscription:args.push_subscription,rules:JSON.parse(JSON.stringify(args.push_rules)),enabled:args.turn_on,revision:args.expected_revision+1};return args.expected_revision+1;}};
});
await page.addScriptTag({content:js});
await page.locator('.push-racer-row > summary').filter({hasText:'確認用選手'}).click();
await page.getByRole('checkbox',{name:'確認用選手 4号艇',exact:true}).check();
await page.getByRole('button',{name:'この端末の通知をオン',exact:true}).click();
await page.waitForFunction(()=>document.querySelector('#race-notifications').textContent.includes('この端末の通知：オン'));
assert.deepEqual(await page.evaluate(()=>window.rows.A.rules),{'1234':[4]});
await page.getByRole('button',{name:'テスト通知を送る',exact:true}).click();
await page.waitForFunction(()=>document.querySelector('#race-notifications').textContent.includes('テスト通知を送信しました'));
assert.equal(await page.getByRole('link',{name:/平和島6R 4号艇/}).count(),1);
await page.getByRole('checkbox',{name:'確認用選手 6号艇',exact:true}).check();
await page.getByRole('button',{name:'選んだ枠番を保存',exact:true}).click();
await page.waitForFunction(()=>window.rows.A.rules['1234'].length===2);
await page.getByRole('button',{name:'この端末の通知をオフ',exact:true}).click();
await page.waitForFunction(()=>!window.rows.A.enabled&&!window.subscribed);
await page.evaluate(()=>{window.fail=true});
await page.getByRole('button',{name:'この端末の通知をオン',exact:true}).click();
await page.waitForSelector('[role=alert]');assert.equal(await page.evaluate(()=>window.subscribed),false);
await page.evaluate(()=>{window.fail=false;window.testUser='B';window.notify();});
await page.locator('.push-racer-row > summary').filter({hasText:'別アカウント'}).click();
await page.getByRole('checkbox',{name:'別アカウント 5号艇',exact:true}).check();
assert.equal(await page.getByRole('checkbox',{name:/確認用選手/}).count(),0);
await page.getByRole('button',{name:'この端末の通知をオン',exact:true}).click();
await page.waitForFunction(()=>window.rows.B&&window.rows.B.enabled);
await page.evaluate(()=>window.TeiRaceNotifications.beforeSignOut());
assert.equal(await page.evaluate(()=>window.rows.B.enabled),false);
assert.equal(await page.evaluate(()=>window.subscribed),false);
await page.evaluate(()=>{window.testUser='A';window.extraFavorites=Object.fromEntries(Array.from({length:19},(_,i)=>[String(4000+i),{name:'確認選手'+(i+1)}]));window.notify();});
await page.waitForFunction(()=>document.querySelectorAll('.push-racer-row').length===20);
assert.equal(await page.locator('.push-racer-row[open]').count(),0);
assert.ok(await page.locator('.push-racer-row').evaluateAll(rows=>rows.reduce((s,r)=>s+r.getBoundingClientRect().height,0)<1300));
await page.screenshot({path:'private/morning-push/20-favorites-folded.png',fullPage:true});
await page.locator('.push-racer-row > summary').first().click();
await page.getByRole('checkbox',{name:'確認用選手 3号艇',exact:true}).check();
assert.equal(await page.locator('.push-racer-row[open]').count(),1);
assert.match(await page.locator('.push-racer-row > summary').first().textContent(),/3・4・6号艇/);
for(const width of [320,390]){await page.setViewportSize({width,height:1000});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));}
assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
fs.mkdirSync('private/morning-push',{recursive:true});
await page.screenshot({path:'private/morning-push/mobile-settings.png',fullPage:true});
await page.evaluate(()=>{window.SITE_CONFIG.notifications.enabled=false;});
assert.deepEqual(errors,[]);
console.log('Edge: per-racer frames, opt-in/off, save, failed enrollment cleanup, account isolation, logout subscription removal, mobile layout passed (simulated backend).');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
