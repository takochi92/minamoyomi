// ローカルでの通しテスト（Chrome と ffmpeg が必要。homesv にも実際の配信にも接続しない）。
//   node tools/boatcast/test/e2e-local.smoke.mjs
// テスト用の動画を ffmpeg で作り、Range 対応の小さなサーバーで配信して、capture.mjs / verify.mjs を最後まで動かす。
//
// 確かめること
//   A 通常：フレーム保存・manifest（指定秒 / 再生位置 / 表示フレーム mediaTime が別々）・既存を壊さない出力先・verify 9/9
//   B 異なる指定秒が同じコマに当たる（5fps の動画で 10.02s と 10.10s）→ 同じ mediaTime・同じ画像・独立した計測値は1つ
//   C 別のコマを撮る（seeked のあとにページが勝手に再生を進める）→ 計測可にしない
//   D 表示フレーム時刻が取れない（requestVideoFrameCallback が無い）→ 計測可にしない（画像は保存する）
//   E play モード：撮影中にフレームが進んだ画像を、計測可にしない
//   F verify：映像サイズ 0×0・フレームが増えない映像（音声だけの動画）を FAIL にする
//   G 失敗の段階：player-load / forbidden / decode / cdp
// ※クラウド上の Chrome では H.264 が再生できないことがあるため、動画は VP9(webm)。実機の H.264 は別途確認すること。

import http from 'node:http';
import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import { createReadStream, existsSync, mkdtempSync, readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const tmp = mkdtempSync(path.join(os.tmpdir(), 'boatcast-e2e-'));
const site = path.join(tmp, 'site');
spawnSync('mkdir', ['-p', site]);

const ff = (args) => spawnSync('ffmpeg', ['-loglevel', 'error', '-y', ...args]);
const made = [
  ff(['-f', 'lavfi', '-i', 'testsrc=duration=30:size=854x480:rate=15', '-c:v', 'libvpx-vp9', '-b:v', '300k', '-pix_fmt', 'yuv420p', path.join(site, 'test.webm')]),
  ff(['-f', 'lavfi', '-i', 'testsrc=duration=30:size=854x480:rate=5', '-c:v', 'libvpx-vp9', '-b:v', '300k', '-pix_fmt', 'yuv420p', path.join(site, 'slow.webm')]),
  ff(['-f', 'lavfi', '-i', 'sine=frequency=440:duration=30', '-c:a', 'libopus', path.join(site, 'audio.webm')]),
];
if (made.some((r) => r.status !== 0)) { console.log('SKIP: ffmpeg で動画を作れません'); process.exit(0); }

const page = (body, head = '') => `<!doctype html><html><head><meta charset="utf-8">${head}</head><body style="margin:0;background:#000">${body}</body></html>`;
const vid = (src, controls = false) => `<video id="v" src="${src}" width="854" height="480"${controls ? ' controls' : ''} playsinline></video>`;
const pages = {
  'page.html': page(vid('test.webm')),
  'slow.html': page(vid('slow.webm')),                       // シークバーなし（画像はフレームだけで決まる）
  'slowctl.html': page(vid('slow.webm', true)),              // シークバーあり（再生位置で画像の見た目が変わる）
  // seeked のあとに勝手に再生を進める（撮影中に別のコマになる）
  'drift.html': page(vid('test.webm') + '<script>const v=document.getElementById("v");v.addEventListener("seeked",()=>setTimeout(()=>{v.play()},60));</script>'),
  // requestVideoFrameCallback が使えない
  'noframe.html': page(vid('test.webm'), '<script>HTMLVideoElement.prototype.requestVideoFrameCallback=undefined;</script>'),
  // 同じコマの上へ再シークしても、新しいフレームの通知が出ない（実機の Chrome でそうなる可能性）ようにする → 別位置から戻して取得する経路
  'slowdup.html': page(vid('slow.webm'), '<script>(()=>{const orig=HTMLVideoElement.prototype.requestVideoFrameCallback;let last=null;HTMLVideoElement.prototype.requestVideoFrameCallback=function(cb){return orig.call(this,(now,md)=>{if(md.mediaTime===last){this.requestVideoFrameCallback(cb);return;}last=md.mediaTime;cb(now,md);});};})();</script>'),
  'audio.html': page(vid('audio.webm')),
  'novideo.html': page('<p>準備中です</p>'),
  'denied.html': page('<p>この映像の視聴は許可されていません</p>'),
  'bad.html': page(vid('bad.webm')),
};
for (const [n, h] of Object.entries(pages)) writeFileSync(path.join(site, n), h);
writeFileSync(path.join(site, 'bad.webm'), Buffer.from('this is not a video file '.repeat(200)));

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
const base = `http://127.0.0.1:${server.address().port}`;
const U = (name) => `${base}/${name}?token=SECRET123`;
const env = { ...process.env, BOATCAST_PROFILE: path.join(tmp, 'profile'), BOATCAST_OUT: path.join(tmp, 'out') };
const port = String(9470 + Math.floor(Math.random() * 20));

const runAsync = (script, args) => new Promise((resolve) => {
  const c = spawn(process.execPath, [path.join(here, script), ...args], { env });
  let out = '';
  c.stdout.on('data', (d) => { out += d; });
  c.stderr.on('data', (d) => { out += d; });
  c.on('close', (code) => resolve({ code, out }));
});
const cap = (page, extra = []) => runAsync('capture.mjs', ['--date', '20261112', '--race', '12', '--port', port, '--player-url', U(page), ...extra]);
const newest = () => {
  const names = readdirSync(path.join(tmp, 'out')).map((n) => ({ n, t: statSync(path.join(tmp, 'out', n)).mtimeMs })).sort((a, b) => a.t - b.t);
  return path.join(tmp, 'out', names.at(-1).n);
};
const manifestOf = (dir) => JSON.parse(readFileSync(path.join(dir, 'manifest.json'), 'utf8'));
const noSecret = (...s) => s.forEach((x) => assert.ok(!String(x).includes('SECRET123'), 'トークンが出力に残っている'));

try {
  // A 通常
  let r = await cap('page.html', ['--seconds', '3,10,20,100']);
  console.log(r.out);
  assert.equal(r.code, 0, 'A: capture が失敗');
  let dir = newest();
  let m = manifestOf(dir);
  noSecret(r.out, JSON.stringify(m));
  assert.equal(m.schema, 2);
  assert.equal(m.status, 'ok');
  assert.equal(m.frames.length, 4);
  for (const f of m.frames) {
    assert.ok(f.measurable, `${f.file}: 計測可のはず（${f.notMeasurableReasons}）`);
    assert.ok(Number.isFinite(f.frame.mediaTime) && Number.isFinite(f.playerPosition.afterShot), '3つの時刻が別々に記録される');
    assert.ok(f.frame.presentedFrames >= 0 && f.sha256.length === 64);
    assert.ok(existsSync(path.join(dir, f.file)) && f.bytes > 1000);
  }
  assert.ok(Math.abs(m.frames[1].frame.mediaTime - 10) <= 0.07, `mediaTime=${m.frames[1].frame.mediaTime}`);   // 15fps → 最大 1/15 秒
  assert.equal(m.frames[3].clamped, true);
  assert.equal(m.measurement.uniqueFrames, 4);
  r = await cap('page.html', ['--seconds', '3']);
  assert.deepEqual(readdirSync(path.join(tmp, 'out')).sort(), ['20261112-custom-12', '20261112-custom-12-2'], 'A: 既存の出力先を壊さず -2 が作られること');

  // B 異なる指定秒が同じコマに当たる
  r = await cap('slow.html', ['--seconds', '10.02,10.1,10.5']);
  console.log(r.out);
  assert.equal(r.code, 0, 'B: capture が失敗');
  m = manifestOf(newest());
  noSecret(r.out, JSON.stringify(m));
  const [b1, b2, b3] = m.frames;
  assert.equal(b1.frame.mediaTime, b2.frame.mediaTime, 'B: 10.02s と 10.10s は同じコマ（5fps）');
  assert.notEqual(b1.frame.mediaTime, b3.frame.mediaTime);
  assert.equal(b1.sha256, b2.sha256, 'B: 同じコマなら画像も同じ');
  assert.notEqual(b1.requestedSec, b2.requestedSec);
  assert.equal(b1.independentMeasurement, true);
  assert.equal(b2.independentMeasurement, false);
  assert.equal(b2.duplicateOf, b1.file);
  assert.equal(m.measurement.uniqueFrames, 2);
  assert.equal(m.measurement.independentMeasurements, 2);
  assert.equal(m.measurement.duplicates.length, 1);
  assert.equal(m.status, 'ok');
  console.log(`B 確認: nudged=${[b1.nudged, b2.nudged, b3.nudged]}（同じコマの上へのシークで、別位置から戻して取得したか）`);

  // B2 シークバーつき：同じコマ（mediaTime が同じ）でも画像は違ってよい。警告にはしない
  r = await cap('slowctl.html', ['--seconds', '10.02,10.1,10.5']);
  assert.equal(r.code, 0, 'B2: capture が失敗');
  m = manifestOf(newest());
  assert.equal(m.frames[0].frame.mediaTime, m.frames[1].frame.mediaTime);
  assert.equal(m.frames[1].duplicateOf, m.frames[0].file);
  assert.equal(m.measurement.uniqueFrames, 2);
  assert.deepEqual(m.measurement.anomalies, []);
  assert.equal(m.status, 'ok');
  console.log(`B2 確認: シークバーつきの画像ハッシュは同じか=${m.frames[0].sha256 === m.frames[1].sha256}（違っても同じコマとして扱う）`);

  // B3 同じコマの上への再シークで新しいフレームが出ない場合：別位置から戻して取得し、同じ mediaTime になる
  r = await cap('slowdup.html', ['--seconds', '10.02,10.1,10.5']);
  console.log(r.out);
  assert.equal(r.code, 0, 'B3: capture が失敗');
  m = manifestOf(newest());
  assert.equal(m.frames[0].frame.mediaTime, m.frames[1].frame.mediaTime);
  assert.equal(m.frames[1].nudged, true, 'B3: 新しいフレームが出ないので、別位置から戻して取得するはず');
  assert.equal(m.frames[1].measurable, true);
  assert.equal(m.frames[1].duplicateOf, m.frames[0].file);
  assert.equal(m.measurement.uniqueFrames, 2);

  // C 別のコマを撮る
  r = await cap('drift.html', ['--seconds', '5,12']);
  console.log(r.out);
  assert.notEqual(r.code, 0, 'C: 計測不可があるので終了コードは 0 にならない');
  m = manifestOf(newest());
  noSecret(r.out, JSON.stringify(m));
  assert.equal(m.status, 'partial');
  assert.ok(m.frames.every((f) => f.measurable === false && f.notMeasurableReasons.includes('frame-changed-during-capture')), 'C: 別のコマの可能性がある画像は計測可にしない');
  assert.ok(m.frames.every((f) => f.attempts === 2), 'C: 1回やり直している');
  assert.equal(m.measurement.measurableImages, 0);
  assert.ok(m.frames.every((f) => existsSync(path.join(newest(), f.file))), 'C: 画像は残す（計測に使わないだけ）');

  // D 表示フレーム時刻が取れない
  r = await cap('noframe.html', ['--seconds', '5,12']);
  console.log(r.out);
  assert.notEqual(r.code, 0);
  m = manifestOf(newest());
  assert.equal(m.status, 'partial');
  assert.ok(m.frames.every((f) => f.measurable === false && f.frame.mediaTime === null && f.frame.supported === false));
  assert.ok(m.frames.every((f) => JSON.stringify(f.notMeasurableReasons) === '["frame-time-unavailable"]'), 'D: 時刻が取れない理由だけ（余計な理由を重ねない）');
  assert.ok(m.frames.every((f) => Number.isFinite(f.playerPosition.afterShot)), 'D: 再生位置は別に記録される');
  assert.ok(m.frames.every((f) => f.independentMeasurement === false && f.frameId === null));

  // E play モード：撮影中にフレームが進んだ画像は計測可にしない
  r = await cap('page.html', ['--seconds', '5,12', '--mode', 'play']);
  console.log(r.out);
  m = manifestOf(newest());
  noSecret(r.out, JSON.stringify(m));
  for (const f of m.frames) {
    if (f.measurable) assert.equal(f.mediaTimeRange.framesDuringCapture, 0, 'E: 計測可は、撮影中にフレームが進まなかったものだけ');
    else assert.ok(JSON.stringify(f.notMeasurableReasons) === '["play-frame-range-only"]' && f.mediaTimeRange.framesDuringCapture > 0);
    assert.ok(f.mediaTimeRange, 'E: 範囲を記録');
  }
  console.log(`E 確認: play モードで計測可=${m.frames.filter((f) => f.measurable).length}/${m.frames.length}`);

  // report.mjs
  const rep = await runAsync('report.mjs', [newest()]);
  assert.match(rep.out, /指定秒/);
  noSecret(rep.out);

  // verify：通常は 9/9 PASS
  let v = await runAsync('verify.mjs', ['--date', '20261112', '--race', '12', '--port', port, '--player-url', U('page.html')]);
  console.log(v.out);
  assert.equal(v.code, 0);
  assert.match(v.out, /RESULT: PASS \(9\/9\)/);
  noSecret(v.out);

  // F verify：音声だけの動画（読込はできるが、映像サイズ 0×0・フレームが増えない）は FAIL
  v = await runAsync('verify.mjs', ['--date', '20261112', '--race', '12', '--port', port, '--video-timeout', '8', '--player-url', U('audio.html')]);
  console.log(v.out);
  assert.notEqual(v.code, 0);
  assert.match(v.out, /PASS  4 プレイヤー読込/, 'F: 読込直後は 0×0 でも項目4は PASS（映像サイズは再生後に見る）');
  assert.match(v.out, /FAIL  7 再生後の映像サイズ  0x0/);
  assert.match(v.out, /FAIL  8 フレーム数が増える/);
  assert.match(v.out, /RESULT: FAIL/);

  // G 失敗の段階
  const stageOf = async (page) => {
    const x = await cap(page, ['--seconds', '3', '--video-timeout', '4']);
    assert.notEqual(x.code, 0, `${page} は失敗するはず`);
    noSecret(x.out);
    const mm = manifestOf(newest());
    assert.equal(mm.status, 'failed');
    return mm.failure;
  };
  assert.equal((await stageOf('novideo.html')).stage, 'player-load');
  const denied = await stageOf('denied.html');
  assert.equal(denied.stage, 'forbidden');
  assert.match(denied.hint, /理由は未確認/);
  assert.doesNotMatch(denied.cause + denied.hint, /地域制限(です|である|のため)/);
  assert.equal((await stageOf('bad.html')).stage, 'decode');
  const blocker = http.createServer().listen(0, '127.0.0.1');
  await new Promise((rr) => blocker.once('listening', rr));
  const busy = blocker.address().port;
  const x = await runAsync('capture.mjs', ['--date', '20261112', '--race', '12', '--port', String(busy), '--player-url', U('page.html')]);
  blocker.close();
  assert.notEqual(x.code, 0);
  assert.match(x.out, /\[cdp\]/);
  assert.match(x.out, /--port/);

  // 受け入れ検査（accept.mjs）：1コマンドで 合格 が出ること
  const acc = await runAsync('accept.mjs', ['--date', '20261112', '--pair', '10.02,10.1', '--spread', '3,10,20', '--port', port, '--player-url', U('slow.html')]);
  console.log(acc.out.split('\n').slice(-12).join('\n'));
  assert.equal(acc.code, 0, 'accept が不合格');
  assert.match(acc.out, /総合: 合格/);
  assert.match(acc.out, /同じコマでした/);
  noSecret(acc.out);
  const bad = await runAsync('accept.mjs', ['--date', '20261112', '--pair', '5,12', '--spread', '3,10', '--port', port, '--player-url', U('noframe.html')]);
  assert.notEqual(bad.code, 0);
  assert.match(bad.out, /総合: 不合格/);

  console.log('E2E OK');
} finally {
  server.close();
}
