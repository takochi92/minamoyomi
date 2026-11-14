// 本番（live）で「販売承認」の設定が外れても、すでに払っている会員を締め出さないことを確かめる。
const assert = require('node:assert/strict');
const path = require('node:path');

(async function () {
  const uid = '10000000-0000-4000-8000-000000000001';
  // TEILOG_PREMIUM_LIVE_APPROVED をわざと入れない（設定ミスの再現）
  const config = {
    SUPABASE_URL:'https://db.example', SUPABASE_SERVICE_ROLE_KEY:'service',
    TEILOG_PREMIUM_PUBLISH_KEY:'a'.repeat(64), TEILOG_BILLING_MODE:'live',
    TEILOG_STRIPE_SECRET_KEY:'sk_live_example', TEILOG_STRIPE_PRICE_ID:'price_example'
  };
  let handler, checkoutCalls = 0, snapshots = [];
  const today = new Date(Date.now() + 9*3600000).toISOString().slice(0,10).replaceAll('-','');
  globalThis.Deno = {env:{get:k=>config[k]},serve:fn=>{handler=fn;}};
  globalThis.fetch = async function (url, options) {
    const {hostname,pathname} = new URL(url);
    if (hostname === 'db.example') {
      if (pathname === '/auth/v1/user') return Response.json({id:uid});
      if (pathname.endsWith('/teilog_premium_owners')) return Response.json([]);
      if (pathname.endsWith('/teilog_premium_customers')) return Response.json([{customer_id:'cus_example'}]);
      if (pathname.endsWith('/teilog_premium_daily')) return Response.json(snapshots);
    }
    if (hostname === 'api.stripe.com') {
      if (pathname.endsWith('/subscriptions')) return Response.json({data:[{id:'sub_example',status:'active',
        items:{data:[{price:{id:'price_example'},current_period_end:Date.now()/1000+1000}]}}]});
      if (pathname.endsWith('/billing_portal/sessions')) return Response.json({url:'https://billing.stripe.com/live'});
      if (pathname.endsWith('/checkout/sessions')) { checkoutCalls++; return Response.json({data:[]}); }
    }
    throw new Error('unexpected request '+hostname+pathname);
  };
  await import(path.join(__dirname,'..','supabase','functions','premium','index.ts'));
  const call = body => handler(new Request('https://teilog.com/functions/v1/premium',{method:'POST',
    headers:{Origin:'https://teilog.com',Authorization:'Bearer valid','Content-Type':'application/json'},body:JSON.stringify(body)}));

  const status = await (await call({action:'status'})).json();
  assert.equal(status.member,true,'A paying member keeps access when the sales flag is missing');
  assert.equal(status.manage,true,'A paying member can still reach the cancellation page');
  assert.equal(status.checkout,false,'New sales stay closed without approval');
  const portal = await call({action:'portal'});
  assert.equal(portal.status,200);
  assert.equal((await portal.json()).url,'https://billing.stripe.com/live');
  assert.notEqual((await call({action:'checkout'})).status,200,'Checkout stays closed without approval');
  assert.equal(checkoutCalls,0,'No Stripe checkout is created without approval');

  // 評価データが古くて出せないときは、理由を返す（黙って空にしない）
  const race = await call({action:'race',date:today,venue:'04',race:1});
  assert.equal(race.status,200);
  const body = await race.json();
  assert.equal(body.evaluation,null);
  assert.equal(body.reason,'snapshot_late');
  console.log('premium live guard: OK');
})().catch(error => { console.error(error); process.exit(1); });
