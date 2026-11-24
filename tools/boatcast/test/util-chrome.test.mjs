import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, existsSync, symlinkSync, writeFileSync, readFileSync, readdirSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { makeUniqueDir, writeNew, frameFileName, pngSize, nowJst } from '../util.mjs';
import { chromeFlags, REQUIRED_FLAGS, cleanStaleLock, isPortInUse } from '../chrome.mjs';
import net from 'node:net';

const tmp = () => mkdtempSync(path.join(os.tmpdir(), 'boatcast-test-'));

test('出力先は既存フォルダを壊さず -2, -3 と増える', () => {
  const base = tmp();
  const a = makeUniqueDir(base, '20261112-heiwajima-12');
  const b = makeUniqueDir(base, '20261112-heiwajima-12');
  const c = makeUniqueDir(base, '20261112-heiwajima-12');
  assert.deepEqual([path.basename(a), path.basename(b), path.basename(c)], ['20261112-heiwajima-12', '20261112-heiwajima-12-2', '20261112-heiwajima-12-3']);
});

test('writeNew は既存ファイルを上書きしない', () => {
  const d = tmp();
  const p1 = writeNew(d, 'f_0010s.png', 'A');
  const p2 = writeNew(d, 'f_0010s.png', 'B');
  assert.equal(readFileSync(p1, 'utf8'), 'A');
  assert.equal(path.basename(p2), 'f_0010s-2.png');
});

test('フレーム名と PNG サイズ', () => {
  assert.equal(frameFileName(10), 'f_0010s.png');
  assert.equal(frameFileName(320), 'f_0320s.png');
  assert.equal(frameFileName(12.5), 'f_0012p5s.png');
  const png = Buffer.alloc(32);
  png.writeUInt32BE(0x89504e47, 0); png.writeUInt32BE(1280, 16); png.writeUInt32BE(900, 20);
  assert.deepEqual(pngSize(png), { width: 1280, height: 900 });
  assert.equal(pngSize(Buffer.from('xx')), null);
});

test('日本時間の時刻文字列', () => {
  assert.equal(nowJst(new Date('2026-11-12T00:00:00Z')), '2026-11-12T09:00:00+09:00');
});

test('Chrome の必須フラグとポート・プロファイル', () => {
  const f = chromeFlags({ port: 9454, profile: '/p/x' });
  for (const r of ['--headless=new', '--disable-gpu', '--disable-accelerated-video-decode', '--autoplay-policy=no-user-gesture-required']) assert.ok(f.includes(r), r);
  assert.deepEqual(REQUIRED_FLAGS.length, 4);
  assert.ok(f.includes('--remote-debugging-port=9454'));
  assert.ok(f.includes('--remote-debugging-address=127.0.0.1'));
  assert.ok(f.includes('--user-data-dir=/p/x'));
  assert.equal(f.at(-1), 'about:blank');
});

test('古いロック（持ち主のプロセスがいない）はプロファイル内だけ消す。生きているものは消さない', () => {
  const prof = tmp();
  symlinkSync('host-999999999', path.join(prof, 'SingletonLock'));      // 存在しない PID
  writeFileSync(path.join(prof, 'keep.txt'), 'x');
  assert.deepEqual(cleanStaleLock(prof), ['SingletonLock']);
  assert.ok(existsSync(path.join(prof, 'keep.txt')));
  assert.ok(!readdirSync(prof).includes('SingletonLock'));

  const prof2 = tmp();
  symlinkSync(`host-${process.pid}`, path.join(prof2, 'SingletonLock'));   // 生きている PID（このテスト自身）
  assert.deepEqual(cleanStaleLock(prof2), []);
  assert.ok(readdirSync(prof2).includes('SingletonLock'));
});

test('ポートの使用中判定', async () => {
  const srv = net.createServer().listen(0, '127.0.0.1');
  await new Promise((r) => srv.once('listening', r));
  const port = srv.address().port;
  assert.equal(await isPortInUse(port), true);
  await new Promise((r) => srv.close(r));
  assert.equal(await isPortInUse(port), false);
});
