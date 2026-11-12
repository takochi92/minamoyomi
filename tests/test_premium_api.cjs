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
    TEILOG_BILLING_MODE:'test',
    TEILOG_PREMIUM_TEST_USERS:uid
  };
  let handler, paid = false, checkoutCalls = 0, published = 0;
  globalThis.Deno = {env:{get:k=>config[k]},serve:fn=>{handler=fn;}};
  globalThis.fetch = async function (url, options) {
    const {hostname,pathname} = new URL(url);
    if (hostname === 'db.example') {
      if (pathname === '/auth/v1/user') {
        const token = options.headers.Authorization;
        return token === 'Bearer valid' ? Response.json({id:uid}) : new Response(null,{status:401});
      }
      assert.equal(options.headers.get('Authorization'),'Bearer service');
      if (pathname.endsWith('/teilog_premium_customers')) return Response.json([{customer_id:'cus_example'}]);
      if (pathname.endsWith('/teilog_publish_premium_snapshot')) { published++; return Response.json(true); }
      if (pathname.endsWith('/teilog_premium_snapshot')) {
        return Response.json([{data:{through:'20261112',venues:{'04':{motors:{'20':{straight:{grade:'S'}}}}}}}]);
      }
    }
    if (hostname === 'api.stripe.com') {
      if (pathname.endsWith('/subscriptions')) return Response.json({data:paid ? [{
        status:'active',items:{data:[{price:{id:'price_example'},current_period_end:Date.now()/1000+1000}]}
      }] : []});
      if (pathname.endsWith('/price_example')) return Response.json({active:true,currency:'jpy',unit_amount:400,recurring:{interval:'month',interval_count:1}});
      if (pathname.endsWith('/checkout/sessions')) {
        if (options.method === 'GET') return Response.json({data:[]});
        checkoutCalls++;
        assert.equal(options.body.get('line_items[0][price]'),'price_example');
        return Response.json({url:'https://checkout.stripe.com/test'});
      }
      if (pathname.endsWith('/billing_portal/sessions')) return Response.json({url:'https://billing.stripe.com/test'});
    }
    if (hostname === 'teilog.com') {
      return Response.json({date:'20261113',jcd:'04',rno:1,racelist:{boats:
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
  assert.equal(preview.testCheckout,true);
  assert.equal(preview.amount,400);
  assert.equal((await call({action:'checkout',amount:400})).status,200);
  assert.equal(checkoutCalls,1);
  paid=true;
  assert.equal((await call({action:'checkout',amount:400})).status,409);
  assert.equal((await call({action:'portal'})).status,200);
  const race = {action:'race',date:'20261113',venue:'04',race:1};
  const result=await call(race);
  assert.match(result.headers.get('cache-control'),/no-store/);
  assert.equal((await result.json()).evaluation.rows[0].metrics.straight.grade,'S');
  config.TEILOG_PREMIUM_TEST_USERS='';
  assert.equal((await call(race)).status,403);
  assert.equal((await call({action:'checkout',amount:400})).status,409);
  const data = {version:1,through:'20261112',venues:{'04':{motors:{}}}};
  assert.equal((await call(data,{'X-Premium-Publish-Key':'b'.repeat(64)})).status,401);
  assert.equal((await call(data,{'X-Premium-Publish-Key':config.TEILOG_PREMIUM_PUBLISH_KEY})).status,200);
  assert.equal(published,1);
  console.log('Premium API authentication, checkout, plan change, portal and snapshot checks OK.');
})().catch(error=>{console.error(error);process.exitCode=1;});
