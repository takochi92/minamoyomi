const BASE = 'https://api.github.com/repos/takochi92/minamoyomi';
const WORKFLOW = '/actions/workflows/update.yml';
const STALE_MS = 5 * 60_000;
const BACKOFF_MS = 5 * 60_000;

export function operatingTime(now) {
  const hour = new Date(now.getTime() + 9 * 3600_000).getUTCHours();
  return hour < 2 || (hour >= 7 && hour < 23);
}

export async function tick(env, now = new Date(), request = fetch) {
  if (!operatingTime(now)) return {state:'outside-hours'};
  if (!env.UPDATE_DISPATCH_TOKEN) throw new Error('missing-dispatch-token');
  const response = await request('https://teilog.com/freshness.json?watchdog=' + now.getTime(), {
    cache:'no-store', signal:AbortSignal.timeout(10_000),
  });
  if (!response.ok) throw new Error('freshness-status-' + response.status);
  const freshness = await response.json();
  if (typeof freshness.updated_at !== 'string' ||
      !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(freshness.updated_at)) throw new Error('invalid-freshness');
  const age = now.getTime() - Date.parse(freshness.updated_at + '+09:00');
  if (!Number.isFinite(age) || age < -60_000) throw new Error('invalid-freshness-time');
  const health = {updated_at:freshness.updated_at, ageMinutes:Math.floor(age / 60_000)};
  const headers = {
    Accept:'application/vnd.github+json',
    Authorization:'Bearer ' + env.UPDATE_DISPATCH_TOKEN,
    'X-GitHub-Api-Version':'2022-11-28',
    'User-Agent':'Teilog-update-watchdog',
  };
  async function api(path, method = 'GET', body) {
    const response = await request(BASE + path, {
      method, headers, redirect:'manual', signal:AbortSignal.timeout(10_000),
      ...(body ? {body:JSON.stringify(body)} : {}),
    });
    if (!response.ok) {
      const error = new Error('github-status-' + response.status);
      error.health = health;
      throw error;
    }
    const expiry = Date.parse(response.headers.get('github-authentication-token-expiration') || '');
    if (Number.isFinite(expiry)) health.tokenExpiresOn=new Date(expiry).toISOString().slice(0,10);
    return response.status === 204 ? null : response.json();
  }
  const result = await api(WORKFLOW + '/runs?branch=main&per_page=20');
  if (!Array.isArray(result.workflow_runs)) throw new Error('invalid-run-list');
  const runs = result.workflow_runs;
  const active = runs.filter(run => run.status !== 'completed');
  if (active.length) {
    const oldest = Math.min(...active.map(run => Date.parse(run.run_started_at || run.created_at)).filter(Number.isFinite));
    return {state:now.getTime() - oldest > 20 * 60_000 ? 'update-stuck' : 'update-running', ...health};
  }
  if (runs.some(run => {
    const at = Date.parse(run.created_at);
    return Number.isFinite(at) && now.getTime() - at < BACKOFF_MS;
  })) return {state:'backoff',...health};
  // The data timestamp is recorded after runner setup. Waiting five minutes
  // from that timestamp adds setup time to every cycle (observed: six minutes).
  // Keep the normal cadence measured from the previous workflow start, while
  // still respecting active jobs and the five-minute backoff above.
  const knownPreviousStart=runs.some(run=>Number.isFinite(Date.parse(run.created_at)));
  if (age < STALE_MS && !knownPreviousStart) return {state:'fresh',...health};
  await api(WORKFLOW + '/dispatches', 'POST', {ref:'main'});
  return {state:'dispatched',...health};
}

export {UpdateMonitor} from './monitor.mjs';

async function authorized(request,env) {
  const actual=request.headers.get('Authorization') || '';
  if (!env.UPDATE_DISPATCH_TOKEN || !actual.startsWith('Bearer ') || actual.length>1000) return false;
  const hash=async value=>new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(value)));
  const [a,b]=await Promise.all([hash(actual.slice(7)),hash(env.UPDATE_DISPATCH_TOKEN)]);
  let different=0;for(let i=0;i<a.length;i++)different|=a[i]^b[i];return different===0;
}

export default {
  async scheduled(_event, env, ctx) {
    ctx.waitUntil(env.UPDATE_MONITOR.get(env.UPDATE_MONITOR.idFromName('race-updates')).fetch('https://internal/check', {method:'POST'}).then(response => {
      if (!response.ok) throw new Error('race-update-watchdog-failed');
    }));
  },
  async fetch(request,env) {
    if (request?.method!=='GET' || new URL(request.url).pathname!=='/health') return new Response('Not found',{status:404});
    if (!await authorized(request,env)) return new Response('Unauthorized',{status:401});
    const response=await env.UPDATE_MONITOR.get(env.UPDATE_MONITOR.idFromName('race-updates')).fetch('https://internal/status');
    return new Response(response.body,{status:response.status,headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
  },
};
