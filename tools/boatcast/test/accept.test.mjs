import test from 'node:test';
import assert from 'node:assert/strict';
import { evaluatePair, evaluateSpread } from '../accept.mjs';

const f = (file, mt, extra = {}) => ({ file, measurable: true, frame: { mediaTime: mt }, playerPosition: { afterShot: mt }, ...extra });

test('近い2つの秒：同じコマなら、重複の印と「計測値1つ」が必要', () => {
  const ok = { status: 'ok', frames: [f('a', 248.166667), f('b', 248.166667, { duplicateOf: 'a' })], measurement: { independentMeasurements: 1 } };
  assert.deepEqual([evaluatePair(ok).ok, evaluatePair(ok).sameFrame], [true, true]);
  const ng = { status: 'ok', frames: [f('a', 248.166667), f('b', 248.166667)], measurement: { independentMeasurements: 2 } };
  assert.equal(evaluatePair(ng).ok, false);
});

test('近い2つの秒：別のコマでも合格。計測不可や失敗は不合格', () => {
  assert.equal(evaluatePair({ status: 'ok', frames: [f('a', 1), f('b', 1.2)], measurement: { independentMeasurements: 2 } }).ok, true);
  assert.equal(evaluatePair({ status: 'partial', frames: [f('a', 1), f('b', null, { measurable: false, notMeasurableReasons: ['frame-time-unavailable'] })] }).ok, false);
  assert.equal(evaluatePair(null).ok, false);
});

test('離れた秒：全部が計測可で別々のコマ', () => {
  assert.equal(evaluateSpread({ status: 'ok', frames: [f('a', 10), f('b', 60), f('c', 120)], measurement: { uniqueFrames: 3 } }, 3).ok, true);
  assert.equal(evaluateSpread({ status: 'ok', frames: [f('a', 10), f('b', 60)], measurement: { uniqueFrames: 2 } }, 3).ok, false);
});
