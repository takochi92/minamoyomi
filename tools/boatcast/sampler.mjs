// 再生中の各コマから「決めた点の画素値」だけを取り出す（動画は保存しない。数値だけを返す）。
//
// requestVideoFrameCallback の中で、そのとき表示されたコマを canvas に描き、指定した点の RGB を読む。
// 1コマごとに mediaTime（コマの時刻）と presentedFrames を残すので、コマ抜けを後から確かめられる。

import { sleep } from './player.mjs';

const INSTALL_JS = `(() => {
  const v = document.querySelector('video');
  if (!v) return { ok: false, why: 'no-video' };
  if (typeof v.requestVideoFrameCallback !== 'function') return { ok: false, why: 'no-rvfc' };
  const S = window.__smp = window.__smp || {};
  S.video = v;
  // 点の集まり（動画の画素座標）。box は読み出す範囲（点の外接矩形）
  S.setPoints = (xy, scale) => {
    S.xy = Int32Array.from(xy); S.scale = scale || 1;
    let x0 = 1e9, y0 = 1e9, x1 = -1, y1 = -1;
    for (let i = 0; i < S.xy.length; i += 2) { x0 = Math.min(x0, S.xy[i]); x1 = Math.max(x1, S.xy[i]); y0 = Math.min(y0, S.xy[i+1]); y1 = Math.max(y1, S.xy[i+1]); }
    S.box = [x0, y0, x1 - x0 + 1, y1 - y0 + 1];
    S.canvas = document.createElement('canvas'); S.canvas.width = S.box[2]; S.canvas.height = S.box[3];
    S.ctx = S.canvas.getContext('2d', { willReadFrequently: true });
    return S.box;
  };
  // [t0, t1] を rate 倍速で再生し、表示されたコマごとに点の RGB を貯める
  S.run = (t0, t1, rate, channels) => new Promise((resolve) => {
    const n = S.xy.length / 2, [bx, by, bw, bh] = S.box, gray = channels === 1;
    const chunks = [], meta = [];
    let done = false, size = null;
    const finish = (why) => { if (done) return; done = true; v.pause(); resolve({ why, meta, size }); S.chunks = chunks; };
    const cb = (now, md) => {
      if (done) return;
      if (md.mediaTime >= t0 - 0.0005) {
        if (v.videoWidth !== (size && size[0]) || v.videoHeight !== (size && size[1])) {
          if (size) { meta.push({ resChange: [v.videoWidth, v.videoHeight], mt: md.mediaTime }); }
          size = size || [v.videoWidth, v.videoHeight];
        }
        S.ctx.drawImage(v, bx, by, bw, bh, 0, 0, bw, bh);
        const d = S.ctx.getImageData(0, 0, bw, bh).data;
        const out = new Uint8Array(n * (gray ? 1 : 3));
        for (let i = 0; i < n; i++) {
          const k = ((S.xy[2*i+1] - by) * bw + (S.xy[2*i] - bx)) * 4;
          if (gray) out[i] = (d[k] + d[k+1] + d[k+2] + 1) / 3;
          else { out[3*i] = d[k]; out[3*i+1] = d[k+1]; out[3*i+2] = d[k+2]; }
        }
        chunks.push(out);
        meta.push({ mt: md.mediaTime, pf: md.presentedFrames, w: md.width, h: md.height });
      }
      if (md.mediaTime >= t1) return finish('end');
      v.requestVideoFrameCallback(cb);
    };
    v.pause();
    const go = () => { S.setRate(rate); v.requestVideoFrameCallback(cb); const p = v.play(); if (p && p.catch) p.catch(() => finish('play-failed')); };
    v.addEventListener('seeked', go, { once: true });
    v.currentTime = Math.max(0, t0 - 0.6);
    setTimeout(() => finish('timeout'), ((t1 - t0 + 2) / rate) * 1000 + 30000);
    v.addEventListener('ended', () => finish('ended'), { once: true });
  });
  // プレイヤーが速さを 1 に戻すので、この video だけ速さを固定する（調べる側の再生だけ。配信には影響しない）
  S.setRate = (r) => {
    const d = Object.getOwnPropertyDescriptor(HTMLMediaElement.prototype, 'playbackRate');
    d.set.call(v, r);
    if (!S.pinned) { Object.defineProperty(v, 'playbackRate', { configurable: true, get() { return d.get.call(v); }, set() {} }); S.pinned = true; }
  };
  // 貯めた数値を base64 で少しずつ渡す
  S.take = (i, j) => { let s = ''; for (let k = i; k < Math.min(j, S.chunks.length); k++) { const c = S.chunks[k]; for (let m = 0; m < c.length; m += 8192) s += String.fromCharCode.apply(null, c.subarray(m, m + 8192)); } return btoa(s); };
  return { ok: true };
})()`;

/** 点の RGB（channels=1 なら灰色 1バイト）を [t0, t1] の全コマで取る。返り値 { meta:[{mt,pf,w,h}], rgb: Buffer(frames*n*channels), n } */
export async function samplePoints(cdp, points, t0, t1, { rate = 1, channels = 3 } = {}) {
  const ok = await cdp.evaluate(INSTALL_JS);
  if (!ok?.ok) throw new Error(`sampler を入れられません: ${ok?.why}`);
  const flat = points.flatMap(([x, y]) => [Math.round(x), Math.round(y)]);
  await cdp.evaluate(`window.__smp.setPoints(${JSON.stringify(flat)})`);
  const res = await cdp.evaluate(`window.__smp.run(${t0}, ${t1}, ${rate}, ${channels})`, { timeoutMs: ((t1 - t0 + 2) / rate) * 1000 + 60000 });
  const frames = res.meta.filter((m) => m.mt !== undefined).length;
  const bufs = [];
  const per = channels === 1 ? 60 : 40;
  for (let i = 0; i < frames; i += per) {
    const b64 = await cdp.evaluate(`window.__smp.take(${i}, ${i + per})`, { timeoutMs: 60000 });
    bufs.push(Buffer.from(b64, 'base64'));
  }
  await sleep(50);
  return { why: res.why, meta: res.meta, size: res.size, n: points.length, rgb: Buffer.concat(bufs) };
}

/** 縮小した灰色の画（場面の切りかわり判定用。w×h の数値だけ） */
export async function sampleGrid(cdp, t0, t1, { rate = 4, w = 48, h = 27, width = 854, height = 480 } = {}) {
  const pts = [];
  for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) pts.push([Math.round((i + 0.5) * width / w), Math.round((j + 0.5) * height / h)]);
  return samplePoints(cdp, pts, t0, t1, { rate });
}
