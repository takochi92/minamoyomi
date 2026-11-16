// 全場の展示リプレイを 480p で通し、48×27 の灰色の値（数値だけ）を残す。固定カメラの場面があるかの判定用。
// 使い方: node tools/boatcast/probe-venues.mjs --out DIR --plan "01:20261108,02:20261114" [--races 6,7]
import { writeFileSync, existsSync, mkdirSync } from 'node:fs';
import path from 'node:path';
import { withChrome, replayUrl } from './session.mjs';
import { sampleGrid } from './sampler.mjs';
import { candidatesFor } from './stadium-candidates.mjs';

const a = Object.fromEntries(process.argv.slice(2).join(' ').split('--').filter(Boolean).map((x) => { const [k, ...v] = x.trim().split(/\s+/); return [k, v.join(' ')]; }));
const races = (a.races || '6,7').split(',').map(Number);
const plan = a.plan.split(',').map((x) => x.split(':'));
mkdirSync(a.out, { recursive: true });
const stopAt = Number(a.stop || 2250);
const hhmm = () => { const d = new Date(Date.now() + 9 * 3600e3); return d.getUTCHours() * 100 + d.getUTCMinutes(); };
await withChrome(async ({ cdp, open }) => {
  for (const [jo, date] of plan) {
    for (const race of races) {
      if (hhmm() >= stopAt) { console.log('stop: time'); return; }
      const file = path.join(a.out, `${jo}-${date}-${race}.json`);
      if (existsSync(file)) continue;
      let done = false;
      for (const slug of candidatesFor(jo)) {
        try {
          const low = await open(replayUrl({ slug, date, race, bitrate: 'low' }));
          const g = await sampleGrid(cdp, 0, low.duration - 0.2, { rate: 4, w: 48, h: 27, width: low.width || 854, height: low.height || 480 });
          const n = g.n; const gray = []; const times = [];
          g.meta.filter((m) => m.mt !== undefined).forEach((m, f) => {
            const row = new Array(n);
            for (let i = 0; i < n; i++) row[i] = Math.round((g.rgb[(f * n + i) * 3] + g.rgb[(f * n + i) * 3 + 1] + g.rgb[(f * n + i) * 3 + 2]) / 3);
            gray.push(row); times.push(m.mt);
          });
          writeFileSync(file, JSON.stringify({ jo, slug, date, race, duration: low.duration, times, gray }));
          console.log(jo, slug, date, race, 'frames', times.length, 'duration', Math.round(low.duration));
          done = true; break;
        } catch (e) { console.log(jo, slug, date, race, 'fail', String(e?.message || e).slice(0, 80)); }
      }
      if (!done) console.log(jo, date, race, 'no slug worked');
    }
  }
});
