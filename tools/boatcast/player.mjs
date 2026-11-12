// プレイヤーページの操作（capture.mjs と verify.mjs で共有）。
// 単体プレイヤーURLを直接開き、トップレベルの <video> を相手にする（iframe 経由は対象外）。

import { StageError, classifyFailure } from './failures.mjs';
import { redactText } from './redact.mjs';

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const VIDEO_STATE_EXPR = `(() => {
  const v = document.querySelector('video');
  if (!v) return { has: false };
  const r = v.getBoundingClientRect();
  return {
    has: true, duration: v.duration, currentTime: v.currentTime, paused: v.paused, ended: v.ended,
    readyState: v.readyState, width: v.videoWidth, height: v.videoHeight,
    seekable: Array.from({ length: v.seekable.length }, (_, i) => [v.seekable.start(i), v.seekable.end(i)]),
    error: v.error ? { code: v.error.code, message: v.error.message || '' } : null,
    rect: { x: r.x, y: r.y, w: r.width, h: r.height },
  };
})()`;

/** <video> の今の状態。duration は NaN / Infinity が JSON にできないので null になることに注意（Number.isFinite で判定） */
export async function readVideo(cdp) {
  const s = await cdp.evaluate(VIDEO_STATE_EXPR);
  if (s && s.has && (s.duration === null || s.duration === undefined)) s.duration = NaN;
  return s;
}

export async function readPageText(cdp, max = 600) {
  try {
    const t = await cdp.evaluate(`(document.body && document.body.innerText || '').slice(0, ${max})`);
    return redactText(String(t || ''));
  } catch { return ''; }
}

/**
 * ネットワークの失敗（HTTP 400 以上・読み込み失敗）を、ホストとパスだけで集める。クエリは最初から持たない。
 * @returns {{httpErrors:Array<{host:string,path:string,status:number}>, failed:Array<{host:string,path:string,error:string}>}}
 */
export function watchNetwork(cdp) {
  const state = { httpErrors: [], failed: [] };
  const urls = new Map();
  const hp = (u) => { try { const x = new URL(u); return { host: x.host, path: x.pathname }; } catch { return { host: '', path: '' }; } };
  cdp.on('Network.requestWillBeSent', (p) => { urls.set(p.requestId, hp(p.request?.url || '')); });
  cdp.on('Network.responseReceived', (p) => {
    const st = p.response?.status;
    if (st >= 400) state.httpErrors.push({ ...hp(p.response.url), status: st });
  });
  cdp.on('Network.loadingFailed', (p) => {
    if (p.canceled) return;
    state.failed.push({ ...(urls.get(p.requestId) || { host: '', path: '' }), error: String(p.errorText || '') });
  });
  return state;
}

/** 失敗の判定に使う状況をまとめる */
export async function failureContext(cdp, net, extra = {}) {
  let video = null;
  try { video = await readVideo(cdp); } catch { /* ページが取れないときは null のまま */ }
  return { video, httpErrors: net?.httpErrors || [], pageText: await readPageText(cdp), ...extra };
}

/** video 要素の出現と duration の確定を待つ。video.error が出たら待たずに分類して投げる */
export async function waitForVideo(cdp, net, { timeoutMs = 45000, intervalMs = 500 } = {}) {
  const end = Date.now() + timeoutMs;
  let last = null;
  while (Date.now() < end) {
    try { last = await readVideo(cdp); } catch (e) {
      throw new StageError('cdp', `video の状態を読めません: ${e.message}`);
    }
    if (last?.has && last.error) break;
    if (last?.has && Number.isFinite(last.duration) && last.duration > 0) return last;
    await sleep(intervalMs);
  }
  const ctx = await failureContext(cdp, net);
  const c = classifyFailure(ctx);
  throw new StageError(c.stage, c.cause, { video: ctx.video && { has: ctx.video.has, duration: String(ctx.video.duration), error: ctx.video.error } });
}

/**
 * 再生を始め、currentTime が進むことを2回のサンプリングで確かめる。
 * 進まなければ、video の中央を CDP でクリックして再試行する（最大 attempts 回）。
 * @returns {{progressed:boolean, samples:Array<{t:number, at:number}>, clicked:boolean}}
 */
export async function ensurePlaying(cdp, { attempts = 3, gapMs = 1500 } = {}) {
  let clicked = false;
  let samples = [];
  for (let i = 0; i < attempts; i++) {
    await cdp.evaluate(`(() => { const v = document.querySelector('video'); if (v) { const p = v.play(); if (p && p.catch) p.catch(() => {}); } })()`);
    await sleep(400);
    const a = await readVideo(cdp);
    await sleep(gapMs);
    const b = await readVideo(cdp);
    samples = [{ t: a.currentTime, at: Date.now() - gapMs }, { t: b.currentTime, at: Date.now() }];
    if (b.error) return { progressed: false, samples, clicked, error: b.error };
    if (b.currentTime - a.currentTime > 0.3) return { progressed: true, samples, clicked };
    const r = b.rect || a.rect;
    if (r && r.w > 0 && r.h > 0) {
      await cdp.click(Math.round(r.x + r.w / 2), Math.round(r.y + r.h / 2));   // プレイヤー中央をクリック
      clicked = true;
    }
    await sleep(500);
  }
  return { progressed: false, samples, clicked };
}

/**
 * 指定秒へシークしてフレームを PNG で返す。
 *  mode='seek' … 一時停止してシーク → seeked と最初のフレーム描画を待つ → 撮影（フレームが安定する想定。実機で要確認）
 *  mode='play' … シークして再生したまま撮影（実際の currentTime は撮影の前後で記録する）
 * @returns {{png:Buffer, requested:number, actual:number, before:number, paused:boolean, error:object|null}}
 */
export async function seekAndShoot(cdp, sec, { mode = 'seek' } = {}) {
  const prep = await cdp.evaluate(`(async (T, MODE) => {
    const v = document.querySelector('video');
    if (!v) return { ok: false, why: 'no-video' };
    if (MODE === 'seek') v.pause();
    await new Promise((resolve, reject) => {
      const to = setTimeout(() => reject(new Error('seek timeout')), 15000);
      v.addEventListener('seeked', () => { clearTimeout(to); resolve(); }, { once: true });
      v.currentTime = T;
    });
    if (MODE === 'play') { const p = v.play(); if (p && p.catch) p.catch(() => {}); }
    await new Promise((resolve) => {
      if (v.requestVideoFrameCallback) {
        const to = setTimeout(resolve, 2500);
        v.requestVideoFrameCallback(() => { clearTimeout(to); resolve(); });
      } else setTimeout(resolve, 600);
    });
    return { ok: true, t: v.currentTime };
  })(${JSON.stringify(sec)}, ${JSON.stringify(mode)})`, { timeoutMs: 40000 });
  if (!prep?.ok) throw new StageError('player-load', `シークできません（${prep?.why || '不明'}）`);
  await sleep(250);                         // 描画が画面に出るのを少し待つ
  const png = await cdp.screenshot();
  const after = await readVideo(cdp);
  const tol = mode === 'play' ? { lo: -0.5, hi: 3 } : { lo: -0.5, hi: 0.5 };      // 実測 − 指定秒 の許容幅
  const diff = after.currentTime - sec;
  const seekOk = Number.isFinite(diff) && diff >= tol.lo && diff <= tol.hi;
  return { png, requested: sec, before: prep.t, actual: after.currentTime, paused: after.paused, error: after.error, seekOk, seekable: after.seekable };
}
