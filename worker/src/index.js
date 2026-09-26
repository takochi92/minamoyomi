/**
 * 艇ログ ライブオッズ（Cloudflare Worker）
 *
 * 1分ごと（cron）：
 *   サイトの data/index.json から「締切30分前〜締切」のレースを選び、公式の3連単・単勝オッズを取得して KV に保存。
 *   公式への負荷を抑えるため、対象は各場の次のレースだけ（通常1分に10〜25回）。リクエストの間は0.3秒あける。
 * GET /live?race=YYYYMMDD-JJ-R
 *   { race, deadline, snaps:[{t:"HH:MM", o3:[120], tf:[6]}...] } を返す（直近12回＋最初の1回）。
 *
 * KV は1日1キー（live:YYYYMMDD）にまとめて書く＝書き込みは1分1回。
 */
const OFFICIAL = "https://www.boatrace.jp/owpc/pc/race";
const WINDOW_MIN = 30;    // 締切何分前から取るか
const KEEP = 12;          // 保存するスナップショット数（最初の1回は別に残す）
const MAX_RACES = 24;     // 1回に取るレースの上限（安全弁）
const GAP_MS = 300;

export function parseOdds3t(html) {
  const cells = [...html.matchAll(/class="oddsPoint[^"]*">([^<]*)</g)].map((m) => m[1].trim());
  if (cells.length !== 120) return null;
  const out = new Array(120).fill(null);
  cells.forEach((c, i) => {
    const v = parseFloat(c);
    out[(i % 6) * 20 + Math.floor(i / 6)] = Number.isFinite(v) ? v : null; // 公式は列=1着艇 → 1-2-3,1-2-4…の順へ
  });
  return out;
}

export function parseOddsTf(html) {
  const cells = [...html.matchAll(/class="oddsPoint[^"]*">([^<]*)</g)].slice(0, 6).map((m) => parseFloat(m[1]));
  return cells.length === 6 ? cells.map((v) => (Number.isFinite(v) ? v : null)) : null;
}

export function jstNow(date = new Date()) {
  const j = new Date(date.getTime() + 9 * 3600e3);
  const p = (n) => String(n).padStart(2, "0");
  return { ymd: `${j.getUTCFullYear()}${p(j.getUTCMonth() + 1)}${p(j.getUTCDate())}`, hm: `${p(j.getUTCHours())}:${p(j.getUTCMinutes())}`,
           min: j.getUTCHours() * 60 + j.getUTCMinutes() };
}

const toMin = (hm) => { const [h, m] = hm.split(":").map(Number); return h * 60 + m; };

/** index.json から取得対象のレースを選ぶ */
export function targets(index, now) {
  if (!index || index.date !== now.ymd) return [];
  const out = [];
  for (const v of index.venues || []) {
    if (v.cancelled) continue;
    for (const r of v.races || []) {
      const left = toMin(r.deadline) - now.min;
      if (left >= 0 && left <= WINDOW_MIN) out.push({ jcd: v.jcd, rno: r.rno, deadline: r.deadline });
    }
  }
  return out.sort((a, b) => a.deadline.localeCompare(b.deadline)).slice(0, MAX_RACES);
}

export function addSnap(store, key, deadline, snap) {
  const r = (store.races[key] ||= { deadline, first: null, snaps: [] });
  if (!r.first) r.first = snap;
  const last = r.snaps[r.snaps.length - 1];
  if (last && last.t === snap.t) r.snaps[r.snaps.length - 1] = snap;
  else r.snaps.push(snap);
  if (r.snaps.length > KEEP) r.snaps = r.snaps.slice(-KEEP);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function getText(url, env) {
  const res = await fetch(url, { headers: { "User-Agent": `Mozilla/5.0 (compatible; TeilogLive/1.0; +${env.SITE_URL}/about.html)` }, cf: { cacheTtl: 0 } });
  if (!res.ok) throw new Error(`${res.status} ${url}`);
  return res.text();
}

export async function tick(env, date = new Date()) {
  const now = jstNow(date);
  const idx = await (await fetch(`${env.SITE_URL}/data/index.json?t=${Date.now()}`, { cf: { cacheTtl: 60 } })).json().catch(() => null);
  const list = targets(idx, now);
  if (!list.length) return { fetched: 0 };
  const kvKey = `live:${now.ymd}`;
  const store = (await env.LIVE.get(kvKey, "json")) || { date: now.ymd, races: {} };
  let ok = 0, errors = [];
  for (const r of list) {
    const q = `rno=${r.rno}&jcd=${r.jcd}&hd=${now.ymd}`;
    try {
      const o3 = parseOdds3t(await getText(`${OFFICIAL}/odds3t?${q}`, env));
      await sleep(GAP_MS);
      const tf = parseOddsTf(await getText(`${OFFICIAL}/oddstf?${q}`, env));
      await sleep(GAP_MS);
      if (o3) { addSnap(store, `${r.jcd}-${r.rno}`, r.deadline, { t: now.hm, o3, tf }); ok++; }
    } catch (e) { errors.push(String(e.message || e)); }
  }
  store.updated = now.hm;
  store.errors = errors.slice(0, 5);
  await env.LIVE.put(kvKey, JSON.stringify(store), { expirationTtl: 3 * 86400 });
  return { fetched: ok, errors };
}

const cors = (env) => ({ "Access-Control-Allow-Origin": env.ALLOW_ORIGIN || "*", "Content-Type": "application/json; charset=utf-8" });

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(tick(env, new Date(event.scheduledTime)));
  },
  async fetch(req, env) {
    const url = new URL(req.url);
    if (url.pathname === "/live") {
      const m = /^(\d{8})-(\d{2})-(\d{1,2})$/.exec(url.searchParams.get("race") || "");
      if (!m) return new Response('{"error":"race=YYYYMMDD-JJ-R"}', { status: 400, headers: cors(env) });
      const store = await env.LIVE.get(`live:${m[1]}`, "json");
      const r = store?.races?.[`${m[2]}-${+m[3]}`];
      const body = r ? { race: m[0], updated: store.updated, deadline: r.deadline, first: r.first, snaps: r.snaps } : { race: m[0], updated: store?.updated || null, snaps: [] };
      return new Response(JSON.stringify(body), { headers: { ...cors(env), "Cache-Control": "public, max-age=20" } });
    }
    if (url.pathname === "/health") {
      const now = jstNow();
      const store = await env.LIVE.get(`live:${now.ymd}`, "json");
      return new Response(JSON.stringify({ now: now.hm, updated: store?.updated || null, races: Object.keys(store?.races || {}).length, errors: store?.errors || [] }), { headers: cors(env) });
    }
    return new Response("not found", { status: 404 });
  },
};
