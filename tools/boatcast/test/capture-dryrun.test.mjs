import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const dir = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const run = (script, args, env = {}) => spawnSync(process.execPath, [path.join(dir, script), ...args], { encoding: 'utf8', env: { ...process.env, ...env } });

test('capture --dry-run は Chrome を起動せず、URL をクエリなしで表示して 0 で終わる', () => {
  const r = run('capture.mjs', ['--date', '20261112', '--races', '11,12', '--dry-run', '--out', '/tmp/boatcast-dry']);
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stdout, /https:\/\/front\.player\.boatrace-cdn\.jp\/player\/vod/);
  assert.ok(!r.stdout.includes('?'), 'クエリ文字列が出力に残っている');
  assert.ok(!r.stdout.includes('raceDate='));
  assert.match(r.stdout, /--disable-accelerated-video-decode/);
  assert.match(r.stdout, /20261112-heiwajima-12/);
});

test('capture：未検証の場は引数エラー（終了コード 2）', () => {
  const r = run('capture.mjs', ['--date', '20261112', '--race', '1', '--venue', '03', '--dry-run'], { BOATCAST_STADIUMS: 'none' });
  assert.equal(r.status, 2);
  assert.match(r.stderr, /未検証/);
});

test('capture：レース番号なしは引数エラー（終了コード 2）と使い方', () => {
  const r = run('capture.mjs', ['--date', '20261112']);
  assert.equal(r.status, 2);
  assert.match(r.stderr, /使い方/);
});

test('capture --help は 0', () => {
  assert.equal(run('capture.mjs', ['--help']).status, 0);
  assert.equal(run('verify.mjs', ['--help']).status, 0);
});

test('--player-url に渡したトークン付きURLも、出力にはクエリを残さない', () => {
  const r = run('capture.mjs', ['--date', '20261112', '--race', '1', '--dry-run', '--player-url', 'http://127.0.0.1:8080/page.html?token=SECRET123']);
  assert.equal(r.status, 0, r.stderr);
  assert.ok(!(r.stdout + r.stderr).includes('SECRET123'));
  assert.match(r.stdout, /http:\/\/127\.0\.0\.1:8080\/page\.html/);
});
