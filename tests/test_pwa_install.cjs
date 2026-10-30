const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
const source=fs.readFileSync('site/pwa.js','utf8');
function runtime(options={}){
  const winEvents={},docEvents={},timers=new Map(),local=options.local||new Map(),session=options.session||new Map(),assigned=[];
  let now=options.now||1800000000000,id=0,banner=null;
  class Element{
    constructor(tag='DIV'){this.tagName=tag;this.handlers={};this.hidden=false;this.style={};this.children={};this.classList={add:()=>{}};}
    addEventListener(name,fn){(this.handlers[name]||=([])).push(fn);}
    fire(name){const event={preventDefault(){this.prevented=true;}};for(const f of this.handlers[name]||[])f(event);return event;}
    setAttribute(name,value){this[name]=value;}
    set innerHTML(value){this.html=value;for(const name of ['.pwa-install-action','.pwa-install-close']){const child=new Element(name.endsWith('action')?'A':'BUTTON');child.parent=this;this.children[name]=child;}}
    querySelector(name){return this.children[name];}
    contains(el){return el===this||el.parent===this;}
    remove(){if(banner===this)banner=null;}
  }
  const button=new Element('BUTTON'),status=new Element(),body=new Element('BODY');button.hidden=true;
  const document={hidden:false,activeElement:body,body:{appendChild(el){banner=el;}},
    createElement:tag=>new Element(tag.toUpperCase()),getElementById:name=>options.installPage?(name==='install-app'?button:status):null,
    querySelector:q=>q==='.top'?{getBoundingClientRect:()=>({bottom:64})}:options.modal?{}:null,
    addEventListener:(n,f)=>(docEvents[n]||=[]).push(f)};
  const storage=map=>({getItem:k=>{if(options.blockedStorage)throw Error('blocked');return map.get(k)||null;},setItem:(k,v)=>{if(options.blockedStorage)throw Error('blocked');map.set(k,String(v));}});
  const mode={matches:!!options.standalone,addEventListener:(n,f)=>mode.change=f};
  const location={origin:options.origin||'https://teilog.com',href:'https://teilog.com'+(options.path||'/'),assign:url=>assigned.push(url)};
  const window={matchMedia:()=>mode,localStorage:storage(local),sessionStorage:storage(session),addEventListener:(n,f)=>(winEvents[n]||=[]).push(f)};
  const navigator={userAgent:options.ua||'Mozilla/5.0 (iPhone)',standalone:options.iosStandalone,maxTouchPoints:options.touch||0};
  const Clock=class extends Date{static now(){return now;}};
  vm.runInNewContext(source,{window,document,navigator,location,URL,Date:Clock,setTimeout:(fn,ms)=>{const key=++id;timers.set(key,{fn,at:now+ms});return key;},clearTimeout:key=>timers.delete(key),requestAnimationFrame:fn=>fn()});
  return {local,session,assigned,document,button,status,mode,Element,get banner(){return banner;},get now(){return now;},
    win:(name,event={})=>{for(const f of winEvents[name]||[])f(event);},doc:(name,event={})=>{for(const f of docEvents[name]||[])f(event);},
    tick(ms){const end=now+ms;let next;while((next=[...timers].filter(([,v])=>v.at<=end).sort((a,b)=>a[1].at-b[1].at)[0])){timers.delete(next[0]);now=next[1].at;next[1].fn();}now=end;}};
}
const flush=async()=>{for(let i=0;i<8;i++)await Promise.resolve();};
function native(env,outcome='dismissed',failure=false){let calls=0,prevented=false;env.win('beforeinstallprompt',{preventDefault(){prevented=true;},prompt(){calls++;if(failure)throw Error('not allowed');return Promise.resolve();},userChoice:Promise.resolve({outcome})});return {get calls(){return calls;},get prevented(){return prevented;}};}
(async()=>{
  let e=runtime({ua:'Desktop'});e.tick(3000);assert.equal(e.banner,null);
  e=runtime();e.tick(2799);assert.equal(e.banner,null);e.tick(1);assert.ok(e.banner);assert.equal(e.banner.style.top,'72px');assert.equal(e.banner.querySelector('.pwa-install-action').textContent,'追加方法');
  e.banner.querySelector('.pwa-install-close').fire('click');assert.equal(e.banner,null);assert.ok(Number(e.local.get('teilog_install_later_v1'))>=e.now+30*86400000);
  let next=runtime({local:e.local,now:e.now});next.tick(3000);assert.equal(next.banner,null);
  next=runtime({local:e.local,now:e.now+31*86400000});next.tick(3000);assert.ok(next.banner);
  e=runtime();e.tick(3000);e.banner.querySelector('.pwa-install-action').fire('click');assert.deepEqual(e.assigned,['/install']);assert.equal(e.banner,null);
  e=runtime({ua:'Android'});let n=native(e);assert.ok(n.prevented);e.tick(3000);assert.equal(n.calls,0);assert.equal(e.banner.querySelector('.pwa-install-action').textContent,'追加する');e.banner.querySelector('.pwa-install-action').fire('click');assert.equal(n.calls,1);await flush();assert.equal(e.banner,null);assert.ok(Number(e.local.get('teilog_install_later_v1'))>e.now);
  e=runtime();e.tick(3000);const first=e.banner;n=native(e,'accepted');assert.equal(e.banner,first);assert.equal(e.banner.querySelector('.pwa-install-action').textContent,'追加する');e.banner.querySelector('.pwa-install-action').fire('click');await flush();assert.equal(e.local.get('teilog_installed_v1'),'0');e.win('appinstalled');assert.equal(e.local.get('teilog_installed_v1'),'1');assert.equal(e.banner,null);
  next=runtime({local:e.local});next.tick(3000);assert.equal(next.banner,null);
  for(const options of [{standalone:true},{iosStandalone:true},{path:'/install'},{path:'/install.html'},{path:'/offline'},{path:'/?code=synthetic'},{path:'/#access_token=synthetic'},{path:'/?error=synthetic'},{origin:'https://example.com'}]){e=runtime(options);e.tick(3000);assert.equal(e.banner,null,JSON.stringify(options));}
  e=runtime({installPage:true,path:'/install'});n=native(e,'accepted');assert.equal(e.button.hidden,false);e.tick(3000);assert.equal(e.banner,null);e.button.fire('click');await flush();assert.equal(n.calls,1);assert.ok(e.status.textContent.includes('追加が完了したら'));e.win('appinstalled');assert.ok(e.status.textContent.includes('追加しました'));
  e=runtime({blockedStorage:true});e.tick(3000);assert.ok(e.banner);e.banner.querySelector('.pwa-install-close').fire('click');native(e);e.tick(3000);assert.equal(e.banner,null);
  e=runtime();e.document.activeElement=new e.Element('INPUT');e.tick(3000);assert.equal(e.banner,null);e.document.activeElement=new e.Element('BODY');e.doc('focusout');e.tick(3000);assert.ok(e.banner);e.document.activeElement=new e.Element('TEXTAREA');e.doc('focusin');assert.equal(e.banner,null);
  e=runtime();e.document.hidden=true;e.tick(3000);assert.equal(e.banner,null);e.document.hidden=false;e.doc('visibilitychange');e.tick(3000);assert.ok(e.banner);e.mode.matches=true;e.mode.change();assert.equal(e.banner,null);assert.equal(e.local.get('teilog_installed_v1'),'1');
  e=runtime({modal:true});e.tick(3000);assert.equal(e.banner,null);
  e=runtime({ua:'Desktop'});n=native(e);e.tick(3000);assert.ok(e.banner);
  e=runtime();n=native(e,'dismissed',true);e.tick(3000);e.banner.querySelector('.pwa-install-action').fire('click');await flush();assert.equal(n.calls,1);assert.deepEqual(e.assigned,['/install']);
  e=runtime();e.tick(3000);next=runtime({session:e.session});next.tick(3000);assert.equal(next.banner,null);
  console.log('PWA promotion OK: user gesture only, guide fallback, 30-day dismissal, app/standalone suppression, edit/auth/modal guards, session limits, blocked storage, and existing install page.');
})().catch(e=>{console.error(e);process.exitCode=1});
