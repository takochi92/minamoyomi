#!/usr/bin/env node
// 展示リプレイから「計測に使う数値」だけを取り出す（動画も静止画も保存しない）。
//
//   node measure-capture.mjs --date 20261114 --venue 04 --races 1,2,3 --out DIR
//
// 1レースごとに：
//   1) 480p を 4倍速で通して、48×27 の灰色の値で場面を分ける（切りかわりで区切り、場の profile の signature と相関）
//   2) 1080p を 1倍速で、見つかった固定カメラの場面だけ再生し、profile の「測る道すじ」の点の RGB を全コマ取る
//   3) DIR/<date>-<venue>-<race>/ に shot ごとの .bin（点の値）と manifest.json（コマ時刻・解像度・コマ抜け）を書く
// 解析は python -m tools.boatcast_measure（このファイルは取り出すだけ）。

import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { withChrome, replayUrl } from './session.mjs';
import { samplePoints, sampleGrid } from './sampler.mjs';
import { nowJst } from './util.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const CAPTURE_VERSION = 'mc-2';

export function loadProfile(venue) {
  return JSON.parse(readFileSync(path.join(HERE, 'profiles', `${venue}.json`), 'utf8'));
}

/** 道すじ（折れ線）に沿って step ごと、垂直方向に ±half を ostep ごとの点。python 側と同じ並び（s が外側） */
export function pathPoints(poly, step, half, ostep) {
  const seg = []; const cum = [0];
  for (let i = 1; i < poly.length; i++) {
    const dx = poly[i][0] - poly[i - 1][0], dy = poly[i][1] - poly[i - 1][1];
    const L = Math.hypot(dx, dy); seg.push([dx, dy, L]); cum.push(cum[i - 1] + L);
  }
  const offs = [];
  for (let o = -half; o <= half + 1e-9; o += ostep) offs.push(o);
  const pts = []; let nS = 0;
  for (let s = 0; s < cum[cum.length - 1]; s += step) {
    let k = 0; while (k < seg.length - 1 && cum[k + 1] <= s) k++;
    const [dx, dy, L] = seg[k]; const u = (s - cum[k]) / L;
    const px = poly[k][0] + u * dx, py = poly[k][1] + u * dy, nx = -dy / L, ny = dx / L;
    for (const o of offs) pts.push([Math.min(1919, Math.max(0, px + o * nx)), Math.min(1079, Math.max(0, py + o * ny))]);
    nS++;
  }
  return { pts, nS, nO: offs.length };
}

/** 動かない物（岸の壁のふち・大型映像装置のふち）を横切る1画素きざみの線。カメラの揺れを毎コマ測る */
export function landmarkPoints(marks) {
  const pts = [];
  for (const m of marks || []) {
    if (m.kind === 'v') for (let y = m.y[0]; y <= m.y[1]; y++) pts.push([m.x, y]);
    else for (let x = m.x[0]; x <= m.x[1]; x++) pts.push([x, m.y]);
  }
  return pts;
}

export function platePoints({ center: [cx, cy], radius }) {
  const pts = [];
  for (let k = 0; k < 16; k++) { const a = (k / 16) * 2 * Math.PI; pts.push([cx + radius * Math.cos(a), cy + radius * Math.sin(a)]); }
  return pts;
}

function ncc(frame, sig, mask) {
  let mx = 0, my = 0, n = 0;
  for (let i = 0; i < sig.length; i++) if (mask[i]) { mx += frame[i]; my += sig[i]; n++; }
  mx /= n; my /= n;
  let sxy = 0, sxx = 0, syy = 0;
  for (let i = 0; i < sig.length; i++) if (mask[i]) { const a = frame[i] - mx, b = sig[i] - my; sxy += a * b; sxx += a * a; syy += b * b; }
  return sxy / (Math.sqrt(sxx * syy) + 1e-9);
}

/** 場面分け：コマごとに、いちばん相関の高い場面（minCorr 以上）を名前にする。1.5秒以内のすきまはつなぎ、
 *  場面ごとにいちばん長い区間を使う。明るさ（朝・夕）で相関の高さは変わるが、他の場面は 0.3 未満にとどまる */
export function findShots(gray, times, profile) {
  const [w, h] = profile.scan.grid; const n = w * h;
  const masks = Object.fromEntries(Object.entries(profile.shots).map(([name, shot]) => {
    const [r0, r1] = shot.scanRows || [profile.scan.maskTopRows, h - 1];
    return [name, Array.from({ length: n }, (_, i) => Math.floor(i / w) >= r0 && Math.floor(i / w) <= r1)];
  }));
  const sigs = Object.fromEntries(Object.entries(profile.shots).map(([name, shot]) => [name, shot.signature.flat()]));
  const labels = gray.map((fr) => {
    let best = null, bc = -1; const all = {};
    for (const name of Object.keys(profile.shots)) {
      const c = ncc(fr, sigs[name], masks[name]);
      all[name] = c;
      if (c > bc) { bc = c; best = name; }
    }
    return { label: bc >= profile.scan.minCorr ? best : null, corr: bc, all };
  });
  const runs = [];
  for (let f = 0; f < labels.length; f++) {
    const L = labels[f].label;
    if (!L) continue;
    const last = runs[runs.length - 1];
    if (last && last.label === L && times[f] - last.to <= (profile.scan.bridge ?? 1.5)) { last.to = times[f]; last.n++; last.sum += labels[f].corr; }
    else runs.push({ label: L, from: times[f], to: times[f], n: 1, sum: labels[f].corr });
  }
  const segments = runs.map((r) => ({ label: r.label, from: r.from, to: r.to, corr: Math.round((r.sum / r.n) * 1000) / 1000 }));
  const out = {};
  for (const s of segments) {
    if (s.to - s.from < (profile.shots[s.label].minDuration ?? 5)) continue;
    if (!out[s.label] || s.to - s.from > out[s.label].to - out[s.label].from) out[s.label] = s;
  }
  // 見つからなかった場面は、profile の window（いつも映る時刻の範囲）の中だけで、低いしきい値（windowMinCorr）でもう一度さがす。
  // 日や天気で見た目が変わる場（浜名湖など）向け。window の無い場面には効かない
  for (const [name, shot] of Object.entries(profile.shots)) {
    if (out[name] || !shot.window) continue;
    const [w0, w1] = shot.window; const floor = shot.windowMinCorr ?? 0.3;
    let cur = null, best = null;
    for (let f = 0; f < labels.length; f++) {
      const t = times[f];
      if (t < w0 || t > w1) continue;
      const c = labels[f].all[name];
      if (c >= floor && cur && t - cur.to <= (profile.scan.bridge ?? 1.5)) { cur.to = t; cur.n++; cur.sum += c; }
      else if (c >= floor) { cur = { from: t, to: t, n: 1, sum: c }; }
      else continue;
      if (!best || cur.to - cur.from > best.to - best.from) best = cur;
    }
    if (best && best.to - best.from >= (shot.minDuration ?? 5)) {
      out[name] = { label: name, from: best.from, to: best.to, corr: Math.round((best.sum / best.n) * 1000) / 1000, byWindow: true };
    }
  }
  return { shots: out, segments };
}

function frameStats(meta) {
  const fr = meta.filter((m) => m.mt !== undefined);
  let skipped = 0;
  for (let i = 1; i < fr.length; i++) if (fr[i].pf - fr[i - 1].pf !== 1 || fr[i].mt - fr[i - 1].mt > 0.05) skipped++;
  const sizes = [...new Set(fr.map((m) => `${m.w}x${m.h}`))];
  return { frames: fr.length, skipped, sizes, resChanges: meta.filter((m) => m.resChange).length, first: fr[0]?.mt ?? null, last: fr[fr.length - 1]?.mt ?? null };
}

export async function captureRace({ cdp, open }, { date, venue, race, profile, out, log = console.log, keepScan = true, denseRate = 0.5, withPlate = false, shots = null }) {
  const dir = path.join(out, `${date}-${venue}-${String(race).padStart(2, '0')}`);
  mkdirSync(dir, { recursive: true });
  const manifest = { schema: 1, tool: CAPTURE_VERSION, createdAt: nowJst(), date, venue, race, slug: profile.slug, status: 'running', shots: {}, scan: null, failure: null };
  const save = () => writeFileSync(path.join(dir, 'manifest.json'), JSON.stringify(manifest, null, 1));
  try {
    const low = await open(replayUrl({ slug: profile.slug, date, race, bitrate: 'low' }));
    const g = await sampleGrid(cdp, 0, low.duration - 0.2, { rate: 4, w: profile.scan.grid[0], h: profile.scan.grid[1], width: low.width || 854, height: low.height || 480 });
    const n = g.n; const gray = []; const times = [];
    g.meta.filter((m) => m.mt !== undefined).forEach((m, f) => {
      const row = new Array(n);
      for (let i = 0; i < n; i++) row[i] = (g.rgb[(f * n + i) * 3] + g.rgb[(f * n + i) * 3 + 1] + g.rgb[(f * n + i) * 3 + 2]) / 3;
      gray.push(row); times.push(m.mt);
    });
    const found = findShots(gray, times, profile);
    if (keepScan) writeFileSync(path.join(dir, 'scan.json'), JSON.stringify({ times, gray: gray.map((r) => r.map((x) => Math.round(x))) }));
    manifest.scan = { duration: low.duration, frames: times.length, end: g.why, segments: found.segments.filter((s) => s.to - s.from > 1) };
    log(`  ${race}R 場面: ${Object.entries(found.shots).map(([k, s]) => `${k} ${s.from.toFixed(1)}-${s.to.toFixed(1)}s(相関${s.corr})`).join(' / ') || 'なし'}`);
    if (!Object.keys(found.shots).length) throw new Error('固定カメラの場面が見つかりません（profile の signature と合わない）');

    await open(replayUrl({ slug: profile.slug, date, race, bitrate: 'high' }));
    for (const [name, s] of Object.entries(found.shots)) {
      if (shots && !shots.includes(name)) continue;
      const shot = profile.shots[name];
      const p = pathPoints(shot.path, shot.step, shot.half, shot.ostep);
      const plate = shot.plate && withPlate ? platePoints(shot.plate) : [];
      // 細かい横方向（引き波の線の位置）：道すじに沿って fine.every ごと、垂直に 1画素きざみ
      const fine = shot.fine ? pathPoints(shot.path, shot.fine.every, shot.fine.half, shot.fine.ostep) : { pts: [], nS: 0, nO: 0 };
      const land = landmarkPoints(shot.landmarks);
      const channels = shot.channels || 3;
      const r = await samplePoints(cdp, [...p.pts, ...fine.pts, ...land, ...plate], s.from + 0.2, s.to - 0.1, { rate: denseRate, channels });
      writeFileSync(path.join(dir, `${name}.bin`), r.rgb);
      const stats = frameStats(r.meta);
      manifest.shots[name] = { window: [s.from, s.to], corr: s.corr, nS: p.nS, nO: p.nO, nPlate: plate.length, end: r.why, ...stats,
        channels, nFineS: fine.nS, nFineO: fine.nO, nLand: land.length, landmarks: shot.landmarks || [],
        times: r.meta.filter((m) => m.mt !== undefined).map((m) => m.mt) };
      log(`  ${race}R ${name}: ${stats.frames}コマ 抜け${stats.skipped} 解像度${stats.sizes.join(',')}`);
    }
    manifest.status = 'ok';
  } catch (e) {
    manifest.status = 'failed';
    manifest.failure = String(e?.message || e).slice(0, 300);
    log(`  ${race}R 失敗: ${manifest.failure}`);
  }
  save();
  return { dir, manifest };
}

async function main() {
  const a = Object.fromEntries(process.argv.slice(2).join(' ').split('--').filter(Boolean).map((x) => { const [k, ...v] = x.trim().split(/\s+/); return [k, v.join(' ')]; }));
  if (!a.date || !a.venue || !a.out) { console.error('使い方: node measure-capture.mjs --date YYYYMMDD --venue 04 --races 1,2 --out DIR [--rate 0.5] [--shots straight,turn1]'); process.exit(2); }
  const profile = loadProfile(a.venue);
  const races = (a.races || '1,2,3,4,5,6,7,8,9,10,11,12').split(',').map(Number);
  const results = [];
  await withChrome(async (ctx) => {
    for (const race of races) results.push(await captureRace(ctx, { date: a.date, venue: a.venue, race, profile, out: a.out, denseRate: Number(a.rate || 0.5), shots: a.shots ? a.shots.split(',') : null }));
  });
  const ok = results.filter((r) => r.manifest.status === 'ok').length;
  console.log(`取得 ${ok}/${results.length} レース`);
  process.exit(ok ? 0 : 1);
}

if (import.meta.url === `file://${process.argv[1]}`) main().catch((e) => { console.error(e?.message || e); process.exit(1); });
