#!/usr/bin/env node
// BOATCAST 展示リプレイの「再生・フレーム取得・記録」。homesv（日本国内の家庭回線）で実行する。
//
//   node capture.mjs --date 20261112 --race 12
//   node capture.mjs --date 20261112 --races 11,12 --seconds 10,60,120
//   node capture.mjs --date 20261112 --race 12 --dry-run        # Chrome を起動せず、計画だけ表示
//
// 処理：Chrome 起動 → プレイヤーURLを開く → video と duration を待つ → 再生開始 → currentTime が進むことを確認
//       → 指定秒へシークして PNG 保存 → manifest.json に記録 → 自分が起動した Chrome の PID だけを終了
// 動画ファイルそのもののダウンロードはしない（再生と、画面のスクリーンショットだけ）。

import { writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { ArgError, parseCaptureArgs, DEFAULT_PORT, DEFAULT_PROFILE, DEFAULT_OUT, DEFAULT_SECONDS } from './args.mjs';
import { CdpClient } from './cdp.mjs';
import { chromeFlags, launchChrome, findChrome } from './chrome.mjs';
import { StageError, classifyFailure } from './failures.mjs';
import { ensurePlaying, failureContext, seekAndShoot, waitForVideo, watchNetwork } from './player.mjs';
import { buildPlayerUrl, resolveVenue, UrlBuildError } from './player-url.mjs';
import { makeLogger, redactDeep, redactUrl } from './redact.mjs';
import { frameFileName, makeUniqueDir, nowJst, pngSize, writeNew } from './util.mjs';

export const TOOL_VERSION = '0.1.0';
const log = makeLogger('[capture]');

export const USAGE = `使い方: node capture.mjs --date YYYYMMDD|today --race N [--race M ... | --races N,M]
  --seconds 10,60,...   取得する秒（既定 ${DEFAULT_SECONDS.join(',')}。duration を超える分は末尾に切り詰める）
  --venue 04            場コード・場名（検証済みは 04 平和島だけ）
  --port ${DEFAULT_PORT}          デバッグポート（環境変数 BOATCAST_PORT。9447 / 9453 は使わない）
  --profile PATH        Chrome のプロファイル（既定 ${DEFAULT_PROFILE}）
  --out DIR             出力の親フォルダ（既定 ${DEFAULT_OUT}）
  --mode seek|play      seek=一時停止してシーク（既定） / play=再生したまま撮る
  --chrome PATH         Chrome の実行ファイル（環境変数 BOATCAST_CHROME）
  --attach              すでに起動している Chrome（--port）に繋ぐ。起動も終了もしない
  --video-timeout SEC   video 要素と duration を待つ秒数（既定 45）
  --pad-race            1桁のレース番号を 01 の形にする（未検証。1〜9R で開けないときの切り分け用）
  --player-url URL      組み立てずにこのURLを開く（ローカルのテストページ用。記録はドメイン＋パスまで）
  --dry-run             Chrome を起動せず、計画だけ表示`;

function venueInfo(args) {
  if (args.playerUrl) return { jo: null, name: 'custom', slug: 'custom', label: 'custom' };
  return resolveVenue(args.venue);
}

function playerUrlFor(args, race) {
  if (args.playerUrl) return args.playerUrl;
  return buildPlayerUrl({ date: args.date, venue: args.venue, race, padRace: args.padRace });
}

/** 1レースぶんの処理。失敗しても例外は投げず、manifest（status=failed）を書いて結果を返す */
async function captureRace({ cdp, net, args, race, venue, chrome }) {
  const startedAt = nowJst();
  const url = playerUrlFor(args, race);
  const dir = makeUniqueDir(args.out, `${args.date}-${venue.label}-${race}`);
  const manifest = {
    tool: { name: 'boatcast-capture', version: TOOL_VERSION },
    createdAt: startedAt,
    date: args.date,
    venue: { jo: venue.jo, name: venue.name, slug: venue.slug },
    race,
    raceType: 'exhibition',
    bitrate: 'low',
    playerUrl: redactUrl(url),          // ドメイン＋パスまで（クエリは落とす）
    mode: args.mode,
    chrome: chrome ? { version: chrome.version, pid: chrome.pid ?? null, port: args.port, attached: Boolean(args.attach) } : null,
    status: 'running',
    video: null,
    playback: null,
    frames: [],
    networkErrors: [],
    failure: null,
  };
  const save = () => writeFileSync(path.join(dir, 'manifest.json'), JSON.stringify(redactDeep(manifest), null, 2) + '\n');
  net.httpErrors.length = 0;
  net.failed.length = 0;
  try {
    log(`${args.date} ${venue.name} ${race}R → ${dir}`);
    log(`プレイヤーを開く: ${redactUrl(url)}`);
    await cdp.navigate(url);
    const v = await waitForVideo(cdp, net, { timeoutMs: args.videoTimeoutMs });
    manifest.video = { duration: v.duration, width: v.width, height: v.height, readyState: v.readyState };
    log(`video 確認: duration=${v.duration}s ${v.width}x${v.height}`);

    const play = await ensurePlaying(cdp);
    manifest.playback = { progressed: play.progressed, clicked: play.clicked, samples: play.samples.map((s) => Math.round(s.t * 100) / 100) };
    if (!play.progressed) {
      const ctx = await failureContext(cdp, net);
      const c = classifyFailure({ ...ctx, video: { ...(ctx.video || { has: true }), error: play.error || ctx.video?.error } });
      throw new StageError(play.error ? c.stage : 'decode', play.error ? c.cause : '再生が進みません（currentTime が増えない）');
    }
    log(`再生確認: currentTime ${manifest.playback.samples.join(' → ')}${play.clicked ? '（中央クリックあり）' : ''}`);

    const seen = new Set();
    for (const want of args.seconds) {
      const dur = manifest.video.duration;
      const target = want > dur - 0.3 ? Math.max(0, Math.floor((dur - 0.5) * 10) / 10) : want;
      const clamped = target !== want;
      if (seen.has(target)) { log(`  ${want}s は ${target}s と重なるので省略`); continue; }
      seen.add(target);
      const shot = await seekAndShoot(cdp, target, { mode: args.mode });
      const file = path.basename(writeNew(dir, frameFileName(target), shot.png));
      const size = pngSize(shot.png);
      manifest.frames.push({
        requestedSec: want, targetSec: target, clamped, file,
        currentTimeBefore: Math.round(shot.before * 1000) / 1000,
        actualCurrentTime: Math.round(shot.actual * 1000) / 1000,
        seekOk: shot.seekOk, seekable: shot.seekable,
        paused: shot.paused, error: shot.error, bytes: shot.png.length, screenshot: size,
      });
      log(`  ${file}  要求 ${want}s → 実測 ${shot.actual.toFixed(2)}s${clamped ? '（末尾に切り詰め）' : ''}${shot.paused ? ' paused' : ''}${shot.error ? ' ERROR' : ''}${shot.seekOk ? '' : ' ⚠シーク位置がずれています'}`);
      if (shot.error) {
        const c = classifyFailure({ video: { has: true, duration: dur, error: shot.error }, httpErrors: net.httpErrors });
        throw new StageError(c.stage, c.cause);
      }
    }
    const off = manifest.frames.filter((f) => !f.seekOk);
    if (off.length) {
      manifest.status = 'partial';
      manifest.warnings = [`シーク位置が指定秒からずれたフレームが ${off.length} 枚あります（${off.map((f) => f.file).join(', ')}）。` +
        'seekable の範囲や、配信が Range / MSE のシークに対応しているかを確認してください'];
      log(`警告: ${manifest.warnings[0]}`);
    } else {
      manifest.status = 'ok';
    }
  } catch (e) {
    const f = e instanceof StageError ? e.toJSON() : { ...classifyFailure({ cdpError: e.message }) };
    manifest.status = 'failed';
    manifest.failure = { stage: f.stage, cause: f.cause, hint: f.hint };
    log(`失敗 [${f.stage}] ${f.cause}`);
    log(`  対処: ${f.hint}`);
  } finally {
    manifest.networkErrors = [...net.httpErrors, ...net.failed];
    manifest.finishedAt = nowJst();
    save();
    try { await cdp.navigate('about:blank', { waitLoadMs: 3000 }); } catch { /* 次のレースで開き直す */ }
  }
  return { race, dir, status: manifest.status, frames: manifest.frames.length };
}

export async function run(argv, env = process.env) {
  let args;
  try {
    args = parseCaptureArgs(argv, env);
  } catch (e) {
    if (e instanceof ArgError) { console.error(`引数エラー: ${e.message}\n\n${USAGE}`); return 2; }
    throw e;
  }
  if (args.help) { console.log(USAGE); return 0; }

  let venue;
  try {
    venue = venueInfo(args);
    for (const r of args.races) playerUrlFor(args, r);   // URL を組み立てられるか先に確かめる
  } catch (e) {
    if (e instanceof UrlBuildError) { console.error(`引数エラー: ${e.message}`); return 2; }
    throw e;
  }

  if (args.dryRun) {
    log('dry-run（Chrome は起動しません）');
    log(`場: ${venue.name}  日付: ${args.date}  レース: ${args.races.join(',')}  モード: ${args.mode}`);
    log(`取得秒: ${args.seconds.join(',')}`);
    for (const r of args.races) log(`  ${r}R → ${redactUrl(playerUrlFor(args, r))}  出力: ${path.join(args.out, `${args.date}-${venue.label}-${r}`)}`);
    log(`Chrome 引数: ${chromeFlags({ port: args.port, profile: args.profile, extra: args.extraChromeArgs }).join(' ')}`);
    return 0;
  }

  let chrome = null;
  let cdp = null;
  const results = [];
  try {
    if (args.attach) {
      const ver = await CdpClient.version({ port: args.port }).catch(() => null);
      if (!ver) throw new StageError('cdp', `--attach 先のデバッグポート ${args.port} が応答しません`);
      chrome = { version: ver.Browser, pid: null, stop: async () => {} };
      log(`既存の Chrome に接続: ${ver.Browser} port=${args.port}（起動も終了もしません）`);
    } else {
      await findChrome(args.chrome);
      chrome = await launchChrome({ chrome: args.chrome, port: args.port, profile: args.profile, extraArgs: args.extraChromeArgs, log });
      log(`Chrome PID=${chrome.pid} ${chrome.version}`);
    }
    cdp = await CdpClient.connect({ port: args.port });
    await cdp.enable(['Page', 'Runtime', 'Network']);
    const net = watchNetwork(cdp);
    for (const race of args.races) results.push(await captureRace({ cdp, net, args, race, venue, chrome }));
  } catch (e) {
    const f = e instanceof StageError ? e.toJSON() : classifyFailure({ cdpError: e.message });
    log(`失敗 [${f.stage}] ${f.cause}`);
    log(`  対処: ${f.hint}`);
    results.push({ race: null, status: 'failed', stage: f.stage });
  } finally {
    if (cdp) await cdp.close();
    if (chrome && !args.attach) {
      await chrome.stop();
      log(`Chrome PID=${chrome.pid} を終了しました（自分が起動した PID のみ）`);
    }
  }
  log('結果: ' + results.map((r) => `${r.race ?? '-'}R ${r.status}${r.frames !== undefined ? ` (${r.frames} frames)` : ''}`).join(' / '));
  return results.every((r) => r.status === 'ok') ? 0 : 1;   // partial（シークのずれ）も 1
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  run(process.argv.slice(2)).then((code) => process.exit(code), (e) => { makeLogger('[capture]', console.error)(e); process.exit(1); });
}
