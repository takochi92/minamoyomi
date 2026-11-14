import { timingSafeEqual } from 'node:crypto';
import { Buffer } from 'node:buffer';
import { calendarDay, matchesMotorPeriod, paidSubscription, raceEvaluation, validSnapshot } from './logic.mjs';

const origin = 'https://teilog.com';
const env = (key: string) => Deno.env.get(key) || '';
const base = env('SUPABASE_URL');
const service = env('SUPABASE_SERVICE_ROLE_KEY');
const stripeKey = env('TEILOG_STRIPE_SECRET_KEY');
const price = env('TEILOG_STRIPE_PRICE_ID');
const billing = env('TEILOG_BILLING_MODE');
const validPrices = [price, ...env('TEILOG_STRIPE_PREVIOUS_PRICE_IDS').split(',').map(x => x.trim())].filter(x => /^price_[A-Za-z0-9_]+$/.test(x));
const liveApproved = env('TEILOG_PREMIUM_LIVE_APPROVED') === 'true';
// Checking an existing membership and opening the billing portal must keep working when new sales
// are paused or misconfigured. Otherwise a paying member loses access and the cancel button while
// Stripe keeps charging. Only selling needs the approval flag and a valid current price.
const verifyReady = (billing === 'test' && stripeKey.startsWith('sk_test_')) ||
  (billing === 'live' && stripeKey.startsWith('sk_live_'));
const checkoutReady = verifyReady && /^price_[A-Za-z0-9_]+$/.test(price) && (billing === 'test' || liveApproved);
const cors = {
  'Access-Control-Allow-Origin': origin,
  'Access-Control-Allow-Headers': 'authorization,apikey,content-type,x-client-info',
  'Access-Control-Allow-Methods': 'POST,OPTIONS',
  'Cache-Control': 'private, no-store',
  'Vary': 'Origin',
};
const reply = (data: unknown, status = 200) => Response.json(data, { status, headers: cors });

async function rest(path: string, method = 'GET', body?: unknown, prefer?: string) {
  const headers = new Headers({ apikey: service, Authorization: 'Bearer ' + service, 'Content-Type': 'application/json' });
  if (prefer) headers.set('Prefer', prefer);
  const r = await fetch(base + '/rest/v1/' + path, {
    method, headers, body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(12000), redirect: 'error',
  });
  if (!r.ok) throw Error('Storage unavailable');
  const text = await r.text();
  return text ? JSON.parse(text) : null;
}

async function stripe(path: string, values?: Record<string, string>, idempotency?: string) {
  const headers = new Headers({ Authorization: 'Bearer ' + stripeKey, 'Stripe-Version': '2026-10-28.endive' });
  if (idempotency) headers.set('Idempotency-Key', idempotency);
  const r = await fetch('https://api.stripe.com/v1/' + path, {
    method: values ? 'POST' : 'GET', headers, body: values && new URLSearchParams(values),
    signal: AbortSignal.timeout(12000), redirect: 'error',
  });
  if (!r.ok) throw Error('Billing unavailable');
  return r.json();
}

async function monthlyAmount() {
  const plan = await stripe('prices/' + encodeURIComponent(price));
  if (!plan.active || plan.currency !== 'jpy' || plan.recurring?.interval !== 'month' ||
      plan.recurring.interval_count !== 1 || !Number.isInteger(plan.unit_amount) || plan.unit_amount <= 0) {
    throw Error('Invalid price');
  }
  return plan.unit_amount;
}

function validPublishKey(supplied: string) {
  const stored = env('TEILOG_PREMIUM_PUBLISH_KEY');
  return /^[a-f0-9]{64}$/.test(stored) && /^[a-f0-9]{64}$/.test(supplied) &&
    timingSafeEqual(Buffer.from(stored), Buffer.from(supplied));
}

async function customer(user: string, create = false) {
  const filter = 'teilog_premium_customers?user_id=eq.' + user + '&mode=eq.' + billing + '&select=customer_id';
  const existing = (await rest(filter))[0]?.customer_id;
  if (existing || !create) return existing;
  const next = await stripe('customers', { 'metadata[teilog_user_id]': user }, 'teilog-customer-v1-' + user);
  await rest('teilog_premium_customers', 'POST',
    { user_id: user, mode: billing, customer_id: next.id }, 'resolution=ignore-duplicates');
  const stored = (await rest(filter))[0]?.customer_id;
  if (!stored) throw Error('Customer mapping unavailable');
  return stored;
}

Deno.serve(async req => {
  if (req.method === 'OPTIONS') return new Response(null, { headers: cors });
  if (req.method !== 'POST') return reply({ error: 'method' }, 405);
  try {
    const publishKey = req.headers.get('x-premium-publish-key');
    if (publishKey !== null) {
      if (!validPublishKey(publishKey)) return reply({ error: 'unauthorized' }, 401);
      const raw = await req.text();
      if (raw.length > 2_000_000) return reply({ error: 'size' }, 413);
      const snapshot = JSON.parse(raw);
      const today = new Date(Date.now() + 9 * 3600000).toISOString().slice(0, 10).replaceAll('-', '');
      if (!validSnapshot(snapshot, today)) return reply({ error: 'invalid snapshot' }, 400);
      const stored = await rest('rpc/teilog_store_premium_snapshot', 'POST', { payload: snapshot });
      return reply({ stored });
    }

    const auth = req.headers.get('authorization') || '';
    if (!auth.startsWith('Bearer ')) return reply({ error: 'unauthorized' }, 401);
    const account = await fetch(base + '/auth/v1/user', {
      headers: { apikey: service, Authorization: auth }, signal: AbortSignal.timeout(10000), redirect: 'error',
    });
    if (account.status === 401 || account.status === 403) return reply({ error: 'unauthorized' }, 401);
    if (!account.ok) throw Error('Authentication unavailable');
    const user = (await account.json()).id;
    if (typeof user !== 'string' || !/^[0-9a-f-]{36}$/.test(user)) return reply({ error: 'unauthorized' }, 401);
    const body = await req.json();
    if (!body || typeof body !== 'object' || Array.isArray(body)) return reply({ error: 'invalid request' }, 400);
    const { action, date, venue, race, amount } = body;
    const tester = env('TEILOG_PREMIUM_TEST_USERS').split(',').map(x => x.trim()).includes(user);
    if (!['checkout', 'status', 'portal', 'race'].includes(action)) return reply({ error: 'invalid action' }, 400);
    const owner = action !== 'portal'
      ? (await rest('teilog_premium_owners?user_id=eq.' + user + '&select=user_id')).length === 1
      : false;
    const billingAccess = checkoutReady && (billing === 'live' || tester);
    const verifyAccess = verifyReady && (billing === 'live' || tester);
    const preview = tester && !billing;
    if (action === 'checkout' && (!billingAccess || owner)) return reply({ error: 'unavailable' }, 409);
    if (action === 'checkout' && amount !== await monthlyAmount()) return reply({ error: 'price changed' }, 409);
    const customerId = verifyAccess ? await customer(user, action === 'checkout' && billingAccess) : undefined;
    if (action === 'portal' && customerId) {
      const session = await stripe('billing_portal/sessions', { customer: customerId, return_url: origin + '/premium' });
      return reply({ url: session.url });
    }
    if (action === 'portal') return reply({ error: 'unavailable' }, 409);

    const customerFilter = customerId ? 'customer=' + encodeURIComponent(customerId) : '';
    // Reading Checkout first makes a completed purchase visible before checking subscriptions.
    const latest = action === 'checkout' ? (await stripe('checkout/sessions?' + customerFilter + '&limit=1')).data[0] : undefined;
    const subscriptions = customerId && !owner ? await stripe('subscriptions?status=all&limit=100&' + customerFilter) : {data: []};
    if (subscriptions.has_more) throw Error('Too many subscriptions to verify');
    const subs = subscriptions.data;
    const member = owner || preview || paidSubscription(subs, validPrices);
    if (action === 'status') {
      const amount = billingAccess && !member ? await monthlyAmount() : null;
      return reply({ member, checkout: billingAccess && billing === 'live', manage: !!customerId,
        owner, tester: preview, testCheckout: billingAccess && billing === 'test' && !member, amount });
    }
    if (action === 'checkout') {
      if (subs.some((s: {status: string}) => !['canceled', 'incomplete_expired'].includes(s.status))) {
        return reply({ error: 'manage existing subscription' }, 409);
      }
      if (latest?.status === 'complete' && (!latest.subscription ||
          !subs.some((sub: {id: string}) => sub.id === latest.subscription))) {
        return reply({ error: 'waiting for subscription' }, 409);
      }
      if (latest?.status === 'open') {
        if (latest.metadata?.teilog_price === price && latest.amount_total === amount && latest.url) return reply({ url: latest.url });
        return reply({ error: 'previous checkout still open' }, 409);
      }
      const created = await stripe('checkout/sessions', {
        mode: 'subscription', customer: customerId, 'line_items[0][price]': price, 'line_items[0][quantity]': '1',
        'metadata[teilog_price]': price, 'payment_method_types[0]': 'card',
        success_url: origin + '/premium?checkout=done', cancel_url: origin + '/premium',
      }, 'teilog-checkout-v2-' + customerId + '-' + price + '-' + (latest?.id || 'first'));
      return reply({ url: created.url });
    }
    if (action === 'race') {
      if (!member) return reply({ error: 'membership required' }, 403);
      if (calendarDay(date) === null || typeof venue !== 'string' ||
          !/^(0[1-9]|1[0-9]|2[0-4])$/.test(venue) || !Number.isInteger(race) || race < 1 || race > 12) {
        return reply({ error: 'invalid race' }, 400);
      }
      const min = new Date(calendarDay(date)! - 3 * 86400000).toISOString().slice(0, 10).replaceAll('-', '');
      const saved = (await rest('teilog_premium_daily?through=lt.' + date + '&through=gte.' + min +
        '&order=through.desc&limit=1&select=data'))[0]?.data;
      // `reason` lets the page tell a late nightly update from a race that simply has no rating.
      if (!saved) return reply({ evaluation: null, reason: 'snapshot_late' });
      if (!saved.venues?.[venue]) return reply({ evaluation: null, reason: 'venue_not_rated' });
      const publicRace = await fetch(origin + '/data/races/' + date + '/' + venue + String(race).padStart(2, '0') + '.json',
        { signal: AbortSignal.timeout(10000), redirect: 'error' });
      if (publicRace.status === 404) return reply({ evaluation: null, reason: 'race_card_missing' });
      if (!publicRace.ok) throw Error('Race data unavailable');
      const entry = await publicRace.json();
      if (entry.date !== date || entry.jcd !== venue || entry.rno !== race) return reply({ evaluation: null, reason: 'race_card_missing' });
      // A reset-looking race card must not inherit ratings from the previous motors.
      const boats = entry.racelist?.boats || [];
      if (boats.filter((boat: {motor_2: number}) => boat.motor_2 === 0).length >= 5) return reply({ evaluation: null, reason: 'new_motors' });
      const frames = boats.map((b: { frame: number, motor_no: number, toban?: string }) =>
        ({ frame: b.frame, motor: b.motor_no, rider: String(b.toban || '') }));
      if (frames.length !== 6 || !frames.every((b: {frame: number, motor: number}) =>
          Number.isInteger(b.frame) && b.frame >= 1 && b.frame <= 6 && Number.isInteger(b.motor) && b.motor > 0) ||
          new Set(frames.map((b: {frame: number}) => b.frame)).size !== 6 ||
          new Set(frames.map((b: {motor: number}) => b.motor)).size !== 6) return reply({ evaluation: null, reason: 'race_card_missing' });
      const ledgerResponse = await fetch(origin + '/data/motor-periods.json', {
        signal: AbortSignal.timeout(10000), redirect: 'error', cache: 'no-store',
      });
      if (ledgerResponse.status === 404) return reply({ evaluation: null, reason: 'motor_period_unknown' });
      if (!ledgerResponse.ok) throw Error('Motor periods unavailable');
      const ledger = await ledgerResponse.json();
      if (!matchesMotorPeriod(saved, ledger, date, venue)) return reply({ evaluation: null, reason: 'motor_period_unknown' });
      return reply({ evaluation: raceEvaluation(saved, date, venue, frames, entry.racelist?.title?.trim() || '') });
    }
    return reply({ error: 'unavailable' }, 409);
  } catch (error) {
    // Only the message: never the request, headers or keys.
    console.error('premium', error instanceof Error ? error.message : 'unknown error');
    if (error instanceof SyntaxError) return reply({ error: 'invalid JSON' }, 400);
    return reply({ error: 'temporarily unavailable' }, 503);
  }
});
