import test from 'node:test';
import assert from 'node:assert/strict';
import { classifyFailure, StageError, HINTS, GEO_TEXT_RE } from '../failures.mjs';

const okVideo = { has: true, duration: 348 };

test('decode：PIPELINE_ERROR_DECODE は起動フラグ不足を案内する', () => {
  const c = classifyFailure({ video: { has: true, duration: NaN, error: { code: 3, message: 'PIPELINE_ERROR_DECODE: video decode error' } } });
  assert.equal(c.stage, 'decode');
  assert.match(c.hint, /--disable-accelerated-video-decode/);
});

test('geo：メディアの 403 は国内IPでない可能性を案内する', () => {
  const c = classifyFailure({ video: { has: true, duration: NaN }, httpErrors: [{ host: 'cdn.example', path: '/vod/seg_1.ts', status: 403 }] });
  assert.equal(c.stage, 'geo');
  assert.match(c.hint, /日本国内/);
  assert.match(c.cause, /403/);
});

test('geo：画面の視聴不可の文言', () => {
  assert.equal(classifyFailure({ video: { has: false }, pageText: 'この映像の視聴は許可されていません' }).stage, 'geo');
  assert.ok(GEO_TEXT_RE.test('お住まいの地域では視聴できません'));
});

test('geo より decode：無関係なパスの 403 しかなく decode エラーなら decode', () => {
  const c = classifyFailure({ video: { has: true, duration: NaN, error: { code: 3, message: 'PIPELINE_ERROR_DECODE' } }, httpErrors: [{ host: 'ad.example', path: '/pixel.gif', status: 403 }] });
  assert.equal(c.stage, 'decode');
});

test('player-load：video が無い／duration が NaN', () => {
  assert.equal(classifyFailure({ video: { has: false } }).stage, 'player-load');
  const c = classifyFailure({ video: { has: true, duration: NaN } });
  assert.equal(c.stage, 'player-load');
  assert.match(c.hint, /未開催|未公開/);
});

test('cdp：対象ページが取れない／ポート競合', () => {
  const c = classifyFailure({ cdpError: 'ECONNREFUSED' });
  assert.equal(c.stage, 'cdp');
  assert.match(c.hint, /--port/);
  assert.match(HINTS.cdp, /9447/);
});

test('StageError は stage・cause・hint を持ち、メッセージのクエリを伏せる', () => {
  const e = new StageError('geo', '取得失敗 https://cdn.example/seg.ts?token=SECRET');
  assert.equal(e.stage, 'geo');
  assert.ok(!e.message.includes('SECRET'));
  assert.ok(!JSON.stringify(e.toJSON()).includes('SECRET'));
  assert.ok(e.hint.length > 0);
});

test('正常な動画はここでは分類しない前提（duration が正なら player-load 扱いの最後の分岐）', () => {
  assert.equal(classifyFailure({ video: okVideo }).stage, 'player-load');
});
