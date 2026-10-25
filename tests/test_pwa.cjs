const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
const manifest=JSON.parse(fs.readFileSync('site/manifest.webmanifest','utf8'));
assert.equal(manifest.id,'/');assert.equal(manifest.start_url,'/');assert.equal(manifest.scope,'/');
assert.equal(manifest.display,'standalone');
for(const size of ['192x192','512x512'])assert(manifest.icons.some(i=>i.sizes===size&&fs.existsSync('site'+i.src)));
assert(manifest.icons.some(i=>i.purpose==='maskable'));
const events={},cached=[],deleted=[],network=[];
const cache={add:async request=>cached.push(request.url),match:async()=>new Response('offline explanation')};
const self={location:{origin:'https://teilog.com'},addEventListener:(name,handler)=>events[name]=handler,skipWaiting:async()=>{},clients:{claim:async()=>{}}};
// Node's Request requires an absolute URL; browser Request resolves against SW.
const BrowserRequest=class extends Request{constructor(url,options){super(new URL(url,'https://teilog.com'),options)}};
// Run in an isolated context with browser-relative Request behavior.
// All cache writes and response policies are checked; no real notes are used.
vm.runInNewContext(fs.readFileSync('site/sw.js','utf8'),{self,URL,Request:BrowserRequest,Response,caches:{open:async()=>cache,keys:async()=>['unrelated-cache','teilog-pwa-offline-old','teilog-pwa-offline-v2'],delete:async key=>deleted.push(key)},
fetch:async(request,options)=>{network.push({url:request.url,options});if(request.url.includes('offline-test'))throw Error('offline');return new Response('fresh race');}});
async function navigation(path){let response;events.fetch({request:{url:'https://teilog.com'+path,method:'GET',mode:'navigate',headers:new Headers()},respondWith:r=>response=r});return response&&await response;}
(async()=>{
  let promise;events.install({waitUntil:p=>promise=p});await promise;
  assert.deepEqual(cached,['https://teilog.com/offline']);
  events.activate({waitUntil:p=>promise=p});await promise;
  assert.deepEqual(deleted,['teilog-pwa-offline-old']);
  assert.equal(await navigation('/mynote'),undefined);
  assert.equal(await navigation('/mynote.html'),undefined);
  assert.equal(await navigation('/mynote?code=private-code'),undefined);
  assert.equal(await navigation('/?code=private-code'),undefined);
  assert.equal(await navigation('/?error=access_denied'),undefined);
  assert.equal(await navigation('/mynote/'),undefined);
  for(const request of [
    {url:'https://teilog.com/race/test',method:'POST',mode:'navigate',headers:new Headers()},
    {url:'https://teilog.com/race/test',method:'GET',mode:'navigate',headers:new Headers({Authorization:'Bearer test-only'})},
    {url:'https://other.example/race/test',method:'GET',mode:'navigate',headers:new Headers()}
  ]){let intercepted=false;events.fetch({request,respondWith:()=>intercepted=true});assert.equal(intercepted,false);}
  for(const url of ['https://teilog.com/data/race.json','https://example.supabase.co/rest/v1/teilog_notes']){
    let intercepted=false;events.fetch({request:{url,method:'GET',mode:'cors',headers:new Headers()},respondWith:()=>intercepted=true});assert.equal(intercepted,false);
  }
  assert.equal(await (await navigation('/race/20261026/example-1')).text(),'fresh race');
  assert.equal(network[0].options.cache,'no-store');
  assert.equal(await (await navigation('/offline-test')).text(),'offline explanation');
  assert.equal(cached.length,1);
  console.log('PWA OK: stable app identity, icons, network-only navigation, no private/API interception, offline explanation only, scoped cache cleanup.');
})().catch(e=>{console.error(e);process.exitCode=1});
