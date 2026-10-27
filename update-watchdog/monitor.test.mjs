import assert from 'node:assert/strict';
import {monitorCheck,safeFailure,UpdateMonitor} from './src/monitor.mjs';
import worker from './src/index.mjs';
import {preflight} from './preflight.mjs';
const now=new Date('2026-10-27T06:20:00Z');
const env={DISPATCH_TOKEN_EXPIRES_ON:'2027-01-25',ADMIN_ALERTS_ENABLED:'true',ADMIN_ALERT_TOPIC:'test-topic',UPDATE_DISPATCH_TOKEN:'test-secret'};
function storage(){let value;return {get:async()=>structuredClone(value),put:async(_key,v)=>{value=structuredClone(v)},value:()=>value};}
let store=storage(),sent=[];
const request=async(url,options)=>{assert.equal(url,'https://ntfy.sh/');sent.push(JSON.parse(options.body));return new Response('',{status:200});};
const healthy=async()=>({state:'fresh',updated_at:'2026-10-27T15:18',ageMinutes:2});
const auth=async()=>{throw new Error('github-status-401');};
let result=await monitorCheck(store,env,now,request,auth);
assert.equal(result.unhealthy,true);assert.equal(sent.length,1);assert.equal(result.state.alertDelivery,'sent');
await monitorCheck(store,env,now,request,auth);assert.equal(sent.length,1,'one outage alert per JST day');
const tomorrow=new Date(now.getTime()+86400_000);
await monitorCheck(store,env,tomorrow,request,auth);assert.equal(sent.length,2);
assert.ok(!JSON.stringify(store.value()).includes('test-topic'));assert.ok(!JSON.stringify(store.value()).includes('test-secret'));
for(const payload of sent){assert.ok(!JSON.stringify(payload).includes('test-secret'));assert.ok(payload.message.includes('認証'));}
store=storage();sent=[];
const unsafe=async()=>{throw new Error('bearer test-secret endpoint test-topic');};
result=await monitorCheck(store,env,now,request,unsafe);assert.equal(sent.length,0);
result=await monitorCheck(store,env,now,request,unsafe);assert.equal(sent.length,1);
assert.equal(safeFailure(new Error('bearer test-secret')),'request-failed');
assert.ok(!JSON.stringify(store.value()).includes('test-secret'));
store=storage();sent=[];
for(const days of [14,13,7,6,1,0]) {
 const at=new Date('2027-01-25T06:00:00Z');at.setUTCDate(at.getUTCDate()-days);
 await monitorCheck(store,env,at,request,healthy);
}
assert.equal(sent.length,3,'warnings at 14/7/1 day stages, not every minute');
store=storage();sent=[];
await monitorCheck(store,env,now,request,async()=>({state:'update-stuck',ageMinutes:30}));assert.equal(sent.length,1);
store=storage();sent=[];
await monitorCheck(store,env,now,request,async()=>({state:'update-running',ageMinutes:21}));assert.equal(sent.length,1);
store=storage();sent=[];
await monitorCheck(store,{...env,ADMIN_ALERTS_ENABLED:'false'},now,request,auth);assert.equal(sent.length,0);
await monitorCheck(store,{...env,ADMIN_ALERT_TEST_ID:'123'},now,request,healthy);assert.equal(sent.length,1);
await monitorCheck(store,{...env,ADMIN_ALERT_TEST_ID:'123'},now,request,healthy);assert.equal(sent.length,1);
store=storage();let attempts=0;
const uncertain=async()=>{attempts++;throw new Error('transport failed');};
await monitorCheck(store,env,now,uncertain,auth);await monitorCheck(store,env,now,uncertain,auth);assert.equal(attempts,1);
assert.equal(store.value().alertDelivery,'unknown','retain bounded delivery status without raw transport errors');
const fakeDO=new UpdateMonitor({storage:storage()},env);
assert.equal((await fakeDO.fetch(new Request('https://internal/check'))).status,404);
let pending;
await worker.scheduled({}, {UPDATE_MONITOR:{idFromName:()=>'',get:()=>({fetch:async()=>new Response('',{status:503})})}}, {waitUntil:p=>{pending=p}});
await assert.rejects(pending,/race-update-watchdog-failed/);
assert.equal((await worker.fetch(new Request('https://example.com/'))).status,404);
store=storage();sent=[];
result=await monitorCheck(store,{...env,DISPATCH_TOKEN_EXPIRES_ON:'2027-02-31'},now,request,healthy);
assert.equal(result.unhealthy,true);assert.equal(sent.length,1);
// Concurrent deliveries share one in-flight check, not three dispatch attempts.
const originalFetch=globalThis.fetch;let reads=0;
try {
 const at=new Date(Date.now()+9*3600_000-120_000).toISOString().slice(0,16);
 globalThis.fetch=async(url)=>{reads++;return url.startsWith('https://teilog.com/')
  ? Response.json({updated_at:at}) : Response.json({workflow_runs:[]});};
 const instance=new UpdateMonitor({storage:storage()},{...env,ADMIN_ALERTS_ENABLED:'false'});
 const responses=await Promise.all([1,2,3].map(()=>instance.fetch(new Request('https://internal/check',{method:'POST'}))));
 assert.equal(reads,2);for(const response of responses)assert.equal(response.status,200);
} finally {globalThis.fetch=originalFetch;}
for(const status of [401,403]) await assert.rejects(preflight('never-print',async()=>new Response('',{status})),new RegExp('dispatch-token-check-'+status));
await assert.rejects(preflight('never-print',async()=>new Response('',{headers:{'github-authentication-token-expiration':'2000-01-01T00:00:00Z'}})),/expires-too-soon/);
assert.equal((await preflight('never-print',async()=>new Response('',{headers:{'github-authentication-token-expiration':'2099-01-01T00:00:00Z'}}))).tokenExpiresOn,'2099-01-01');
console.log('monitor: authentication, stale/stuck updates, expiry stages, deduplication, transport ambiguity, secret isolation, Cron failure propagation passed');
