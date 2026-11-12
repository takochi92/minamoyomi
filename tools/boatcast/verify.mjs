#!/usr/bin/env node
// 自己点検モード。homesv で「この道具がそのまま動く状態か」を1行ずつ PASS / FAIL で出す。
//
//   node verify.mjs                       # 今日（日本時間）の平和島12R展示で点検
//   node verify.mjs --date 20261112 --race 12
//
// 点検項目
//   1 Chrome のバージョン / 2 デバッグポートの空き / 3 Chrome 起動とデバッグ接続
//   4 プレイヤー読込（video 要素があること。この時点の映像サイズは見ない：読込直後は 0×0 のことがある）
//   5 duration > 0
//   6 5秒間で currentTime が 3秒以上進む
//   7 再生後の映像サイズ（幅・高さが 0 より大きい。読込直後ではなく、再生が進んだあとで見る）
//   8 フレーム数が実際に増える（5秒間に 10 フレーム以上。requestVideoFrameCallback の通知数と getVideoPlaybackQuality の両方を見る）
//   9 エラーなし
// 起動した Chrome は、自分の PID だけを終了する。

import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { ArgError, parseVerifyArgs } from './args.mjs';
import { CdpClient } from './cdp.mjs';
import { findChrome, isPortInUse, launchChrome } from './chrome.mjs';
import { HINTS, StageError, classifyFailure } from './failures.mjs';
import { ensurePlaying, failureContext, installFrameProbe, readProbe, readVideo, sleep, waitForVideo, watchNetwork } from './player.mjs';
import { buildPlayerUrl, resolveVenue, UrlBuildError } from './player-url.mjs';
import { makeLogger, redactText, redactUrl } from './redact.mjs';

const USAGE = `使い方: node verify.mjs [--date YYYYMMDD|today] [--race N] [--venue 04] [--port 9454] [--profile PATH] [--chrome PATH] [--attach] [--video-timeout SEC] [--player-url URL]`;

export const MIN_FRAMES_IN_WINDOW = 10;   // 5秒間に増えるべきフレーム数の最低ライン（2fps 相当。実際の配信は、これよりずっと多いはず）
export const WINDOW_MS = 5000;

/** 点検項目 6〜8 の判定（ブラウザなしでテストできるように、値を渡して判定だけする） */
export function judgePlayback({ before, after, probeBefore, probeAfter }) {
  const adv = (after?.currentTime ?? 0) - (before?.currentTime ?? 0);
  const w = after?.width ?? 0;
  const h = after?.height ?? 0;
  const rvfc = probeAfter?.supported ? (probeAfter.seq ?? 0) - (probeBefore?.seq ?? 0) : null;
  const q = probeBefore?.quality && probeAfter?.quality ? probeAfter.quality.total - probeBefore.quality.total : null;
  const frames = [rvfc, q].filter((x) => x !== null);
  return {
    advance: adv,
    advanceOk: adv >= 3,
    sizeOk: w > 0 && h > 0,
    width: w,
    height: h,
    framesRvfc: rvfc,
    framesQuality: q,
    // どちらか取れた方すべてが基準以上であること（片方でも 0 なら「実際には増えていない」とみなす）
    framesOk: frames.length > 0 && frames.every((n) => n >= MIN_FRAMES_IN_WINDOW),
    framesMeasured: frames.length > 0,
  };
}

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
    try {
      const found = await findChrome(args.chrome);
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
      line(true, '4 プレイヤー読込（video 要素）', '映像サイズは再生後に項目7で確認');
      line(v.duration > 0, '5 duration > 0', `${v.duration}s`);
    } catch (e) {
      const st = e instanceof StageError ? e : null;
      line(false, '4 プレイヤー読込（video 要素）', st ? `[${st.stage}] ${st.cause_}` : e.message);
      for (const n of ['5 duration > 0', '6 5秒間で currentTime が 3秒以上進む', '7 再生後の映像サイズ', '8 フレーム数が増える', '9 エラーなし']) line(null, n, '4 が失敗したため未確認');
      if (st) out(`  対処: ${st.hint}`);
      return finish(rows, out);
    }

    // 6〜8 再生して 5秒間の変化を見る（フレーム監視は再生の前に入れる）
    await installFrameProbe(cdp);
    const play = await ensurePlaying(cdp);
    const before = await readVideo(cdp);
    const probeBefore = await readProbe(cdp);
    await sleep(WINDOW_MS);
    const after = await readVideo(cdp);
    const probeAfter = await readProbe(cdp);
    const j = judgePlayback({ before, after, probeBefore, probeAfter });

    line(j.advanceOk, '6 5秒間で currentTime が 3秒以上進む', `${before.currentTime.toFixed(2)} → ${after.currentTime.toFixed(2)}（+${j.advance.toFixed(2)}s${play.clicked ? '・中央クリックあり' : ''}）`);
    line(j.sizeOk, '7 再生後の映像サイズ', `${j.width}x${j.height}${j.sizeOk ? '' : '（0 のまま。映像がデコード・描画されていない可能性）'}`);
    const fd = `rVFC ${j.framesRvfc ?? '未対応'} / playbackQuality ${j.framesQuality ?? '未対応'}（5秒・基準 ${MIN_FRAMES_IN_WINDOW} 以上）`;
    line(j.framesOk, '8 フレーム数が増える', j.framesMeasured ? fd : 'フレーム数を測れません（どちらも未対応）');

    // 9 エラーなし
    const ctx = await failureContext(cdp, net);
    const err = ctx.video?.error;
    const bad = err || net.httpErrors.some((e) => e.status === 403);
    if (bad) {
      const c = classifyFailure(ctx);
      line(false, '9 エラーなし', `[${c.stage}] ${c.cause}`);
      out(`  対処: ${c.hint}`);
    } else {
      line(true, '9 エラーなし', `video.error なし・403 なし（その他の HTTP エラー ${net.httpErrors.length} 件）`);
    }
    if (!j.advanceOk && !bad) out(`  再生位置が進んでいません。確認: ${HINTS['player-load']}`);
    if ((!j.sizeOk || !j.framesOk) && !bad) out(`  映像が描画されていません（映像サイズ 0×0、またはフレームが増えない）。デコードの失敗（起動フラグ不足）や、映像トラックのない配信の可能性があります。確認: ${HINTS.decode}`);
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
