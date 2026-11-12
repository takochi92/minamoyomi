import { timingSafeEqual } from 'node:crypto';
import { Buffer } from 'node:buffer';
import { paidSubscription, raceEvaluation } from './logic.mjs';

const origin = 'https://teilog.com';
const env = (key: string) => Deno.env.get(key) || '';
const base = env('SUPABASE_URL');
const service = env('SUPABASE_SERVICE_ROLE_KEY');
const stripeKey = env('TEILOG_STRIPE_SECRET_KEY');
const price = env('TEILOG_STRIPE_PRICE_ID');
const billing = env('TEILOG_BILLING_MODE');
const liveApproved = env('TEILOG_PREMIUM_LIVE_APPROVED') === 'true';
const checkoutReady = /^price_/.test(price) &&
  ((billing === 'test' && stripeKey.startsWith('sk_test_')) ||
   (billing === 'live' && liveApproved && stripeKey.startsWith('sk_live_')));
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
      if (snapshot?.version !== 1 || !/^20\d{6}$/.test(snapshot.through) ||
          !snapshot.venues || !Object.keys(snapshot.venues).length) return reply({ error: 'invalid snapshot' }, 400);
      const stored = await rest('rpc/teilog_publish_premium_snapshot', 'POST', { payload: snapshot });
      return reply({ stored });
    }

    const auth = req.headers.get('authorization') || '';
    if (!auth.startsWith('Bearer ')) return reply({ error: 'unauthorized' }, 401);
    const account = await fetch(base + '/auth/v1/user', {
      headers: { apikey: service, Authorization: auth }, signal: AbortSignal.timeout(10000), redirect: 'error',
    });
    if (!account.ok) return reply({ error: 'unauthorized' }, 401);
    const user = (await account.json()).id;
    if (typeof user !== 'string' || !/^[0-9a-f-]{36}$/.test(user)) return reply({ error: 'unauthorized' }, 401);
    const { action, date, venue, race, amount } = await req.json();
    const tester = env('TEILOG_PREMIUM_TEST_USERS').split(',').map(x => x.trim()).includes(user);
    const canCheckout = checkoutReady && (billing === 'live' || tester);
    if (action === 'checkout' && !canCheckout) return reply({ error: 'unavailable' }, 409);
    if (action === 'checkout' && amount !== await monthlyAmount()) return reply({ error: 'price changed' }, 409);
    const customerId = canCheckout ? await customer(user, action === 'checkout') : undefined;
    const subs = customerId ? (await stripe('subscriptions?status=all&limit=100&customer=' + encodeURIComponent(customerId))).data : [];
    const member = paidSubscription(subs, price) || tester;
    if (action === 'status') {
      const amount = canCheckout && (!member || billing === 'test') ? await monthlyAmount() : null;
      return reply({ member, checkout: canCheckout && billing === 'live', manage: !!customerId,
        tester, testCheckout: canCheckout && billing === 'test', amount });
    }
    if (action === 'portal' && customerId) {
      const session = await stripe('billing_portal/sessions', { customer: customerId, return_url: origin + '/premium' });
      return reply({ url: session.url });
    }
    if (action === 'checkout' && canCheckout) {
      if (subs.some((s: {status: string}) => !['canceled', 'incomplete_expired'].includes(s.status))) {
        return reply({ error: 'manage existing subscription' }, 409);
      }
      // Repeated clicks share a session within the checkout expiry window.
      const session = await stripe('checkout/sessions?customer=' + encodeURIComponent(customerId) + '&status=open&limit=1');
      if (session.data[0]?.url) return reply({ url: session.data[0].url });
      const created = await stripe('checkout/sessions', {
        mode: 'subscription', customer: customerId, 'line_items[0][price]': price, 'line_items[0][quantity]': '1',
        'payment_method_types[0]': 'card', success_url: origin + '/premium?checkout=done', cancel_url: origin + '/premium',
      }, 'teilog-checkout-v1-' + customerId + '-' + Math.floor(Date.now() / 3600000));
      return reply({ url: created.url });
    }
    if (action === 'race') {
      if (!member) return reply({ error: 'membership required' }, 403);
      if (typeof date !== 'string' || !/^20\d{6}$/.test(date) || typeof venue !== 'string' ||
          !/^(0[1-9]|1[0-9]|2[0-4])$/.test(venue) || !Number.isInteger(race) || race < 1 || race > 12) {
        return reply({ error: 'invalid race' }, 400);
      }
      const saved = (await rest('teilog_premium_snapshot?id=eq.1&select=data'))[0]?.data;
      if (!saved?.venues?.[venue]) return reply({ evaluation: null });
      const publicRace = await fetch(origin + '/data/races/' + date + '/' + venue + String(race).padStart(2, '0') + '.json',
        { signal: AbortSignal.timeout(10000), redirect: 'error' });
      if (!publicRace.ok) return reply({ evaluation: null });
      const entry = await publicRace.json();
      if (entry.date !== date || entry.jcd !== venue || entry.rno !== race) return reply({ evaluation: null });
      // A reset-looking race card must not inherit ratings from the previous motors.
      const boats = entry.racelist?.boats || [];
      if (boats.every((boat: {motor_2: number}) => boat.motor_2 === 0)) return reply({ evaluation: null });
      const frames = boats.map((b: { frame: number, motor_no: number }) => ({ frame: b.frame, motor: b.motor_no }));
      if (frames.length !== 6 || new Set(frames.map((b: {frame: number}) => b.frame)).size !== 6) return reply({ evaluation: null });
      return reply({ evaluation: raceEvaluation(saved, date, venue, frames) });
    }
    return reply({ error: 'unavailable' }, 409);
  } catch {
    return reply({ error: 'temporarily unavailable' }, 503);
  }
});
