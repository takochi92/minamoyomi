const assert = require('node:assert/strict');

(async function () {
  const origin = 'https://teilog.com';
  const uid = '10000000-0000-4000-8000-000000000001';
  const config = {
    SUPABASE_URL:'https://db.example',
    SUPABASE_SERVICE_ROLE_KEY:'service',
    TEILOG_PREMIUM_PUBLISH_KEY:'a'.repeat(64),
    TEILOG_STRIPE_SECRET_KEY:'sk_test_example',
    TEILOG_STRIPE_PRICE_ID:'price_example',
    TEILOG_STRIPE_PREVIOUS_PRICE_IDS:'price_old',
    TEILOG_BILLING_MODE:'test',
    TEILOG_PREMIUM_TEST_USERS:uid
  };
  let handler, paid = false, paymentStatus = 'active', checkoutCalls = 0, published = 0, session, authDown = false;
  let createKey;
  const now = Date.now();
  const cutoff = new Date(now + 9*3600000 - 86400000).toISOString().slice(0,10).replaceAll('-','');
  const today = new Date(now + 9*3600000).toISOString().slice(0,10).replaceAll('-','');
  const data = {version:1,through:cutoff,venues:{'04':{period:'20260618',motors:{'20':{
    straight:{grade:'S',runs:9,meetings:2,field:20,through:cutoff,delta:-.05,venue_delta:-.04}
  }}}}};
  globalThis.Deno = {env:{get:k=>config[k]},serve:fn=>{handler=fn;}};
  globalThis.fetch = async function (url, options) {
    const {hostname,pathname} = new URL(url);
    if (hostname === 'db.example') {
      if (pathname === '/auth/v1/user') {
        if (authDown) return new Response(null,{status:503});
        const token = options.headers.Authorization;
        return token === 'Bearer valid' ? Response.json({id:uid}) : new Response(null,{status:401});
      }
      assert.equal(options.headers.get('Authorization'),'Bearer service');
      if (pathname.endsWith('/teilog_premium_customers')) return Response.json([{customer_id:'cus_example'}]);
      if (pathname.endsWith('/teilog_store_premium_snapshot')) { published++; return Response.json(true); }
      if (pathname.endsWith('/teilog_premium_daily')) {
        assert.equal(new URL(url).searchParams.get('through'),'lt.'+today);
        return Response.json([{data}]);
      }
    }
    if (hostname === 'api.stripe.com') {
      if (pathname.endsWith('/subscriptions')) return Response.json({data:paid ? [{
        id:'sub_example',status:paymentStatus,items:{data:[{price:{id:'price_old'},current_period_end:Date.now()/1000+1000}]}
      }] : []});
      if (pathname.endsWith('/price_example')) return Response.json({active:true,currency:'jpy',unit_amount:400,recurring:{interval:'month',interval_count:1}});
      if (pathname.endsWith('/checkout/sessions')) {
        if (options.method === 'GET') return Response.json({data:session ? [session] : []});
        createKey = options.headers.get('Idempotency-Key');
        checkoutCalls++;
        assert.equal(options.body.get('line_items[0][price]'),'price_example');
        return Response.json({url:'https://checkout.stripe.com/test'});
      }
      if (pathname.endsWith('/billing_portal/sessions')) return Response.json({url:'https://billing.stripe.com/test'});
    }
    if (hostname === 'teilog.com') {
      return Response.json({date:today,jcd:'04',rno:1,racelist:{boats:
        Array.from({length:6},(_,i)=>({frame:i+1,motor_no:20+i,motor_2:22}))}});
    }
    assert.fail('Unexpected endpoint ' + url);
  };
  await import('../supabase/functions/premium/index.ts');
  const call = (body,headers = {Authorization:'Bearer valid'}) =>
    handler(new Request(origin+'/premium',{method:'POST',headers,body:JSON.stringify(body)}));
  assert.equal((await call({action:'race'},{})).status,401);
  assert.equal((await call({action:'race'},{Authorization:'Bearer invalid'})).status,401);
  assert.equal((await call({action:'checkout',amount:401})).status,409);
  assert.equal(checkoutCalls,0);
  const preview = await (await call({action:'status'})).json();
  assert.equal(preview.checkout,false);
  assert.equal(preview.member,false,'Trial allowlist must not mask a test payment failure');
  assert.equal(preview.testCheckout,true);
  assert.equal(preview.amount,400);
  assert.equal((await call({action:'checkout',amount:400})).status,200);
  assert.equal(checkoutCalls,1);
  const initialKey = createKey;
  assert.equal((await call({action:'checkout',amount:400})).status,200);
  assert.equal(createKey,initialKey,'Concurrent retries use the same Stripe key');
  session = {id:'cs_example',status:'open',url:'https://checkout.stripe.com/test',amount_total:400,metadata:{teilog_price:'price_old'}};
  assert.equal((await call({action:'checkout',amount:400})).status,409,'Do not return an old-price checkout');
  session.metadata.teilog_price = 'price_example';
  assert.equal((await call({action:'checkout',amount:400})).status,200);
  assert.equal(checkoutCalls,2,'Reuse the existing checkout');
  session.status = 'complete';
  session.subscription = 'sub_example';
  assert.equal((await call({action:'checkout',amount:400})).status,409,'Wait for subscription visibility');
  paid=true;
  assert.equal((await (await call({action:'status'})).json()).member,true,'Retain access at the previous price');
  assert.equal((await call({action:'checkout',amount:400})).status,409);
  assert.equal((await call({action:'portal'})).status,200);
  const race = {action:'race',date:today,venue:'04',race:1};
  const result=await call(race);
  assert.match(result.headers.get('cache-control'),/no-store/);
  assert.equal((await result.json()).evaluation.rows[0].metrics.straight.grade,'S');
  paymentStatus = 'past_due';
  assert.equal((await call(race)).status,403,'Payment failure revokes access in test mode');
  paymentStatus = 'canceled';
  assert.equal((await call(race)).status,403,'Cancellation revokes access');
  paymentStatus = 'active';
  config.TEILOG_PREMIUM_TEST_USERS='';
  assert.equal((await call(race)).status,403);
  assert.equal((await call({action:'checkout',amount:400})).status,409);
  authDown = true;
  assert.equal((await call({action:'status'})).status,503);
  authDown = false;
  const headers = {'X-Premium-Publish-Key':config.TEILOG_PREMIUM_PUBLISH_KEY};
  assert.equal((await call({...data,through:today},headers)).status,400);
  assert.equal((await call({...data,venues:{'04':{motors:{}}}},headers)).status,400);
  assert.equal((await call(null)).status,400);
  assert.equal((await call(data,{'X-Premium-Publish-Key':'b'.repeat(64)})).status,401);
  assert.equal((await call(data,{'X-Premium-Publish-Key':config.TEILOG_PREMIUM_PUBLISH_KEY})).status,200);
  assert.equal(published,1);
  console.log('Premium API authentication, checkout, plan change, portal and snapshot checks OK.');
})().catch(error=>{console.error(error);process.exitCode=1;});
