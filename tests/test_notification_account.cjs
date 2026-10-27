const assert=require('node:assert/strict'),vm=require('vm'),fs=require('fs'),crypto=require('crypto');
const M=require('../site/note-store.js');
let uid='A',callback,delay=null,lastArgs,reads=[];
const client={auth:{onAuthStateChange:f=>callback=f,getSession:async()=>({data:{session:{user:{id:'A'}}}})},
 from:table=>{const q={select(){return q},eq(k,v){reads.push([table,k,v]);return q},async maybeSingle(){if(table==='teilog_push_devices'&&delay)await delay;return {data:table==='teilog_push_devices'?{id:'device',rules:{'1234':[4]}}:null}}};return q},
 rpc:async(name,args)=>{lastArgs=args;return {data:2}}};
const storage=new Map(),events={};
const window={SITE_CONFIG:{account:{url:'https://test.supabase.co',publishableKey:'sb_publishable_test'}},TeiNoteModel:M,supabase:{createClient:()=>client},addEventListener(){}};
const ctx={window,document:{readyState:'loading',hidden:false,getElementById:()=>null,addEventListener:(n,f)=>events[n]=f},
 location:{origin:'https://teilog.com'},localStorage:{get length(){return storage.size},getItem:k=>storage.get(k)||null,key:i=>[...storage.keys()][i],setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},
 setTimeout,clearTimeout,setInterval:()=>0,TextEncoder,URL,crypto};
vm.runInNewContext(fs.readFileSync('site/note-account.js','utf8'),ctx);
const tick=()=>new Promise(r=>setTimeout(r,10));
(async()=>{
 await events.DOMContentLoaded();await tick();const a=window.TeiNoteAccount;
 assert.equal(a.identity(),'A');await a.notificationCall('save',{expected_user_id:'B',expected_revision:1});
 assert.equal(lastArgs.expected_user_id,'A','Caller cannot choose another owner');
 await a.notificationCall('read',{device_id:'device'});
 assert.ok(reads.some(x=>x[0]==='teilog_push_devices'&&x[1]==='user_id'&&x[2]==='A'));
 assert.ok(reads.some(x=>x[1]==='id'&&x[2]==='device'));
 let release;delay=new Promise(r=>release=r);const old=a.notificationCall('read',{device_id:'device'});
 callback('SIGNED_IN',{user:{id:'B'}});await tick();release();
 await assert.rejects(old,/ログイン状態が変わりました/);
 callback('SIGNED_OUT',null);await tick();await assert.rejects(a.notificationCall('save',{}),/ログイン/);
 assert.equal(a.identity(),null);
 console.log('Notification account: owner binding, filtered read, stale identity response rejected, logged-out writes rejected');
})().catch(e=>{console.error(e);process.exitCode=1;});
