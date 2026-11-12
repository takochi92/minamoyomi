#!/usr/bin/env node
// 自己点検モード。homesv で「この道具がそのまま動く状態か」を1行ずつ PASS / FAIL で出す。
//
//   node verify.mjs                       # 今日（日本時間）の平和島12R展示で点検
//   node verify.mjs --date 20261112 --race 12
//
// 点検項目：1 Chrome のバージョン / 2 デバッグポートの空き / 3 Chrome 起動とデバッグ接続 / 4 プレイヤー読込（video 要素）
//          5 duration > 0 / 6 5秒間で currentTime が 3秒以上進む / 7 エラーなし
// 起動した Chrome は、自分の PID だけを終了する。

import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { ArgError, parseVerifyArgs } from './args.mjs';
import { CdpClient } from './cdp.mjs';
import { findChrome, isPortInUse, launchChrome } from './chrome.mjs';
import { StageError, classifyFailure } from './failures.mjs';
import { ensurePlaying, readVideo, sleep, waitForVideo, watchNetwork, failureContext } from './player.mjs';
import { buildPlayerUrl, resolveVenue, UrlBuildError } from './player-url.mjs';
import { makeLogger, redactText, redactUrl } from './redact.mjs';

const USAGE = `使い方: node verify.mjs [--date YYYYMMDD|today] [--race N] [--venue 04] [--port 9454] [--profile PATH] [--chrome PATH] [--attach] [--player-url URL]`;

export async function run(argv, env = process.env, out = console.log) {
  let args;
  try {
    args = parseVerifyArgs(argv, env);
  } catch (e) {
    if (e instanceof ArgError) { console.error(`引数エラー: ${e.message}\n${USAGE}`); return 2; }
    throw e;
  }
  if (args.help) { out(USAGE); return 0; }

  const rows = [];
  const line = (ok, name, detail = '') => {
    const s = `${ok === null ? 'SKIP' : ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  ' + redactText(String(detail)) : ''}`;
    rows.push({ ok, s });
    out(s);
  };

  let url;
  try {
    url = args.playerUrl || buildPlayerUrl({ date: args.date, venue: args.venue, race: args.race, padRace: args.padRace });
    if (!args.playerUrl) resolveVenue(args.venue);
  } catch (e) {
    if (e instanceof UrlBuildError) { console.error(`引数エラー: ${e.message}`); return 2; }
    throw e;
  }
  out(`点検対象: ${redactUrl(url)}`);

  let chrome = null;
  let cdp = null;
  try {
    // 1 Chrome のバージョン
    let found = null;
    try {
      found = await findChrome(args.chrome);
      line(true, '1 Chrome のバージョン', `${found.version}（${found.bin}）`);
    } catch (e) {
      line(false, '1 Chrome のバージョン', e.message);
      return finish(rows, out);
    }

    // 2 デバッグポートの空き（--attach のときは「応答すること」を点検）
    const inUse = await isPortInUse(args.port);
    if (args.attach) {
      line(inUse, '2 デバッグポート（--attach）', inUse ? `${args.port} に Chrome が応答` : `${args.port} が応答しません`);
      if (!inUse) return finish(rows, out);
    } else {
      line(!inUse, '2 デバッグポートの空き', inUse ? `${args.port} は使用中（落とさずに --port を変えてください）` : `${args.port} は空き`);
      if (inUse) return finish(rows, out);
    }

    // 3 起動とデバッグ接続
    try {
      if (!args.attach) chrome = await launchChrome({ chrome: args.chrome, port: args.port, profile: args.profile, extraArgs: args.extraChromeArgs });
      cdp = await CdpClient.connect({ port: args.port });
      await cdp.enable(['Page', 'Runtime', 'Network']);
      line(true, '3 Chrome 起動とデバッグ接続', chrome ? `PID=${chrome.pid}` : '既存の Chrome に接続');
    } catch (e) {
      line(false, '3 Chrome 起動とデバッグ接続', e.message);
      return finish(rows, out);
    }

    // 4・5 プレイヤー読込と duration
    const net = watchNetwork(cdp);
    let v = null;
    try {
      await cdp.navigate(url);
      v = await waitForVideo(cdp, net, { timeoutMs: args.videoTimeoutMs });
      line(true, '4 プレイヤー読込（video 要素）', `${v.width}x${v.height}`);
      line(v.duration > 0, '5 duration > 0', `${v.duration}s`);
    } catch (e) {
      const st = e instanceof StageError ? e : null;
      line(false, '4 プレイヤー読込（video 要素）', st ? `[${st.stage}] ${st.cause_}` : e.message);
      line(null, '5 duration > 0', '4 が失敗したため未確認');
      line(null, '6 5秒間の再生進行', '未確認');
      line(null, '7 エラーなし', '未確認');
      if (st) out(`  対処: ${st.hint}`);
      return finish(rows, out);
    }

    // 6 5秒間で currentTime が 3秒以上進む
    const play = await ensurePlaying(cdp);
    const a = await readVideo(cdp);
    await sleep(5000);
    const b = await readVideo(cdp);
    const adv = (b.currentTime ?? 0) - (a.currentTime ?? 0);
    line(adv >= 3, '6 5秒間で currentTime が 3秒以上進む', `${a.currentTime.toFixed(2)} → ${b.currentTime.toFixed(2)}（+${adv.toFixed(2)}s${play.clicked ? '・中央クリックあり' : ''}）`);

    // 7 エラーなし
    const ctx = await failureContext(cdp, net);
    const err = ctx.video?.error;
    const bad = err || net.httpErrors.some((e) => e.status === 403);
    if (bad) {
      const c = classifyFailure(ctx);
      line(false, '7 エラーなし', `[${c.stage}] ${c.cause}`);
      out(`  対処: ${c.hint}`);
    } else {
      line(true, '7 エラーなし', `video.error なし・403 なし（その他の HTTP エラー ${net.httpErrors.length} 件）`);
    }
    if (adv < 3 && !bad) {
      const c = classifyFailure({ ...ctx, video: { ...(ctx.video || {}), has: true, duration: v.duration } });
      out(`  再生が進みません。対処: ${c.hint}`);
    }
  } catch (e) {
    line(false, '内部エラー', e.message);
  } finally {
    if (cdp) await cdp.close();
    if (chrome) await chrome.stop();
  }
  return finish(rows, out);
}

function finish(rows, out) {
  const checked = rows.filter((r) => r.ok !== null);
  const pass = checked.filter((r) => r.ok).length;
  const ok = checked.length > 0 && pass === checked.length && rows.every((r) => r.ok !== null);
  out(`RESULT: ${ok ? 'PASS' : 'FAIL'} (${pass}/${rows.length})`);
  return ok ? 0 : 1;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  run(process.argv.slice(2)).then((c) => process.exit(c), (e) => { makeLogger('[verify]', console.error)(e); process.exit(1); });
}
