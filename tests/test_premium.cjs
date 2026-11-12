const assert = require('node:assert/strict');
const {buckets} = require('../site/premium.js');

(async function () {
  const {paidSubscription,raceEvaluation} = await import('../supabase/functions/premium/logic.mjs');
  const sub = {status:'active',items:{data:[{price:{id:'price_1'},current_period_end:101}]}};
  assert.equal(paidSubscription([sub],'price_1',100),true);
  assert.equal(paidSubscription([sub],'price_other',100),false);
  assert.equal(paidSubscription([sub],'price_1',101),false);
  assert.equal(paidSubscription([{...sub,status:'past_due'}],'price_1',100),false);
  assert.equal(paidSubscription([{...sub,cancel_at:100}],'price_1',100),false);
  const field={through:'20261112',venues:{'04':{motors:{'20':{straight:{grade:'S'}}}}}};
  const lanes=[{frame:1,motor:20},{frame:2,motor:22}];
  assert.equal(raceEvaluation(field,'20261112','04',lanes),null);
  assert.equal(raceEvaluation(field,'20261116','04',lanes),null);
  assert.deepEqual(raceEvaluation(field,'20261113','04',lanes).rows[1].metrics,{});
  const bets=[{date:'20261231',inv:300,ret:700},{date:'20270101',inv:700,ret:0},
              {date:'20270104',inv:200,ret:100},{date:'20270105',ret:900},
              {date:'20261301',ret:900}];
  assert.deepEqual(buckets(bets,'week','20270104').slice(-2).map(x=>x.net),[-300,-100]);
  assert.deepEqual(buckets(bets,'month','20270104').slice(-2).map(x=>x.net),[400,-800]);
  assert.deepEqual(buckets(bets,'year','20270104').slice(-2).map(x=>x.net),[400,-800]);
  console.log('Premium access, historical boundaries and chart totals OK.');
})().catch(error=>{console.error(error);process.exitCode=1;});
