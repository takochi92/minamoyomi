import test from 'node:test';
import assert from 'node:assert/strict';
import { pathPoints, findShots } from '../measure-capture.mjs';

test('pathPoints: s が外側、垂直方向に half ごと。python 側と同じ並び', () => {
  const p = pathPoints([[100, 100], [100, 140]], 10, 4, 4);
  assert.equal(p.nS, 4);
  assert.equal(p.nO, 3);
  assert.deepEqual(p.pts.slice(0, 3).map(([x, y]) => [Math.round(x), Math.round(y)]), [[104, 100], [100, 100], [96, 100]]);
  assert.deepEqual(p.pts[3].map(Math.round), [104, 110]);
});

function profile() {
  const w = 4, h = 3;
  const a = Array.from({ length: w * h }, (_, i) => (i * 37) % 200);
  const b = Array.from({ length: w * h }, (_, i) => (i * 91) % 200);
  return { profile: { scan: { grid: [w, h], maskTopRows: 0, minCorr: 0.4, bridge: 1.5 },
    shots: { turn1: { signature: a, minDuration: 2 }, straight: { signature: b, minDuration: 2 } } }, a, b };
}

test('findShots: 似ている場面を名前づけし、短いすきまはつなぎ、いちばん長い区間を使う', () => {
  const { profile: p, a, b } = profile();
  const noise = Array.from({ length: 12 }, (_, i) => (i % 2) * 255);
  const frames = [], times = [];
  const push = (fr, n) => { for (let i = 0; i < n; i++) { frames.push(fr); times.push(times.length / 10); } };
  push(noise, 20); push(a, 30); push(noise, 5); push(a, 20); push(noise, 30); push(b, 40);
  const r = findShots(frames, times, p);
  assert.equal(r.shots.turn1.from, 2.0);
  assert.equal(r.shots.turn1.to, 7.4);            // 0.5 秒のすきまはつながる
  assert.equal(r.shots.straight.from, 10.5);
});

test('findShots: どれにも似ていなければ何も返さない', () => {
  const { profile: p } = profile();
  const flat = Array.from({ length: 50 }, () => Array.from({ length: 12 }, (_, k) => (k % 2) * 255));
  const r = findShots(flat, flat.map((_, i) => i / 10), p);
  assert.deepEqual(Object.keys(r.shots), []);
});

test('findShots: しきい値に届かなくても、window の中なら低いしきい値で場面を取る（window の無い場面は取らない）', () => {
  const { profile: p, a } = profile();
  // a に少しだけ似たコマ（相関 0.4 未満・0.3 以上）
  const weak = a.map((x, i) => (i % 3 === 0 ? 255 - x : x));
  const noise = Array.from({ length: 12 }, (_, i) => (i % 2) * 255);
  const frames = [], times = [];
  const push = (fr, n) => { for (let i = 0; i < n; i++) { frames.push(fr); times.push(times.length / 10); } };
  push(noise, 20); push(weak, 40); push(noise, 20);
  assert.deepEqual(Object.keys(findShots(frames, times, p).shots), []);
  p.shots.turn1.window = [1, 7]; p.shots.turn1.windowMinCorr = 0.1;
  const r = findShots(frames, times, p);
  assert.equal(r.shots.turn1.byWindow, true);
  assert.equal(r.shots.turn1.from, 2.0);
  assert.equal(r.shots.straight, undefined);
});

test('findShots: altSignatures（昼と夜の見た目）のどれかに似ていれば同じ場面とみなす', () => {
  const { profile: p, a, b } = profile();
  delete p.shots.straight;
  const frames = [], times = [];
  const push = (fr, n) => { for (let i = 0; i < n; i++) { frames.push(fr); times.push(times.length / 10); } };
  push(b, 30);
  assert.deepEqual(Object.keys(findShots(frames, times, p).shots), []);
  p.shots.turn1.altSignatures = [b];
  assert.equal(findShots(frames, times, p).shots.turn1.from, 0);
});
