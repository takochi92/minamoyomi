#!/usr/bin/env node
// 受け入れ検査（homesv でこれ1本を実行すれば、正式運用してよいかが 合格 / 不合格 で出る）。
//
//   node accept.mjs --date 20261112
//
// やること（Chrome は1つずつ順番に起動する）
//   1 ユニットテスト
//   2 自己点検 verify（9項目）
//   3 近い2つの秒を撮る（既定 248.167 と 248.197、12R）→ 同じコマなら「同じコマ・計測値は1つ」と記録されていること
//   4 離れた秒を撮る（既定 10,60,120、1R）→ 全部が計測可で、別々のコマであること
// 結果は <出力先>/acceptance-report.json にも保存する（URL のクエリなどは含めない）。

import { spawn } from 'node:child_process';
import { mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { DEFAULT_OUT, todayJst } from './args.mjs';
import { redactDeep, redactText } from './redact.mjs';
import { nowJst } from './util.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));

/** 近い2つの秒の manifest を判定する */
export function evaluatePair(m) {
  const problems = [];
  if (!m || m.status !== 'ok') problems.push(`status=${m?.status ?? 'なし'}${m?.failure ? `（${m.failure.stage}: ${m.failure.cause}）` : ''}`);
  const fs = m?.frames ?? [];
  if (fs.length !== 2) problems.push(`画像が2枚ではありません（${fs.length}枚）`);
  for (const f of fs) {
    if (!f.measurable) problems.push(`${f.file}: 計測不可（${(f.notMeasurableReasons || []).join(',')}）`);
    if (!Number.isFinite(f.frame?.mediaTime)) problems.push(`${f.file}: 表示フレームの時刻がありません`);
    if (!Number.isFinite(f.playerPosition?.afterShot)) problems.push(`${f.file}: 再生位置がありません`);
  }
  let sameFrame = null;
  if (fs.length === 2 && fs.every((f) => Number.isFinite(f.frame?.mediaTime))) {
    sameFrame = fs[0].frame.mediaTime === fs[1].frame.mediaTime;
    if (sameFrame) {
      if (fs[1].duplicateOf !== fs[0].file) problems.push('同じコマなのに duplicateOf が付いていません');
      if (m.measurement?.independentMeasurements !== 1) problems.push(`同じコマなのに、独立した計測値が ${m.measurement?.independentMeasurements} 個です`);
    } else if (m.measurement?.independentMeasurements !== 2) problems.push('別のコマなのに、独立した計測値が2個ではありません');
  }
  return { ok: problems.length === 0, sameFrame, mediaTimes: fs.map((f) => f.frame?.mediaTime ?? null), problems };
}

/** 離れた秒の manifest を判定する */
export function evaluateSpread(m, expected) {
  const problems = [];
  if (!m || m.status !== 'ok') problems.push(`status=${m?.status ?? 'なし'}${m?.failure ? `（${m.failure.stage}: ${m.failure.cause}）` : ''}`);
  const fs = m?.frames ?? [];
  if (fs.length !== expected) problems.push(`画像が ${expected} 枚ではありません（${fs.length}枚）`);
  for (const f of fs) if (!f.measurable) problems.push(`${f.file}: 計測不可（${(f.notMeasurableReasons || []).join(',')}）`);
  if (m?.measurement && m.measurement.uniqueFrames !== fs.length) problems.push(`別々のコマが ${m.measurement.uniqueFrames} 個しかありません`);
  return { ok: problems.length === 0, mediaTimes: fs.map((f) => f.frame?.mediaTime ?? null), problems };
}

function run(script, args, env) {
  return new Promise((resolve) => {
    const c = spawn(process.execPath, script === '--test' ? ['--test', path.join(here, 'test', '*.test.mjs')] : [path.join(here, script), ...args], { env });
    let out = '';
    c.stdout.on('data', (d) => { out += d; process.stdout.write(redactText(String(d))); });
    c.stderr.on('data', (d) => { out += d; process.stderr.write(redactText(String(d))); });
    c.on('close', (code) => resolve({ code, out }));
  });
}

function takeFlag(argv, name, def) {
  const i = argv.indexOf(`--${name}`);
  if (i === -1) return def;
  const v = argv[i + 1];
  argv.splice(i, 2);
  return v;
}

const manifestIn = (dir) => {
  try { return JSON.parse(readFileSync(path.join(dir, readdirSync(dir).sort()[0], 'manifest.json'), 'utf8')); } catch { return null; }
};

export async function main(argv0, env = process.env) {
  const argv = [...argv0];
  if (argv.includes('--help')) {
    console.log('使い方: node accept.mjs [--date YYYYMMDD|today] [--pair 248.167,248.197] [--pair-race 12] [--spread 10,60,120] [--spread-race 1] [--port N など capture/verify と同じ引数]');
    return 0;
  }
  const date = takeFlag(argv, 'date', todayJst());
  const pair = takeFlag(argv, 'pair', '248.167,248.197');
  const pairRace = takeFlag(argv, 'pair-race', '12');
  const spread = takeFlag(argv, 'spread', '10,60,120');
  const spreadRace = takeFlag(argv, 'spread-race', '1');
  const base = path.join(takeFlag(argv, 'out', env.BOATCAST_OUT ?? DEFAULT_OUT), `acceptance-${nowJst().replace(/[-:+]/g, '').slice(0, 15)}`);
  mkdirSync(base, { recursive: true });
  const steps = [];
  const step = (name, ok, detail = []) => { steps.push({ name, ok, detail }); };

  console.log('\n=== 1/4 ユニットテスト ===');
  const t = await run('--test', [], env);
  step('1 ユニットテスト', t.code === 0, t.code === 0 ? [] : ['node --test が失敗しました']);

  console.log('\n=== 2/4 自己点検 ===');
  const v = await run('verify.mjs', ['--date', date, '--race', pairRace, ...argv], env);
  step('2 自己点検（verify）', v.code === 0, v.out.split('\n').filter((l) => l.startsWith('FAIL')));

  console.log('\n=== 3/4 近い2つの秒（同じコマの扱い） ===');
  const d3 = path.join(base, 'pair');
  await run('capture.mjs', ['--date', date, '--race', pairRace, '--seconds', pair, '--out', d3, ...argv], env);
  const e3 = evaluatePair(manifestIn(d3));
  step('3 近い2つの秒', e3.ok, [...e3.problems, e3.sameFrame === null ? '' : e3.sameFrame ? `同じコマでした（mediaTime ${e3.mediaTimes[0]}）。計測値は1つとして記録` : `別々のコマでした（${e3.mediaTimes.join(' / ')}）`].filter(Boolean));

  console.log('\n=== 4/4 離れた秒 ===');
  const d4 = path.join(base, 'spread');
  await run('capture.mjs', ['--date', date, '--race', spreadRace, '--seconds', spread, '--out', d4, ...argv], env);
  const e4 = evaluateSpread(manifestIn(d4), spread.split(',').length);
  step('4 離れた秒', e4.ok, e4.problems);

  const pass = steps.every((s) => s.ok);
  console.log('\n===== 受け入れ検査の結果 =====');
  for (const s of steps) {
    console.log(`${s.ok ? '合格  ' : '不合格'} ${s.name}`);
    for (const d of s.detail) console.log(`        ${redactText(d)}`);
  }
  console.log(`総合: ${pass ? '合格（正式運用してよい状態です）' : '不合格（上の「不合格」の行を、そのまま報告してください）'}`);
  const report = redactDeep({ createdAt: nowJst(), date, pass, steps, pair: e3, spread: e4 });
  writeFileSync(path.join(base, 'acceptance-report.json'), JSON.stringify(report, null, 2) + '\n');
  console.log(`記録: ${path.join(base, 'acceptance-report.json')}`);
  return pass ? 0 : 1;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) main(process.argv.slice(2)).then((c) => process.exit(c));
