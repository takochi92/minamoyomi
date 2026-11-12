#!/usr/bin/env node
// 全24場の stadium 表記を、homesv で「実際に再生して」確かめ、stadiums.json に記録する。
//
//   node venues.mjs --date 20261112                 # 全場（開催のない場は「未確認」のまま残る。別の日にもう一度実行すれば埋まる）
//   node venues.mjs --date 20261112 --venues 01,12  # 一部の場だけ
//
// 1場ずつ順番に（Chrome は1つ）：
//   ① 場ページ（?jo=XX）を開き、プレイヤーへのリクエストや iframe から stadium の値を拾う（値だけ。クエリ全体は保存しない）
//   ② ①の値 → すでに記録済みの値 → 候補（stadium-candidates.mjs の仮説）の順に、展示リプレイを開く
//   ③ 再生が始まった（duration > 0 かつ currentTime が進む）書き方だけを「確認済み」として記録する
// 再生できなかった場は記録しない（推測では埋めない）。以前に確認済みの記録は、失敗しても消さない。

import { writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { DEFAULT_PORT, DEFAULT_PROFILE, RESERVED_PORTS, todayJst } from './args.mjs';
import { CdpClient } from './cdp.mjs';
import { launchChrome } from './chrome.mjs';
import { StageError } from './failures.mjs';
import { ensurePlaying, sleep, waitForVideo, watchNetwork } from './player.mjs';
import { buildPlayerUrl, EVIDENCE, isValidDate, loadStadiumMap, stadiumMapPath, STADIUMS, venuePageUrl } from './player-url.mjs';
import { makeLogger } from './redact.mjs';
import { candidatesFor } from './stadium-candidates.mjs';
import { nowJst } from './util.mjs';

const log = makeLogger('[venues]');
const SLUG_RE = /^[0-9]{2}[a-z][a-z0-9_-]{1,30}$/i;

/** 試す順番：場ページで拾った値 → 記録済み → 内蔵 → 候補（重複は除く） */
export function candidateOrder(jo, { fromPage = [], recorded = null } = {}) {
  const out = [];
  const add = (slug, source) => { if (slug && SLUG_RE.test(slug) && slug.startsWith(jo) && !out.some((x) => x.slug === slug)) out.push({ slug, source }); };
  fromPage.forEach((s) => add(s, 'venue-page'));
  add(recorded, 'recorded');
  add(STADIUMS[jo]?.slug, 'builtin');
  candidatesFor(jo).forEach((s) => add(s, 'candidate'));
  return out;
}

/** 結果を対応表に反映する。確認できたものだけ上書きし、確認済みの記録は失敗では消さない */
export function mergeResults(map, results, { date, race, now = nowJst() } = {}) {
  const out = { ...map };
  for (const r of results) {
    if (!r.confirmed) continue;
    out[r.jo] = { slug: r.confirmed.slug, name: STADIUMS[r.jo].name, evidence: EVIDENCE.PR_TOOL_HOMESV, source: r.confirmed.source, checkedAt: now, date, race, duration: r.confirmed.duration };
  }
  return out;
}

function parse(argv) {
  const o = { date: todayJst(), race: 1, venues: Object.keys(STADIUMS), port: Number(process.env.BOATCAST_PORT || DEFAULT_PORT), profile: process.env.BOATCAST_PROFILE || DEFAULT_PROFILE, timeout: 12, padRace: false, chrome: process.env.BOATCAST_CHROME || null };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]; const v = () => argv[++i];
    if (a === '--date') { const d = v(); o.date = d === 'today' ? todayJst() : d; }
    else if (a === '--race') o.race = Number(v());
    else if (a === '--venues') { const x = v(); if (x !== 'all') o.venues = x.split(',').map((s) => s.trim().padStart(2, '0')); }
    else if (a === '--port') o.port = Number(v());
    else if (a === '--profile') o.profile = v();
    else if (a === '--chrome') o.chrome = v();
    else if (a === '--video-timeout') o.timeout = Number(v());
    else if (a === '--pad-race') o.padRace = true;
    else if (a === '--help') o.help = true;
    else throw new Error(`解釈できない引数: ${a}`);
  }
  if (!isValidDate(o.date)) throw new Error(`日付は YYYYMMDD で: ${o.date}`);
  if (!Number.isInteger(o.race) || o.race < 1 || o.race > 12) throw new Error('レース番号は 1〜12');
  if (o.venues.some((j) => !STADIUMS[j])) throw new Error('場コードは 01〜24');
  if (RESERVED_PORTS[o.port]) throw new Error(`ポート ${o.port} は ${RESERVED_PORTS[o.port]} の割当てです`);
  return o;
}

async function slugsFromVenuePage(cdp, jo, seen) {
  seen.clear();
  try { await cdp.navigate(venuePageUrl(jo), { waitLoadMs: 12000 }); } catch { return []; }
  await sleep(3000);
  let dom = [];
  try {
    dom = await cdp.evaluate(`(() => { const out = []; const re = /stadium=([0-9]{2}[A-Za-z][A-Za-z0-9_-]{1,30})/g;
      const srcs = [...document.querySelectorAll('iframe,a,video,source')].map((e) => e.src || e.href || '').join(' ') + ' ' + document.documentElement.innerHTML.slice(0, 400000);
      let m; while ((m = re.exec(srcs))) out.push(m[1]); return [...new Set(out)].slice(0, 10); })()`);
  } catch { /* ページが読めなくても候補で続ける */ }
  return [...new Set([...seen, ...(dom || [])])].filter((s) => s.startsWith(jo));
}

export async function main(argv) {
  let o;
  try { o = parse(argv); } catch (e) { console.error(`引数エラー: ${e.message}`); return 2; }
  if (o.help) { console.log('使い方: node venues.mjs [--date YYYYMMDD|today] [--race 1] [--venues all|01,02] [--port N] [--video-timeout 12] [--pad-race]'); return 0; }
  const file = stadiumMapPath();
  const map = loadStadiumMap(file);
  let chrome = null; let cdp = null; const results = [];
  try {
    chrome = await launchChrome({ chrome: o.chrome, port: o.port, profile: o.profile, log });
    log(`Chrome PID=${chrome.pid} ${chrome.version}`);
    cdp = await CdpClient.connect({ port: o.port });
    await cdp.enable(['Page', 'Runtime', 'Network']);
    const net = watchNetwork(cdp);
    const seen = new Set();
    cdp.on('Network.requestWillBeSent', (p) => {
      try { const s = new URL(p.request.url).searchParams.get('stadium'); if (s && SLUG_RE.test(s)) seen.add(s); } catch { /* URL でないものは無視 */ }
    });
    for (const jo of o.venues) {
      const name = STADIUMS[jo].name;
      const fromPage = await slugsFromVenuePage(cdp, jo, seen);
      const cands = candidateOrder(jo, { fromPage, recorded: map[jo]?.slug });
      const r = { jo, name, fromPage, tried: [], confirmed: null };
      for (const c of cands) {
        net.httpErrors.length = 0; net.failed.length = 0;
        const url = buildPlayerUrl({ date: o.date, race: o.race, slug: c.slug, padRace: o.padRace });
        try {
          await cdp.navigate(url);
          const v = await waitForVideo(cdp, net, { timeoutMs: o.timeout * 1000 });
          const play = await ensurePlaying(cdp, { attempts: 2 });
          if (play.progressed) { r.confirmed = { ...c, duration: v.duration }; r.tried.push({ ...c, ok: true }); break; }
          r.tried.push({ ...c, ok: false, stage: 'no-progress' });
        } catch (e) {
          r.tried.push({ ...c, ok: false, stage: e instanceof StageError ? e.stage : 'error' });
          if (e instanceof StageError && e.stage === 'cdp') throw e;
        }
      }
      results.push(r);
      log(r.confirmed
        ? `確認済み ${jo} ${name}: ${r.confirmed.slug} （見つけ方: ${r.confirmed.source} / duration ${r.confirmed.duration}s）`
        : `未確認   ${jo} ${name}: 再生できず（試した数 ${r.tried.length}: ${r.tried.map((t) => `${t.slug}→${t.stage}`).join(', ') || 'なし'}）。この日に開催がない・リプレイ未公開の可能性`);
    }
  } catch (e) {
    log(`中断 [${e.stage || 'error'}] ${e.message}`);
    if (e.hint) log(`  対処: ${e.hint}`);
  } finally {
    if (cdp) await cdp.close();
    if (chrome) { await chrome.stop(); log(`Chrome PID=${chrome.pid} を終了しました（自分が起動した PID のみ）`); }
  }
  const merged = mergeResults(map, results, { date: o.date, race: o.race });
  if (file && results.some((r) => r.confirmed)) {
    writeFileSync(file, JSON.stringify({ note: 'venues.mjs が homesv で再生を確認できた書き方だけを記録（evidence 参照）', updatedAt: nowJst(), stadiums: merged }, null, 2) + '\n');
    log(`記録: ${file}`);
  }
  const usable = Object.keys(STADIUMS).sort().filter((jo) => STADIUMS[jo].slug || merged[jo]);
  const missing = Object.keys(STADIUMS).sort().filter((jo) => !usable.includes(jo));
  console.log(`\n今回 確認できた場: ${results.filter((r) => r.confirmed).length} / 試した場 ${results.length}`);
  console.log(`使える場の合計: ${usable.length} / 24`);
  if (missing.length) console.log(`まだ使えない場: ${missing.map((jo) => `${jo}${STADIUMS[jo].name}`).join(' ')}（開催のある日に、もう一度 node venues.mjs --date <日付> --venues ${missing.join(',')}）`);
  else console.log('全24場が使えます');
  return 0;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) main(process.argv.slice(2)).then((c) => process.exit(c));
