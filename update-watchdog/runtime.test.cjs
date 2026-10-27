const assert=require('node:assert/strict'),path=require('node:path');
const {Miniflare,Response}=require(process.env.MINIFLARE_MODULE || 'miniflare');
const {buildSync}=require(process.env.ESBUILD_MODULE || 'esbuild');
const built=buildSync({entryPoints:[path.resolve(__dirname,'src/index.mjs')],bundle:true,format:'esm',write:false}).outputFiles[0].text;
// A fixed operating-hour clock makes the exact same test work at night in CI.
const script=`const RealDate=Date;globalThis.Date=class extends RealDate{constructor(...a){super(...(a.length?a:['2026-10-27T06:20:00Z']));}static now(){return 1793082000000;}};\n`+built;
(async()=>{
let mode='fresh',dispatches=0,notifications=0;
const mf=new Miniflare({modules:true,script,compatibilityDate:'2026-04-12',
 bindings:{UPDATE_DISPATCH_TOKEN:'test-secret',ADMIN_ALERTS_ENABLED:'true',ADMIN_ALERT_TOPIC:'test-topic',ADMIN_ALERT_TEST_ID:'123',DISPATCH_TOKEN_EXPIRES_ON:'2027-01-25'},
 durableObjects:{UPDATE_MONITOR:{className:'UpdateMonitor',useSQLite:true}},
 outboundService:async request=>{
  const url=new URL(request.url);
  if(url.hostname==='teilog.com') {assert.equal(request.headers.get('Authorization'),null);return Response.json({updated_at:mode==='fresh'?'2026-10-27T15:18':'2026-10-27T15:10'});}
  if(url.hostname==='api.github.com') {
   assert.equal(request.headers.get('Authorization'),'Bearer test-secret');
   if(mode==='auth-failure')return new Response('',{status:401});
   if(request.method==='POST'){dispatches++;return new Response(null,{status:204});}
   return Response.json({workflow_runs:[]});
  }
  assert.equal(url.hostname,'ntfy.sh');assert.equal(request.headers.get('Authorization'),null);
  const body=await request.json();assert.equal(body.topic,'test-topic');assert.ok(!JSON.stringify(body).includes('test-secret'));
  notifications++;return Response.json({id:'test-only'});
 },
});
try{
 const namespace=await mf.getDurableObjectNamespace('UPDATE_MONITOR');const stub=namespace.get(namespace.idFromName('race-updates'));
 const check=async()=>{const response=await stub.fetch('https://internal/check',{method:'POST'});return {status:response.status,body:await response.json()}};
 assert.equal((await check()).body.state,'fresh');assert.equal(notifications,1);
 await check();assert.equal(notifications,1,'test notification is not repeated');
 mode='stale';assert.equal((await check()).body.state,'dispatched');assert.equal(dispatches,1);
 mode='auth-failure';assert.equal((await check()).status,503);assert.equal(notifications,2,'one authentication alert');
 await check();assert.equal(notifications,2);
 const state=await (await stub.fetch('https://internal/status')).json();assert.equal(state.alertDelivery,'sent');assert.equal(state.alertHttpStatus,200);
 const publicResponse=await mf.dispatchFetch('https://example.com/health');assert.equal(publicResponse.status,401);
 const health=await mf.dispatchFetch('https://example.com/health',{headers:{Authorization:'Bearer test-secret'}});
 const text=await health.text();assert.equal(health.status,200);assert.ok(!text.includes('test-secret'));assert.ok(!text.includes('test-topic'));
 console.log('workerd runtime: public freshness, GitHub dispatch, ntfy accepted, duplicate suppression, authentication failures and protected diagnostics passed');
}finally{await mf.dispose();}
})().catch(error=>{console.error(error);process.exitCode=1});
