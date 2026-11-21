// Chrome の起動・終了。自分が起動した Chrome の PID だけを終了する（pkill の広いパターンは使わない）。
//
// 必須フラグ：--headless=new --disable-gpu --disable-accelerated-video-decode --autoplay-policy=no-user-gesture-required
//   （既定設定だと映像が PIPELINE_ERROR_DECODE で再生できない。この設定で通常再生を確認済み）

import { spawn, execFile } from 'node:child_process';
import { lstatSync, readlinkSync, rmSync, mkdirSync } from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import { promisify } from 'node:util';
import { StageError } from './failures.mjs';
import { CdpClient } from './cdp.mjs';

const execFileP = promisify(execFile);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export const REQUIRED_FLAGS = [
  '--headless=new',
  '--disable-gpu',
  '--disable-accelerated-video-decode',
  '--autoplay-policy=no-user-gesture-required',
];

export function chromeFlags({ port, profile, extra = [] }) {
  return [
    ...REQUIRED_FLAGS,
    `--user-data-dir=${profile}`,
    `--remote-debugging-port=${port}`,
    '--remote-debugging-address=127.0.0.1',
    '--no-first-run',
    '--window-size=1280,900',
    ...extra,
    'about:blank',
  ];
}

/** Chrome の実行ファイルを探す（BOATCAST_CHROME > google-chrome-stable > google-chrome > chromium） */
export async function findChrome(preferred = null) {
  const candidates = preferred ? [preferred] : ['google-chrome-stable', 'google-chrome', 'chromium', 'chromium-browser'];
  for (const c of candidates) {
    try {
      const { stdout } = await execFileP(c, ['--version'], { timeout: 15000 });
      return { bin: c, version: stdout.trim() };
    } catch { /* 次の候補へ */ }
  }
  throw new StageError('cdp', `Chrome の実行ファイルが見つかりません（試した名前: ${candidates.join(', ')}）。BOATCAST_CHROME か --chrome で指定してください`);
}

/** そのポートで誰かが待ち受けているか（使用中なら true。使用中の相手は落とさない） */
export function isPortInUse(port, host = '127.0.0.1', timeoutMs = 1500) {
  return new Promise((resolve) => {
    const s = net.createConnection({ port, host });
    const done = (v) => { s.destroy(); resolve(v); };
    s.setTimeout(timeoutMs, () => done(false));
    s.once('connect', () => done(true));
    s.once('error', () => done(false));
  });
}

/**
 * 自分のプロファイルに SingletonLock が残っていて、持ち主のプロセスがもういない場合だけ、プロファイル内のロックを消す。
 * プロファイルの外のファイルには触らない。生きているプロセスのロックは消さない。
 */
export function cleanStaleLock(profile) {
  const removed = [];
  const lock = path.join(profile, 'SingletonLock');
  let target = null;
  try { target = readlinkSync(lock); } catch { return removed; }   // ロックなし（または通常ファイル）
  const pid = Number((target.match(/-(\d+)$/) || [])[1]);
  if (pid) {
    try { process.kill(pid, 0); return removed; } catch (e) { if (e.code === 'EPERM') return removed; }   // 生きている
  }
  for (const n of ['SingletonLock', 'SingletonCookie', 'SingletonSocket']) {
    const p = path.join(profile, n);
    if (path.dirname(p) !== path.resolve(profile)) continue;   // プロファイル直下だけ
    try { lstatSync(p); } catch { continue; }   // 無いものは数えない（壊れたシンボリックリンクも lstat なら見える）
    try { rmSync(p, { force: true }); removed.push(n); } catch { /* 無視 */ }
  }
  return removed;
}

/**
 * Chrome を起動して、デバッグポートが応答するまで待つ。
 * ポートが使用中なら起動せずに cdp 段階のエラーにする（使用中の Chrome は落とさない）。
 * @returns {{pid:number, version:string, stop:()=>Promise<void>}}
 */
export async function launchChrome({ chrome = null, port, profile, extraArgs = [], log = () => {} }) {
  const found = await findChrome(chrome);
  if (await isPortInUse(port)) {
    throw new StageError('cdp', `デバッグポート ${port} はすでに使われています。使用中のプロセスは落としません`);
  }
  mkdirSync(profile, { recursive: true });
  const removed = cleanStaleLock(profile);
  if (removed.length) log(`古いロックを消しました（自分のプロファイル内）: ${removed.join(', ')}`);

  const args = chromeFlags({ port, profile, extra: extraArgs });
  log(`Chrome 起動: ${found.bin} port=${port} profile=${profile}`);
  const child = spawn(found.bin, args, { stdio: 'ignore', detached: false });
  let exited = false;
  child.once('exit', () => { exited = true; });
  child.once('error', () => { exited = true; });
  if (!child.pid) throw new StageError('cdp', 'Chrome を起動できませんでした');

  const stop = async () => {
    if (exited) return;
    try { process.kill(child.pid, 'SIGTERM'); } catch { return; }   // 自分が起動した PID だけ
    for (let i = 0; i < 40 && !exited; i++) await sleep(250);
    if (!exited) { try { process.kill(child.pid, 'SIGKILL'); } catch { /* 終了済み */ } }
  };

  const end = Date.now() + 25000;
  let version = null;
  while (Date.now() < end && !exited) {
    try { version = await CdpClient.version({ port }); break; } catch { await sleep(300); }
  }
  if (!version) {
    await stop();
    throw new StageError('cdp', exited ? 'Chrome がすぐに終了しました（フラグ・プロファイルを確認）' : `デバッグポート ${port} が 25秒以内に応答しませんでした`);
  }
  return { pid: child.pid, version: version.Browser || found.version, binary: found.bin, stop };
}

