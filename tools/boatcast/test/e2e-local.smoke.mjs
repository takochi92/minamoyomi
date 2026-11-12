// ローカルでの通しテスト（Chrome と ffmpeg が必要。homesv の実配信は使わない）。
//   node test/e2e-local.smoke.mjs
// テスト用の動画を ffmpeg で作り、Range 対応の小さなサーバーで配信して、capture.mjs / verify.mjs を最後まで動かす。
// ※クラウド上では H.264 が再生できない Chrome があるので、動画は VP9(webm) にしている。実機の H.264 は別途確認すること。

import http from 'node:http';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createReadStream, existsSync, mkdtempSync, readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const tmp = mkdtempSync(path.join(os.tmpdir(), 'boatcast-e2e-'));
const site = path.join(tmp, 'site');
spawnSync('mkdir', ['-p', site]);

const ff = spawnSync('ffmpeg', ['-loglevel', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc=duration=30:size=854x480:rate=15',
  '-c:v', 'libvpx-vp9', '-b:v', '300k', '-pix_fmt', 'yuv420p', path.join(site, 'test.webm')]);
if (ff.status !== 0) { console.log('SKIP: ffmpeg で動画を作れません'); process.exit(0); }
writeFileSync(path.join(site, 'novideo.html'), '<!doctype html><html><body><p>準備中です</p></body></html>');
writeFileSync(path.join(site, 'geo.html'), '<!doctype html><html><body><p>この映像の視聴は許可されていません</p></body></html>');
writeFileSync(path.join(site, 'bad.webm'), Buffer.from('this is not a video file '.repeat(200)));
writeFileSync(path.join(site, 'bad.html'), '<!doctype html><html><body><video src="bad.webm" width="854" height="480" controls></video></body></html>');
writeFileSync(path.join(site, 'page.html'), '<!doctype html><html><body style="margin:0;background:#000"><video src="test.webm" width="854" height="480" controls playsinline></video></body></html>');

const server = http.createServer((req, res) => {
  const u = new URL(req.url, 'http://x');
  const f = path.join(site, path.basename(u.pathname));
  if (!existsSync(f)) { res.writeHead(404).end(); return; }
  const size = statSync(f).size;
  const type = f.endsWith('.webm') ? 'video/webm' : 'text/html; charset=utf-8';
  const m = /bytes=(\d*)-(\d*)/.exec(req.headers.range || '');
  if (m) {
    const start = m[1] ? Number(m[1]) : 0;
    const end = m[2] ? Math.min(Number(m[2]), size - 1) : size - 1;
    res.writeHead(206, { 'Content-Type': type, 'Accept-Ranges': 'bytes', 'Content-Range': `bytes ${start}-${end}/${size}`, 'Content-Length': end - start + 1 });
    createReadStream(f, { start, end }).pipe(res);
  } else {
    res.writeHead(200, { 'Content-Type': type, 'Accept-Ranges': 'bytes', 'Content-Length': size });
    createReadStream(f).pipe(res);
  }
});
await new Promise((r) => server.listen(0, '127.0.0.1', r));
const url = `http://127.0.0.1:${server.address().port}/page.html?token=SECRET123`;
const env = { ...process.env, BOATCAST_PROFILE: path.join(tmp, 'profile'), BOATCAST_OUT: path.join(tmp, 'out') };
const port = String(9470 + Math.floor(Math.random() * 20));

import { spawn } from 'node:child_process';
const runAsync = (script, args) => new Promise((resolve) => {
  const c = spawn(process.execPath, [path.join(here, script), ...args], { env, encoding: 'utf8' });
  let out = '';
  c.stdout.on('data', (d) => { out += d; });
  c.stderr.on('data', (d) => { out += d; });
  c.on('close', (code) => resolve({ code, out }));
});

try {
  const cap = await runAsync('capture.mjs', ['--date', '20261112', '--race', '12', '--seconds', '3,10,20,100', '--port', port, '--player-url', url]);
  console.log(cap.out);
  assert.equal(cap.code, 0, 'capture が失敗');
  assert.ok(!cap.out.includes('SECRET123'), 'トークンがログに残っている');
  const dirs = readdirSync(path.join(tmp, 'out'));
  assert.deepEqual(dirs, ['20261112-custom-12']);
  const d = path.join(tmp, 'out', dirs[0]);
  const manifest = JSON.parse(readFileSync(path.join(d, 'manifest.json'), 'utf8'));
  assert.ok(!JSON.stringify(manifest).includes('SECRET123'), 'トークンが manifest に残っている');
  assert.equal(manifest.status, 'ok');
  assert.equal(manifest.video.duration, 30);
  assert.equal(manifest.playback.progressed, true);
  assert.equal(manifest.frames.length, 4);
  assert.ok(manifest.frames.every((f) => f.seekOk && existsSync(path.join(d, f.file)) && f.bytes > 1000), 'フレームのシーク位置または保存に問題');
  assert.equal(manifest.frames[3].clamped, true);

  const cap2 = await runAsync('capture.mjs', ['--date', '20261112', '--race', '12', '--seconds', '3', '--port', port, '--player-url', url]);
  assert.equal(cap2.code, 0);
  assert.deepEqual(readdirSync(path.join(tmp, 'out')).sort(), ['20261112-custom-12', '20261112-custom-12-2'], '既存の出力先を壊さず -2 が作られること');

  const ver = await runAsync('verify.mjs', ['--date', '20261112', '--race', '12', '--port', port, '--player-url', url]);
  console.log(ver.out);
  assert.equal(ver.code, 0);
  assert.match(ver.out, /RESULT: PASS/);
  assert.ok(!ver.out.includes('SECRET123'));

  // 失敗の段階の分類（実際にページを開いて確かめる）
  const stageOf = async (page, extra = []) => {
    const base = `http://127.0.0.1:${server.address().port}/${page}?token=SECRET123`;
    const r = await runAsync('capture.mjs', ['--date', '20261112', '--race', '12', '--seconds', '3', '--port', port, '--video-timeout', '4', '--player-url', base, ...extra]);
    assert.notEqual(r.code, 0, `${page} は失敗するはず`);
    assert.ok(!r.out.includes('SECRET123'));
    const names = readdirSync(path.join(tmp, 'out')).filter((n) => !['20261112-custom-12', '20261112-custom-12-2'].includes(n)).sort();
    const m = JSON.parse(readFileSync(path.join(tmp, 'out', names.at(-1), 'manifest.json'), 'utf8'));
    assert.equal(m.status, 'failed');
    return m.failure.stage;
  };
  assert.equal(await stageOf('novideo.html'), 'player-load');
  assert.equal(await stageOf('geo.html'), 'geo');
  assert.equal(await stageOf('bad.html'), 'decode');
  // cdp：ポート競合（使用中のポートは落とさず、cdp 段階で止まる）
  const blocker = http.createServer().listen(0, '127.0.0.1');
  await new Promise((r) => blocker.once('listening', r));
  const busy = blocker.address().port;
  const r = await runAsync('capture.mjs', ['--date', '20261112', '--race', '12', '--port', String(busy), '--player-url', url]);
  blocker.close();
  assert.notEqual(r.code, 0);
  assert.match(r.out, /\[cdp\]/);
  assert.match(r.out, /--port/);
  console.log('E2E OK');
} finally {
  server.close();
}
