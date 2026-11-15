// 受付フラグを ON（TEILOG_PREMIUM_LIVE_APPROVED=true）にしたら、月額500円の申込が開くことを確かめる。
const assert = require('node:assert/strict');
const path = require('node:path');

(async function () {
  const uid = '10000000-0000-4000-8000-000000000001';
  const config = {
    SUPABASE_URL:'https://db.example', SUPABASE_SERVICE_ROLE_KEY:'service',
    TEILOG_BILLING_MODE:'live', TEILOG_PREMIUM_LIVE_APPROVED:'true',
    TEILOG_STRIPE_SECRET_KEY:'sk_live_example', TEILOG_STRIPE_PRICE_ID:'price_example'
  };
  let handler, unit = 500, created;
  globalThis.Deno = {env:{get:k=>config[k]},serve:fn=>{handler=fn;}};
  globalThis.fetch = async function (url, options) {
    const {hostname,pathname} = new URL(url);
    if (hostname === 'db.example') {
      if (pathname === '/auth/v1/user') return Response.json({id:uid});
      if (pathname.endsWith('/teilog_premium_owners')) return Response.json([]);
      if (pathname.endsWith('/teilog_premium_customers')) return Response.json([{customer_id:'cus_example'}]);
    }
    if (hostname === 'api.stripe.com') {
      if (pathname.endsWith('/subscriptions')) return Response.json({data:[]});
      if (pathname.endsWith('/price_example')) return Response.json({active:true,currency:'jpy',unit_amount:unit,recurring:{interval:'month',interval_count:1}});
      if (pathname.endsWith('/checkout/sessions')) {
        if (options.method === 'GET') return Response.json({data:[]});
        created = options.body;
        return Response.json({url:'https://checkout.stripe.com/live'});
      }
    }
    throw new Error('unexpected request '+hostname+pathname);
  };
  await import(path.join(__dirname,'..','supabase','functions','premium','index.ts'));
  const call = (body, login = true) => handler(new Request('https://teilog.com/functions/v1/premium',{method:'POST',
    headers:{Origin:'https://teilog.com','Content-Type':'application/json',...(login?{Authorization:'Bearer valid'}:{})},body:JSON.stringify(body)}));

  assert.deepEqual(await (await call({action:'offer'},false)).json(),{open:true,amount:500});
  const status = await (await call({action:'status'})).json();
  assert.equal(status.checkout,true);
  assert.equal(status.amount,500);
  assert.equal(status.member,false,'Opening sales does not make anyone a member before payment');
  const checkout = await call({action:'checkout',amount:500});
  assert.equal(checkout.status,200);
  assert.equal((await checkout.json()).url,'https://checkout.stripe.com/live');
  assert.equal(created.get('mode'),'subscription');
  assert.equal([...created.keys()].some(k=>k.startsWith('payment_method_types')),false,'Stripe no longer accepts payment_method_types here');
  assert.equal(created.get('success_url'),'https://teilog.com/premium?checkout=done');

  // まちがった価格ID（500円ではない）をつないだら、申込を開かない
  unit = 980;
  assert.notEqual((await call({action:'checkout',amount:980})).status,200,'A price other than 500 yen must not be sold');
  console.log('premium open: OK');
})().catch(error => { console.error(error); process.exit(1); });
