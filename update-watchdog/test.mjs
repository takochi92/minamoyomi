import assert from 'node:assert/strict';
import {tick, operatingTime} from './src/index.mjs';
const now = new Date('2026-10-27T06:20:00Z');
assert.equal(operatingTime(now),true);
assert.equal(operatingTime(new Date('2026-10-27T18:00:00Z')),false);
await assert.rejects(tick({},now),/missing-dispatch-token/);
const env={UPDATE_DISPATCH_TOKEN:'test-only'};
async function scenario({runs=[],at='2026-10-27T13:46',fail=false,githubStatus=200}={}) {
  const calls=[];
  const request=async(url,options)=>{
    calls.push({url,options});
    if(url.includes('/runs?'))return Response.json({workflow_runs:runs},{status:githubStatus});
    if(url.startsWith('https://teilog.com/')) {
      assert.equal(options.headers,undefined);
      return fail ? new Response('',{status:503}) : Response.json({updated_at:at});
    }
    assert.equal(url,'https://api.github.com/repos/takochi92/minamoyomi/actions/workflows/update.yml/dispatches');
    assert.equal(options.method,'POST');
    assert.deepEqual(JSON.parse(options.body),{ref:'main'});
    return new Response(null,{status:204});
  };
  return {calls,run:()=>tick(env,now,request)};
}
let s=await scenario();assert.equal((await s.run()).state,'dispatched');assert.equal(s.calls.length,3);
s=await scenario({at:'2026-10-27T15:18'});assert.equal((await s.run()).state,'fresh');assert.equal(s.calls.length,2);
for(const status of ['queued','in_progress','pending','waiting']) {
  s=await scenario({runs:[{status}]});assert.equal((await s.run()).state,'update-running');assert.equal(s.calls.length,2);
}
s=await scenario({runs:[{status:'completed',created_at:'2026-10-27T06:18:00Z'}]});assert.equal((await s.run()).state,'backoff');
for(const at of ['bad','2026-10-27T18:00']) {
  s=await scenario({at});await assert.rejects(s.run(),/invalid-freshness/);assert.equal(s.calls.length,1);
}
s=await scenario({fail:true});await assert.rejects(s.run(),/freshness-status-503/);assert.equal(s.calls.length,1);
s=await scenario({runs:[{status:'queued',created_at:'2026-10-27T05:00:00Z'}]});assert.equal((await s.run()).state,'update-stuck');
s=await scenario({at:'2026-10-27T15:14'});assert.equal((await s.run()).state,'dispatched');
s=await scenario({at:'2026-10-27T15:16'});assert.equal((await s.run()).state,'fresh');
s=await scenario({at:'2026-10-27T15:16',runs:[{status:'completed',created_at:'2026-10-27T06:15:00Z'}]});
assert.equal((await s.run()).state,'dispatched','normal cadence is five minutes from the previous start, not five minutes after setup and collection');
s=await scenario({at:'2026-10-27T15:16',runs:[{status:'completed',created_at:'2026-10-27T06:15:01Z'}]});
assert.equal((await s.run()).state,'dispatched','absorb the observed two-second registration delay at the five-minute Cron boundary');
s=await scenario({at:'2026-10-27T15:16',runs:[{status:'completed',created_at:'2026-10-27T06:15:06Z'}]});
assert.equal((await s.run()).state,'backoff','never dispatch before the bounded five-second registration allowance');
for(const githubStatus of [401,403,500]) {
 s=await scenario({githubStatus});await assert.rejects(s.run(),error=>error.message==='github-status-'+githubStatus && error.health.ageMinutes>20);
 assert.equal(s.calls.filter(c=>c.options.method==='POST').length,0);
}
console.log('update watchdog: stale/fresh, active jobs, backoff, hours, fail closed, token isolation passed');
