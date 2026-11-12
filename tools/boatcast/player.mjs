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

// ---- 表示フレームの時刻（requestVideoFrameCallback）----------------------------------------
// シークの「前に」登録し、ページに残して使う（window.__bc）。コールバックは表示された新しいフレームごとに呼ばれ、
// metadata.mediaTime が「そのとき画面に出たフレームの時刻」。currentTime（プレイヤーの再生位置）とは別物。
const PROBE_JS = `(() => {
  const v = document.querySelector('video');
  if (!v) return { ok: false, why: 'no-video' };
  if (window.__bc && window.__bc.video === v) return { ok: true, supported: window.__bc.supported, reused: true };
  const p = { video: v, supported: typeof v.requestVideoFrameCallback === 'function', seq: 0, last: null };
  window.__bc = p;
  if (p.supported) {
    const cb = (now, md) => {
      p.seq += 1;
      p.last = { seq: p.seq, mediaTime: md.mediaTime, presentedFrames: md.presentedFrames, presentationTime: md.presentationTime,
                 expectedDisplayTime: md.expectedDisplayTime, width: md.width, height: md.height, currentTime: v.currentTime };
      v.requestVideoFrameCallback(cb);
    };
    v.requestVideoFrameCallback(cb);
  }
  // シーク → seeked を待つ → 新しいフレームの表示を待つ → 表示が落ち着くのを待つ。リスナーは currentTime を変える前に登録する
  p.seekTo = async (T, mode) => {
    const seq0 = p.seq;
    if (mode === 'seek') v.pause();
    const seeked = await new Promise((res) => {
      const to = setTimeout(() => res(false), 15000);
      v.addEventListener('seeked', () => { clearTimeout(to); res(true); }, { once: true });
      v.currentTime = T;
    });
    if (mode === 'play') { const pr = v.play(); if (pr && pr.catch) pr.catch(() => {}); }
    let got = false;
    if (p.supported) {
      const end = performance.now() + 2500;
      while (performance.now() < end) { if (p.seq > seq0) { got = true; break; } await new Promise((r) => setTimeout(r, 25)); }
      if (got && mode === 'seek') {                       // 追加のフレームが続かなくなるまで待つ（最大 約1.5秒）
        let ls = p.seq;
        for (let i = 0; i < 10; i++) { await new Promise((r) => setTimeout(r, 150)); if (p.seq === ls) break; ls = p.seq; }
      }
    } else {
      await new Promise((r) => setTimeout(r, 600));
    }
    return { seeked, gotFrame: got, seq0, seq: p.seq, last: p.last, currentTime: v.currentTime, paused: v.paused };
  };
  return { ok: true, supported: p.supported };
})()`;

const PROBE_READ_JS = `(() => {
  const p = window.__bc, v = document.querySelector('video');
  if (!p || !v) return { installed: false };
  const q = v.getVideoPlaybackQuality ? v.getVideoPlaybackQuality() : null;
  return { installed: true, supported: p.supported, seq: p.seq, last: p.last, currentTime: v.currentTime, paused: v.paused,
           error: v.error ? { code: v.error.code, message: v.error.message || '' } : null,
           seekable: Array.from({ length: v.seekable.length }, (_, i) => [v.seekable.start(i), v.seekable.end(i)]),
           quality: q ? { total: q.totalVideoFrames, dropped: q.droppedVideoFrames } : null };
})()`;

/** フレーム時刻の監視を入れる（シークの前に呼ぶ。ページを読み込み直したら入れ直す） */
export async function installFrameProbe(cdp) {
  const r = await cdp.evaluate(PROBE_JS);
  if (!r?.ok) throw new StageError('player-load', `フレーム監視を入れられません（${r?.why || '不明'}）`);
  return r;
}

export async function readProbe(cdp) {
  return cdp.evaluate(PROBE_READ_JS);
}

const r3 = (x) => (Number.isFinite(x) ? Math.round(x * 1000) / 1000 : null);

function frameFrom(last, supported) {
  if (!supported || !last) return { supported: Boolean(supported), mediaTime: null, presentedFrames: null, presentationTime: null, seq: null };
  return { supported: true, mediaTime: last.mediaTime, presentedFrames: last.presentedFrames, presentationTime: last.presentationTime ?? null, width: last.width, height: last.height, seq: last.seq };
}

/**
 * 指定秒へシークして、表示されたフレームを確認してから PNG を返す。
 *  mode='seek' … 一時停止 → シーク → seeked と新しいフレームの表示を確認 → 表示が落ち着いてから撮影。撮影の前後で
 *                フレームが変わっていないこと（stable）も確認する。変わっていたら1回だけやり直す。
 *                同じコマの上に再シークすると新しいフレームが出ないので、その場合は一度別の位置へ動かしてから戻す（nudged）
 *  mode='play' … シーク後、再生したまま撮る。撮影の前後で「最後に表示されたフレーム」が同じだったときだけ、
 *                画像とフレーム時刻の対応を確認できたとみなす（そうでなければ範囲 mediaTimeRange だけ記録）
 * @returns {{png, requested, seeked, nudged, attempts, stable, paused, error, seekable, quality, playerPosition, frame, mediaTimeRange}}
 */
export async function seekAndShoot(cdp, sec, { mode = 'seek', duration = null } = {}) {
  const probe = await installFrameProbe(cdp);
  const T = JSON.stringify(sec);
  const M = JSON.stringify(mode);
  let attempts = 0;
  let out = null;
  while (attempts < 2) {
    attempts += 1;
    let r = await cdp.evaluate(`window.__bc.seekTo(${T}, ${M})`, { timeoutMs: 40000 });
    let nudged = false;
    if (mode === 'seek' && r.seeked && !r.gotFrame && probe.supported) {
      nudged = true;                                             // 同じコマの上へのシークは新しいフレームを出さない
      const dur = Number.isFinite(duration) ? duration : sec + 10;
      const away = sec + 2 <= dur - 0.5 ? sec + 2 : Math.max(0, sec - 2);
      await cdp.evaluate(`window.__bc.seekTo(${JSON.stringify(away)}, 'seek')`, { timeoutMs: 40000 });
      r = await cdp.evaluate(`window.__bc.seekTo(${T}, 'seek')`, { timeoutMs: 40000 });
    }
    await sleep(250);                                            // 描画が画面に出るのを少し待つ
    const s1 = await readProbe(cdp);
    const png = await cdp.screenshot();
    const s2 = await readProbe(cdp);
    let stable;
    let frame;
    let mediaTimeRange = null;
    if (mode === 'seek') {
      stable = probe.supported ? Boolean(r.gotFrame) && s1.seq === r.seq && s2.seq === r.seq && s2.paused && Math.abs(s2.currentTime - r.currentTime) < 0.001 : null;   // null＝確かめられない
      frame = frameFrom(r.gotFrame ? r.last : null, probe.supported);
    } else {
      stable = probe.supported ? Boolean(r.gotFrame) && s1.seq === s2.seq : null;   // 撮影の前後で最後のフレームが同じ → 画像はそのフレーム
      frame = frameFrom(stable ? s2.last : null, probe.supported);
      if (stable === false) frame.ambiguous = true;                // フレームが進んだので1つに決められない（範囲 mediaTimeRange を見る）
      mediaTimeRange = { from: r3(s1.last?.mediaTime), to: r3(s2.last?.mediaTime), framesDuringCapture: s2.seq - s1.seq };
    }
    out = {
      png, requested: sec, seeked: r.seeked, nudged, attempts, stable, frame, mediaTimeRange,
      paused: s2.paused, error: s2.error, seekable: s2.seekable, quality: s2.quality,
      playerPosition: { afterSeek: r3(r.currentTime), beforeShot: r3(s1.currentTime), afterShot: r3(s2.currentTime) },
    };
    if (stable !== false || mode === 'play') break;              // 落ち着かなかったときだけ、1回やり直す
  }
  return out;
}
