import test from 'node:test';
import assert from 'node:assert/strict';
import { judgeFrame, markDuplicates, mediaTimeKey, sha256, summarizeManifest } from '../frames.mjs';
import { formatReport } from '../report.mjs';
import { judgePlayback, MIN_FRAMES_IN_WINDOW } from '../verify.mjs';

const fr = (mediaTime, extra = {}) => ({ supported: true, mediaTime, presentedFrames: 100, ...extra });
const seekOk = (target, mediaTime, o = {}) => judgeFrame({ mode: 'seek', targetSec: target, frame: fr(mediaTime), seeked: true, stable: true, ...o });

test('指定秒の近くのフレームで、撮影の前後で変わっていなければ計測可', () => {
  const j = seekOk(248.197, 248.166667);
  assert.equal(j.measurable, true);
  assert.deepEqual(j.reasons, []);
  assert.ok(Math.abs(j.frameOffsetSec - (-0.030333)) < 1e-6);
});

test('表示フレームの時刻が取れなければ計測可にしない', () => {
  const a = judgeFrame({ mode: 'seek', targetSec: 10, frame: { supported: false, mediaTime: null }, seeked: true, stable: true });
  assert.equal(a.measurable, false);
  assert.deepEqual(a.reasons, ['frame-time-unavailable']);
  const b = judgeFrame({ mode: 'seek', targetSec: 10, frame: fr(NaN), seeked: true, stable: true });
  assert.ok(b.reasons.includes('frame-time-unavailable'));
});

test('別のコマを撮った可能性（撮影中にフレームが変わった／指定秒から遠い）は計測可にしない', () => {
  assert.deepEqual(seekOk(10, 10, { stable: false }).reasons, ['frame-changed-during-capture']);
  assert.deepEqual(seekOk(10, 12.5).reasons, ['frame-time-off-target']);      // 先のコマ
  assert.deepEqual(seekOk(10, 9.0).reasons, ['frame-time-off-target']);       // 手前すぎるコマ
  assert.deepEqual(seekOk(10, 9.6).reasons, []);                              // 許容内（0.5秒前まで）
  assert.deepEqual(seekOk(10, 9.6, { toleranceBefore: 0.2 }).reasons, ['frame-time-off-target']);
});

test('seeked を確認できなければ計測可にしない', () => {
  assert.deepEqual(seekOk(10, 10, { seeked: false }).reasons, ['seek-not-completed']);
});

test('play モード：撮影中にフレームが進んだら、画像とフレーム時刻の対応を確認できないので計測可にしない', () => {
  const ok = judgeFrame({ mode: 'play', targetSec: 10, frame: fr(10.5), seeked: true, stable: true });
  assert.equal(ok.measurable, true);                        // 前後で最後のフレームが同じ＝画像はそのフレーム
  const ng = judgeFrame({ mode: 'play', targetSec: 10, frame: fr(null, { ambiguous: true }), seeked: true, stable: false });
  assert.equal(ng.measurable, false);
  assert.deepEqual(ng.reasons, ['play-frame-range-only']);  // 「時刻が取れない」は重ねて出さない
});

test('フレーム時刻を監視できないとき（stable=null）は、時刻が取れない理由だけを出す', () => {
  const j = judgeFrame({ mode: 'seek', targetSec: 10, frame: { supported: false, mediaTime: null }, seeked: true, stable: null });
  assert.deepEqual(j.reasons, ['frame-time-unavailable']);
});

const img = (file, requestedSec, mediaTime, sha, measurable = true) => ({ file, requestedSec, measurable, sha256: sha, frame: fr(mediaTime), notMeasurableReasons: measurable ? [] : ['x'] });

test('同じ mediaTime の画像は同じコマ。指定秒や再生位置が違っても、独立した計測値は1つ', () => {
  const frames = [img('a.png', 248.167, 248.166667, 'H1'), img('b.png', 248.197, 248.166667, 'H1'), img('c.png', 250, 250.0, 'H2')];
  const m = markDuplicates(frames);
  assert.equal(frames[0].independentMeasurement, true);
  assert.equal(frames[1].independentMeasurement, false);
  assert.equal(frames[1].duplicateOf, 'a.png');
  assert.equal(frames[1].frameId, frames[0].frameId);
  assert.equal(m.uniqueFrames, 2);
  assert.equal(m.independentMeasurements, 2);
  assert.equal(m.duplicates.length, 1);
  assert.deepEqual(m.duplicates[0].requestedSecs, [248.167, 248.197]);
  assert.equal(m.duplicates[0].identicalImages, true);
  assert.deepEqual(m.anomalies, []);
});

test('計測可でない画像は、同じコマのグループに入れない', () => {
  const frames = [img('a.png', 10, 10, 'H1'), img('b.png', 10.1, 10, 'H1', false)];
  const m = markDuplicates(frames);
  assert.equal(frames[1].frameId, null);
  assert.equal(m.measurableImages, 1);
  assert.equal(m.duplicates.length, 0);
  assert.equal(m.notMeasurable[0].file, 'b.png');
});

test('同じ mediaTime で画像が違うのは、同じコマ（シークバー等の違い）。警告にはしない', () => {
  const a = markDuplicates([img('a.png', 10, 10, 'H1'), img('b.png', 10.1, 10, 'H2')]);
  assert.deepEqual(a.anomalies, []);
  assert.equal(a.duplicates[0].identicalImages, false);
  assert.match(a.duplicates[0].note, /同じコマ/);
  assert.equal(a.uniqueFrames, 1);
});

test('画像が同じなのに mediaTime が違うときは警告（古い画面を撮った疑い）', () => {
  const b = markDuplicates([img('a.png', 10, 10, 'H1'), img('b.png', 12, 12, 'H1')]);
  assert.equal(b.anomalies[0].kind, 'same-image-different-mediaTime');
});

test('mediaTimeKey はマイクロ秒で丸める', () => {
  assert.equal(mediaTimeKey(248.1666670001), mediaTimeKey(248.166667));
  assert.equal(mediaTimeKey(null), null);
  assert.equal(mediaTimeKey(NaN), null);
});

test('sha256 は同じバイト列で同じ値', () => {
  assert.equal(sha256(Buffer.from('a')), sha256(Buffer.from('a')));
  assert.notEqual(sha256(Buffer.from('a')), sha256(Buffer.from('b')));
});

test('manifest の要約と表示（report）：問題のある画像を指摘する', () => {
  const frames = [img('a.png', 248.167, 248.166667, 'AAAAAAAAAAAAAAAA'), img('b.png', 248.197, 248.166667, 'AAAAAAAAAAAAAAAA'), img('c.png', 300, 300, 'C', false)];
  const measurement = markDuplicates(frames);
  frames.forEach((f) => { f.playerPosition = { afterShot: f.requestedSec }; });
  const manifest = { date: '20261112', venue: { name: '平和島' }, race: 12, status: 'partial', mode: 'seek', video: { duration: 348, width: 854, height: 480 }, frames, measurement };
  const { rows, problems } = summarizeManifest(manifest);
  assert.equal(rows.length, 3);
  assert.ok(problems.some((p) => p.includes('c.png')));
  const out = formatReport(manifest).text;
  assert.match(out, /= a\.png/);
  assert.match(out, /別々のコマ 1/);
});

test('verify の判定：読込直後は 0x0 でも、再生後のサイズ・フレーム数を別に見る', () => {
  const good = judgePlayback({
    before: { currentTime: 1 }, after: { currentTime: 6.2, width: 854, height: 480 },
    probeBefore: { supported: true, seq: 10, quality: { total: 30 } }, probeAfter: { supported: true, seq: 160, quality: { total: 180 } },
  });
  assert.deepEqual([good.advanceOk, good.sizeOk, good.framesOk], [true, true, true]);
  const zero = judgePlayback({
    before: { currentTime: 1 }, after: { currentTime: 6, width: 0, height: 0 },
    probeBefore: { supported: true, seq: 10, quality: { total: 30 } }, probeAfter: { supported: true, seq: 160, quality: { total: 180 } },
  });
  assert.equal(zero.sizeOk, false);
  assert.equal(zero.advanceOk, true);          // currentTime だけ進んで映像が出ていないケース
  const still = judgePlayback({
    before: { currentTime: 1 }, after: { currentTime: 6, width: 854, height: 480 },
    probeBefore: { supported: true, seq: 10, quality: { total: 30 } }, probeAfter: { supported: true, seq: 10, quality: { total: 30 } },
  });
  assert.equal(still.framesOk, false);         // フレームが増えていない
  const half = judgePlayback({
    before: { currentTime: 1 }, after: { currentTime: 6, width: 854, height: 480 },
    probeBefore: { supported: true, seq: 10, quality: { total: 30 } }, probeAfter: { supported: true, seq: 160, quality: { total: 30 } },
  });
  assert.equal(half.framesOk, false);          // 片方でも増えていなければ OK にしない
  const unknown = judgePlayback({ before: { currentTime: 1 }, after: { currentTime: 6, width: 854, height: 480 }, probeBefore: { supported: false }, probeAfter: { supported: false } });
  assert.equal(unknown.framesMeasured, false);
  assert.equal(unknown.framesOk, false);
  assert.ok(MIN_FRAMES_IN_WINDOW >= 1);
});
