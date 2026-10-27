const BASE = 'https://api.github.com/repos/takochi92/minamoyomi';
const WORKFLOW = '/actions/workflows/update.yml';
const STALE_MS = 8 * 60_000;
const BACKOFF_MS = 5 * 60_000;

export function operatingTime(now) {
  const hour = new Date(now.getTime() + 9 * 3600_000).getUTCHours();
  return hour < 2 || (hour >= 7 && hour < 23);
}

export async function tick(env, now = new Date(), request = fetch) {
  if (!operatingTime(now)) return {state:'outside-hours'};
  if (!env.UPDATE_DISPATCH_TOKEN) return {state:'missing-dispatch-token'};
  const headers = {
    Accept:'application/vnd.github+json',
    Authorization:'Bearer ' + env.UPDATE_DISPATCH_TOKEN,
    'X-GitHub-Api-Version':'2022-11-28',
    'User-Agent':'Teilog-update-watchdog',
  };
  async function api(path, method = 'GET', body) {
    const response = await request(BASE + path, {
      method, headers, signal:AbortSignal.timeout(10_000),
      ...(body ? {body:JSON.stringify(body)} : {}),
    });
    if (!response.ok) throw new Error('github-status-' + response.status);
    return response.status === 204 ? null : response.json();
  }
  const result = await api(WORKFLOW + '/runs?branch=main&per_page=20');
  if (!Array.isArray(result.workflow_runs)) throw new Error('invalid-run-list');
  const runs = result.workflow_runs;
  if (runs.some(run => run.status !== 'completed')) return {state:'update-running'};
  if (runs.some(run => {
    const at = Date.parse(run.created_at);
    return Number.isFinite(at) && now.getTime() - at < BACKOFF_MS;
  })) return {state:'backoff'};

  // Read public data without transmitting the dispatch token to another host.
  const response = await request('https://teilog.com/freshness.json?watchdog=' + now.getTime(), {
    cache:'no-store', signal:AbortSignal.timeout(10_000),
  });
  if (!response.ok) throw new Error('freshness-status-' + response.status);
  const freshness = await response.json();
  if (typeof freshness.updated_at !== 'string' ||
      !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(freshness.updated_at)) {
    throw new Error('invalid-freshness');
  }
  const age = now.getTime() - Date.parse(freshness.updated_at + '+09:00');
  if (!Number.isFinite(age) || age < -60_000) throw new Error('invalid-freshness-time');
  if (age < STALE_MS) return {state:'fresh',updated_at:freshness.updated_at};
  await api(WORKFLOW + '/dispatches', 'POST', {ref:'main'});
  return {state:'dispatched',updated_at:freshness.updated_at};
}

export default {
  async scheduled(_event, env, ctx) {
    ctx.waitUntil(tick(env).then(result => console.log(JSON.stringify(result))).catch(error => {
      // Only our bounded status messages are logged; never response bodies or credentials.
      console.error('watchdog-failed', /^((github|freshness)-status-\d+|invalid-[a-z-]+)$/.test(error.message)
        ? error.message : 'request-failed');
      throw new Error('race-update-watchdog-failed');
    }));
  },
  fetch() { return new Response('Not found', {status:404}); },
};
