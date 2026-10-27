import assert from 'node:assert/strict';
import {tick, operatingTime} from './src/index.mjs';
const now = new Date('2026-10-27T06:20:00Z');
assert.equal(operatingTime(now),true);
assert.equal(operatingTime(new Date('2026-10-27T18:00:00Z')),false);
assert.deepEqual(await tick({}, now),{state:'missing-dispatch-token'});
const env={UPDATE_DISPATCH_TOKEN:'test-only'};
async function scenario({runs=[],at='2026-10-27T13:46',fail=false}={}) {
  const calls=[];
  const request=async(url,options)=>{
    calls.push({url,options});
    if(url.includes('/runs?'))return Response.json({workflow_runs:runs});
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
  s=await scenario({runs:[{status}]});assert.equal((await s.run()).state,'update-running');assert.equal(s.calls.length,1);
}
s=await scenario({runs:[{status:'completed',created_at:'2026-10-27T06:18:00Z'}]});assert.equal((await s.run()).state,'backoff');
for(const at of ['bad','2026-10-27T18:00']) {
  s=await scenario({at});await assert.rejects(s.run(),/invalid-freshness/);assert.equal(s.calls.length,2);
}
s=await scenario({fail:true});await assert.rejects(s.run(),/freshness-status-503/);assert.equal(s.calls.length,2);
console.log('update watchdog: stale/fresh, active jobs, backoff, hours, fail closed, token isolation passed');
