#!/usr/bin/env node
// manifest.json を表にして、「どの画像が計測に使えるか」を確かめる（実機確認用。ブラウザは使わない）。
//
//   node report.mjs captures/20261112-heiwajima-12            # フォルダ（中の manifest.json を読む）
//   node report.mjs captures/20261112-heiwajima-12/manifest.json
//
// 見る点：指定秒 / プレイヤーの再生位置 / 表示フレームの mediaTime / 計測可否 / 同じコマの重複 / 画像ハッシュ
// 終了コード：問題なし=0 / 計測に使えない画像や食い違いの疑いがある=1 / 読めない=2

import { existsSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { summarizeManifest } from './frames.mjs';
import { redactDeep } from './redact.mjs';

export function formatReport(manifest) {
  const { rows, problems } = summarizeManifest(manifest);
  const f = (x, d = 3) => (x === null || x === undefined ? '-' : Number(x).toFixed(d));
  const lines = [
    `${manifest.date} ${manifest.venue?.name ?? ''} ${manifest.race}R  status=${manifest.status}  mode=${manifest.mode}  ${manifest.video ? `duration=${manifest.video.duration}s ${manifest.video.width}x${manifest.video.height}` : ''}`,
    '指定秒      再生位置    mediaTime     計測  重複(同じコマ)      sha256        file',
  ];
  for (const r of rows) {
    lines.push(`${f(r.requestedSec).padStart(8)}  ${f(r.playerPosition).padStart(8)}  ${f(r.mediaTime, 6).padStart(12)}  ${(r.measurable ? '可' : '不可').padEnd(3)}  ${(r.duplicateOf ? `= ${r.duplicateOf}` : '').padEnd(16)}  ${r.sha256.padEnd(12)}  ${r.file}${r.reasons.length ? `  [${r.reasons.join(',')}]` : ''}`);
  }
  const m = manifest.measurement;
  if (m) lines.push(`画像 ${m.images} 枚 / 計測可 ${m.measurableImages} 枚 / 別々のコマ ${m.uniqueFrames} / 独立した計測値 ${m.independentMeasurements}`);
  for (const p of problems) lines.push(`⚠ ${p}`);
  return { text: lines.join('\n'), problems };
}

export function run(argv) {
  if (!argv.length || argv.includes('--help')) { console.log('使い方: node report.mjs <captures のフォルダ または manifest.json> ...'); return argv.length ? 0 : 2; }
  let code = 0;
  for (const a of argv) {
    const p = existsSync(a) && statSync(a).isDirectory() ? path.join(a, 'manifest.json') : a;
    let m;
    try { m = JSON.parse(readFileSync(p, 'utf8')); } catch (e) { console.error(`読めません: ${path.basename(p)}（${e.message}）`); return 2; }
    const r = formatReport(redactDeep(m));
    console.log(r.text + '\n');
    if (r.problems.length) code = 1;
  }
  return code;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) process.exit(run(process.argv.slice(2)));
