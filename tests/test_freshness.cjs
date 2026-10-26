const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
const source=fs.readFileSync('site/freshness.js','utf8');
async function run({revision='2026-10-26T09:00',incoming='2026-10-26T09:05',hidden=false,edited=false,account=null,stored=null,fail=false,raceKey=''}={}){
 const handlers={},message={textContent:''},button={textContent:'更新',addEventListener:(n,f)=>handlers.click=f};let reloads=0,requests=0;
 const document={hidden,activeElement:null,getElementById:()=>({dataset:{revision,source:'/freshness.json',key:raceKey},querySelector:q=>q==='button'?button:message}),addEventListener:(n,f)=>handlers[n]=f};
 const storage=new Map(stored?[['teilog_public_refresh:/freshness.json:'+raceKey,stored]]:[]);
 const location={href:'https://teilog.com/race/20261026/kiryu-1',origin:'https://teilog.com',reload:()=>reloads++};
 const state={document,location,URL,AbortController,Date,sessionStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)},window:{TeiNoteAccount:account?{state:()=>account}:null,addEventListener:(n,f)=>handlers[n]=f},setTimeout:()=>1,clearTimeout:()=>{},setInterval:f=>handlers.interval=f,fetch:async(url,options)=>{requests++;assert.equal(options.cache,'no-store');if(fail)throw Error('offline');return {ok:true,json:async()=>({updated_at:'2026-10-26T09:30',races:{'20261026-01-1':incoming},...(raceKey?{}:{updated_at:incoming})})}}};
 if(edited){document.hidden=true;}
 vm.runInNewContext(source,state);
 if(edited){handlers.input({target:{tagName:'TEXTAREA'}});document.hidden=false;handlers.visibilitychange();}
 await new Promise(r=>setImmediate(r));
 return {get reloads(){return reloads},get requests(){return requests},get message(){return message.textContent},handlers,document};
}
(async()=>{
 assert.equal((await run()).reloads,1);
 assert.equal((await run({incoming:'2026-10-26T09:00'})).reloads,0);
 assert.equal((await run({incoming:'2026-10-26T08:55'})).reloads,0);
 assert.equal((await run({raceKey:'20261026-01-1',incoming:'2026-10-26T09:00'})).reloads,0);
 assert.equal((await run({raceKey:'20261026-01-1',incoming:'2026-10-26T09:05'})).reloads,1);
 assert.equal((await run({hidden:true})).requests,0);
 assert.equal((await run({edited:true})).reloads,0);
 assert.equal((await run({stored:'2026-10-26T09:05'})).reloads,0);
 assert.equal((await run({account:{configured:true,ready:true,user:true,mode:'conflict',message:'conflict'}})).reloads,0);
 assert.equal((await run({account:{configured:true,ready:true,user:true,mode:'account',message:'同期待ち'}})).reloads,0);
 assert.equal((await run({account:{configured:true,ready:true,user:true,mode:'account',message:'同期済み'}})).reloads,1);
 const failed=await run({fail:true});assert.equal(failed.reloads,0);assert.match(failed.message,/確認できません/);
 const resumed=await run({hidden:true});resumed.document.hidden=false;resumed.handlers.visibilitychange();await new Promise(r=>setImmediate(r));
 assert.equal(resumed.reloads,1);assert.match(resumed.message,/時点/);
 console.log('Freshness OK: newer public revision only, visibility/resume, no edit/conflict/pending reload, no reload loop, honest network failure.');
})().catch(e=>{console.error(e);process.exitCode=1});
