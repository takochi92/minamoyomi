import test from 'node:test';
import assert from 'node:assert/strict';
import { parseCaptureArgs, parseVerifyArgs, parseSeconds, ArgError, DEFAULT_SECONDS, DEFAULT_PORT, DEFAULT_PROFILE, todayJst } from '../args.mjs';

const ENV = {};

test('既定値：秒数・ポート 9454・プロファイル', () => {
  const a = parseCaptureArgs(['--date', '20261112', '--race', '12'], ENV);
  assert.deepEqual(a.seconds, DEFAULT_SECONDS);
  assert.deepEqual(DEFAULT_SECONDS, [10, 60, 120, 180, 200, 240, 280, 320]);
  assert.equal(a.port, DEFAULT_PORT);
  assert.equal(a.port, 9454);
  assert.equal(a.profile, DEFAULT_PROFILE);
  assert.equal(a.mode, 'seek');
  assert.deepEqual(a.races, [12]);
});

test('レース番号は複数指定できる（--race 繰り返し / --races カンマ区切り）', () => {
  assert.deepEqual(parseCaptureArgs(['--date=20261112', '--race', '11', '--race', '12'], ENV).races, [11, 12]);
  assert.deepEqual(parseCaptureArgs(['--date', '20261112', '--races', '10,11, 12'], ENV).races, [10, 11, 12]);
  assert.deepEqual(parseCaptureArgs(['--date', '20261112', '--races', '12,12,11'], ENV).races, [12, 11]);
});

test('秒数は並べ替え・重複除去。負数や文字は拒否', () => {
  assert.deepEqual(parseSeconds('60,10,10,12.5'), [10, 12.5, 60]);
  assert.throws(() => parseSeconds('10,-1'), ArgError);
  assert.throws(() => parseSeconds('abc'), ArgError);
  assert.deepEqual(parseCaptureArgs(['--date', '20261112', '--race', '1', '--seconds', '5,30'], ENV).seconds, [5, 30]);
});

test('ポートとプロファイルは引数・環境変数で変えられる（引数が優先）', () => {
  assert.equal(parseCaptureArgs(['--date', '20261112', '--race', '1', '--port', '9455'], ENV).port, 9455);
  const e = { BOATCAST_PORT: '9460', BOATCAST_PROFILE: '/tmp/p', BOATCAST_OUT: '/tmp/o' };
  const a = parseCaptureArgs(['--date', '20261112', '--race', '1'], e);
  assert.deepEqual([a.port, a.profile, a.out], [9460, '/tmp/p', '/tmp/o']);
  assert.equal(parseCaptureArgs(['--date', '20261112', '--race', '1', '--port', '9461'], e).port, 9461);
});

test('9447 / 9453 は他用途なので拒否', () => {
  assert.throws(() => parseCaptureArgs(['--date', '20261112', '--race', '1', '--port', '9447'], ENV), /艇ろぐ投稿ジョブ/);
  assert.throws(() => parseCaptureArgs(['--date', '20261112', '--race', '1', '--port', '9453'], ENV), /Codex/);
  assert.throws(() => parseCaptureArgs(['--date', '20261112', '--race', '1', '--port', '80'], ENV), ArgError);
});

test('入力の誤りは ArgError', () => {
  assert.throws(() => parseCaptureArgs(['--race', '12'], ENV), /--date/);
  assert.throws(() => parseCaptureArgs(['--date', '20261399', '--race', '12'], ENV), ArgError);
  assert.throws(() => parseCaptureArgs(['--date', '20261112'], ENV), /レース番号/);
  assert.throws(() => parseCaptureArgs(['--date', '20261112', '--race', '13'], ENV), ArgError);
  assert.throws(() => parseCaptureArgs(['--date', '20261112', '--race', '1', '--mode', 'x'], ENV), ArgError);
  assert.throws(() => parseCaptureArgs(['--date', '20261112', '--race', '1', '--port'], ENV), /値がありません/);
  assert.throws(() => parseCaptureArgs(['stray'], ENV), /解釈できない/);
});

test('フラグ類：--attach --dry-run --chrome', () => {
  const a = parseCaptureArgs(['--date', '20261112', '--race', '1', '--attach', '--dry-run', '--chrome', '/x/chrome'], ENV);
  assert.deepEqual([a.attach, a.dryRun, a.chrome], [true, true, '/x/chrome']);
  assert.deepEqual(parseCaptureArgs(['--date', '20261112', '--race', '1'], { BOATCAST_CHROME_ARGS: '--no-sandbox --foo' }).extraChromeArgs, ['--no-sandbox', '--foo']);
});

test('--date today は日本時間の今日', () => {
  assert.equal(parseCaptureArgs(['--date', 'today', '--race', '1'], ENV).date, todayJst());
  assert.equal(todayJst(new Date('2026-11-12T16:00:00Z')), '20261113');   // UTC 16:00 = JST 翌日 01:00
  assert.equal(todayJst(new Date('2026-11-12T14:59:00Z')), '20261112');
});

test('verify の引数：既定は今日の12R', () => {
  const v = parseVerifyArgs([], ENV);
  assert.equal(v.race, 12);
  assert.equal(v.date, todayJst());
  assert.equal(v.port, 9454);
  assert.equal(parseVerifyArgs(['--race', '3', '--date', '20261112'], ENV).race, 3);
});

test('--video-timeout は秒で受け取りミリ秒にする（既定 45 秒）', () => {
  assert.equal(parseCaptureArgs(['--date', '20261112', '--race', '1'], ENV).videoTimeoutMs, 45000);
  assert.equal(parseCaptureArgs(['--date', '20261112', '--race', '1', '--video-timeout', '5'], ENV).videoTimeoutMs, 5000);
  assert.throws(() => parseCaptureArgs(['--date', '20261112', '--race', '1', '--video-timeout', '0'], ENV), ArgError);
});

test('--frame-tolerance は秒（既定 0.5）', () => {
  assert.equal(parseCaptureArgs(['--date', '20261112', '--race', '1'], ENV).frameToleranceSec, 0.5);
  assert.equal(parseCaptureArgs(['--date', '20261112', '--race', '1', '--frame-tolerance', '0.2'], ENV).frameToleranceSec, 0.2);
  assert.throws(() => parseCaptureArgs(['--date', '20261112', '--race', '1', '--frame-tolerance', '-1'], ENV), ArgError);
});
