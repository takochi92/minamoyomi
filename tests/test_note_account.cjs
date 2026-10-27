// Browser-independent account-state tests. These do not replace real RLS tests.
const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const M=require('../site/note-store.js');
const source=fs.readFileSync(require.resolve('../site/note-account.js'),'utf8');
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function until(f){for(let i=0;i<250;i++){if(f())return;await sleep(4)}throw Error('State transition timed out');}
function harness({account=true,uid='A',guest=M.empty(),verificationOnly=false,checkQuery=false,checkSession=false}={}) {
  const backing=new Map([['teilog_note_v1',JSON.stringify(guest)]]),cloud=new Map(),events={},docEvents={},writes=[];
  let current=uid,callback,offline=false,delayed=null,writeDelay=null,writeStarted=false;
  const storage={get length(){return backing.size},key:i=>[...backing.keys()][i],getItem:k=>backing.get(k)||null,setItem:(k,v)=>backing.set(k,String(v)),removeItem:k=>backing.delete(k)};
  const client={auth:{onAuthStateChange:f=>{callback=f},getSession:async()=>({data:{session:current?{user:{id:current,email:current+'@example.test'}}:null}})},
    from:()=>({select:fields=>({eq:(field,id)=>({maybeSingle:async()=>{if(offline)throw Error('offline');if(delayed)await delayed;
      const row=cloud.get(id);return {data:id===current&&row?(fields==='revision'?{revision:row.revision}:M.copy(row)):null};}})})}),
    rpc:async(name,args)=>{if(offline)throw Error('offline');writeStarted=true;if(writeDelay)await writeDelay;
      // Mirrors the expected-user guard, but only a live DB test proves RLS.
      if(args.expected_user_id!==current)return {error:{code:'28000'}};
      const row=cloud.get(current),rev=row?row.revision:0;
      if(args.expected_revision!==rev)return {error:{code:'40001'}};
      cloud.set(current,{revision:rev+1,data:M.copy(args.note_data)});writes.push(current);return {data:rev+1};}
  };
  const window={SITE_CONFIG:{account:account?{url:'https://test.supabase.co',publishableKey:'sb_publishable_test',verificationOnly}:{}},TeiNoteModel:M,supabase:{createClient:()=>client},addEventListener:(n,f)=>{events[n]=f}};
  const document={readyState:'loading',hidden:false,getElementById:()=>null,addEventListener:(n,f)=>{docEvents[n]=f}};
  const sessionBacking=new Map(checkSession?[['teilog_note_check_v1','1']]:[]);
  const sessionStorage={getItem:k=>sessionBacking.get(k)||null,setItem:(k,v)=>sessionBacking.set(k,String(v))};
  const context={window,document,location:{origin:'https://teilog.com',href:'https://teilog.com/mynote'+(checkQuery?'?note-sync-check=1':'')},sessionStorage,localStorage:storage,crypto,URL,Blob,TextEncoder,atob,setTimeout:(f,ms)=>setTimeout(f,ms===900?5:ms),clearTimeout,setInterval:()=>0,confirm:()=>false};
  vm.runInNewContext(source,context);
  return {api:window.TeiNoteAccount,cloud,backing,writes,async init(){await docEvents.DOMContentLoaded()},switch(id){current=id;callback('SIGNED_IN',id?{user:{id,email:id+'@example.test'}}:null)},offline(v){offline=v},delay(p){delayed=p},delayWrite(p){writeDelay=p},writeStarted:()=>writeStarted,events};
}
(async()=>{
  const guest=M.empty();guest.racer['1234']={name:'端末内',text:'ゲストのメモ'};
  let h=harness({account:false,guest});await h.init();
  let next=h.api.data();next.budget=10000;h.api.save(h.api.data(),next);
  assert.equal(JSON.parse(h.backing.get('teilog_note_v1')).budget,10000);
  assert.equal(h.writes.length,0);

  // Live verification stays hidden on ordinary visits and survives the OAuth
  // redirect only in a tab where the owner explicitly opened the check link.
  h=harness({verificationOnly:true});await h.init();assert.equal(h.api.state().configured,false);
  h=harness({verificationOnly:true,checkQuery:true});await h.init();await until(()=>h.api.state().ready);assert.equal(h.api.state().configured,true);
  h=harness({verificationOnly:true,checkSession:true});await h.init();await until(()=>h.api.state().ready);assert.equal(h.api.state().configured,true);

  // Logging in never uploads guest data automatically.
  h=harness({guest});await h.init();await until(()=>h.api.state().ready);
  assert.equal(h.api.state().user,true);assert.deepEqual(h.api.data(),M.empty());assert.equal(h.writes.length,0);
  next=h.api.data();next.racer['2345']={name:'本人',text:'アカウントAのメモ'};
  h.api.save(h.api.data(),next);await until(()=>h.cloud.has('A'));
  assert.equal(h.cloud.get('A').data.racer['2345'].text,'アカウントAのメモ');
  assert.equal(JSON.parse(h.backing.get('teilog_note_v1')).racer['1234'].text,'ゲストのメモ');

  // Sign-out and account switch clear the old account view immediately.
  h.switch(null);await until(()=>!h.api.state().user);
  assert.equal(h.api.data().racer['1234'].text,'ゲストのメモ');assert.equal(h.api.data().racer['2345'],undefined);
  h.switch('B');await until(()=>h.api.state().user&&h.api.state().ready);
  assert.deepEqual(h.api.data(),M.empty());assert.equal(h.cloud.has('B'),false);

  // Offline edits stay pending under A; B never receives or renders them.
  h.switch('A');await until(()=>h.api.state().ready&&h.api.data().racer['2345']);h.offline(true);
  next=h.api.data();next.racer['2345'].text='オフラインの変更';h.api.save(h.api.data(),next);
  await until(()=>h.api.state().mode==='error');
  assert([...h.backing.keys()].some(k=>k.startsWith('teilog_note_pending_v1:A:')));
  h.offline(false);h.switch('B');await until(()=>h.api.state().ready&&h.api.data().racer['2345']===undefined);
  assert.equal(h.cloud.has('B'),false);
  h.switch('A');await until(()=>h.cloud.get('A').data.racer['2345'].text==='オフラインの変更');
  assert.equal(h.writes.includes('B'),false);

  // An in-flight read for A may resolve after switching to B. It must be ignored.
  let release;const blocked=new Promise(r=>release=r);h=harness();h.delay(blocked);
  const init=h.init();await sleep(8);h.delay(null);h.switch('B');await until(()=>h.api.state().ready);
  release();await init;await sleep(8);assert.deepEqual(h.api.data(),M.empty());assert.equal(h.writes.length,0);

  // A's payload must not be saved under B if the SDK obtains B's token after an
  // account switch. Both the backend expected-user guard and frontend generation
  // guard are needed; ignoring the final response alone is not sufficient.
  h=harness();await h.init();await until(()=>h.api.state().ready);
  let releaseWrite;h.delayWrite(new Promise(r=>releaseWrite=r));
  next=h.api.data();next.racer['3456']={text:'Aだけの非公開メモ'};h.api.save(h.api.data(),next);
  await until(()=>h.writeStarted());h.switch('B');await until(()=>h.api.state().ready&&!h.api.data().racer['3456']);
  releaseWrite();await sleep(12);assert.equal(h.cloud.has('B'),false);assert.equal(h.writes.length,0);
  h.switch('A');await until(()=>h.cloud.has('A'));assert.equal(h.cloud.get('A').data.racer['3456'].text,'Aだけの非公開メモ');

  h=harness();await h.init();await until(()=>h.api.state().ready);
  next=h.api.data();next.motor['03-36']={jcd:'03',no:'36',venue:'江戸川',favorite:true};
  h.api.save(h.api.data(),next);await until(()=>h.cloud.has('A'));
  assert.equal(h.cloud.get('A').data.motor['03-36'].favorite,true);
  h.switch('B');await until(()=>h.api.state().ready&&!h.api.data().motor['03-36']);
  h.switch('A');await until(()=>h.api.state().ready&&h.api.data().motor['03-36']);
  assert.equal(h.api.data().motor['03-36'].favorite,true);

  // Old/malformed guest storage is never silently replaced with an empty note.
  h=harness({account:false});h.backing.set('teilog_note_v1','broken');
  // Construct a fresh harness with a shape the normalizer rejects.
  h=harness({account:false,guest:{bets:[{id:'b',date:'20261025',inv:-1}]}});
  await h.init();assert.equal(h.api.state().ready,false);
  assert.throws(()=>h.api.save(M.empty(),M.empty()));
  console.log('Account state OK: guest preservation, no automatic import, login/logout isolation, offline retry, stale response isolation, malformed storage guard.');
})().catch(e=>{console.error(e);process.exitCode=1});
