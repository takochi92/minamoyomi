// Production-generated page + real scripts, mocked login/DB/Push. No external traffic.
const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
(async()=>{const b=await chromium.launch({channel:'msedge',headless:true});try{
const page=await b.newPage({viewport:{width:390,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
await page.addInitScript(()=>{
 const notes={racer:{},motor:{},fav:{'1234':{name:'結合確認用選手'}},bets:[],budget:0};let saved=null,sub=null;
 const reg={pushManager:{getSubscription:async()=>sub,subscribe:async()=>{sub={toJSON:()=>({endpoint:'https://fcm.googleapis.com/fcm/send/integration-test',keys:{}}),unsubscribe:async()=>{sub=null;return true}};return sub;}}};
 Object.defineProperty(navigator,'serviceWorker',{configurable:true,value:{register:async()=>reg,ready:Promise.resolve(reg),getRegistration:async()=>reg}});
 window.Notification={permission:'granted'};window.PushManager=function(){};window.testInvoked=false;
 const client={auth:{onAuthStateChange(){},getSession:async()=>({data:{session:{user:{id:'A'}}}})},
 from:table=>{const q={select(){return q},eq(){return q},maybeSingle:async()=>({data:table==='teilog_notes'?{data:notes,revision:1}:saved})};return q;},
 rpc:async(name,a)=>{if(name!=='teilog_save_push')throw Error('Unexpected RPC');assertOwner(a);saved={id:a.device_id,subscription:a.push_subscription,rules:a.push_rules,enabled:a.turn_on,revision:a.expected_revision+1};return {data:saved.revision};},
 functions:{invoke:async()=>{window.testInvoked=true;return {data:{sent:1}};}}};
 function assertOwner(a){if(a.expected_user_id!=='A')throw Error('Wrong owner');}
 window.supabase={createClient:()=>client};
});
await page.route('**/*',async r=>{
 const u=new URL(r.request().url());if(u.origin!=='https://teilog.com')return r.abort();
 if(u.pathname==='/mynote')return r.fulfill({contentType:'text/html',body:fs.readFileSync('private/morning-push/integration.html')});
 if(u.pathname==='/fav-today.json')return r.fulfill({json:{date:'20261027',racers:{}}});
 const file=path.resolve('site','.'+u.pathname);if(!file.startsWith(path.resolve('site')+path.sep)||!fs.existsSync(file))return r.fulfill({status:404,body:''});
 return r.fulfill({contentType:file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'application/octet-stream',body:fs.readFileSync(file)});
});
await page.goto('https://teilog.com/mynote');
await page.getByRole('checkbox',{name:'結合確認用選手 4号艇',exact:true}).check();
await page.getByRole('button',{name:'この端末の通知をオン',exact:true}).click();
await page.waitForFunction(()=>document.querySelector('#race-notifications').textContent.includes('この端末の通知：オン'));
await page.getByRole('button',{name:'テスト通知を送る',exact:true}).click();await page.waitForFunction(()=>window.testInvoked);
assert.deepEqual(errors,[]);assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
assert.ok(await page.evaluate(()=>!!(document.querySelector('#race-notifications').compareDocumentPosition(document.querySelector('#note-app'))&Node.DOCUMENT_POSITION_FOLLOWING)));
await page.screenshot({path:'private/morning-push/integration-mobile.png',fullPage:true});
console.log('Production HTML + real config/account/note/notification script ordering: login, frame selection, authenticated save and function invocation passed (mocked services).');
}finally{await b.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
