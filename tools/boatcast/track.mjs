// 調査用：指定した区間を 240x135 の灰色の値（数値だけ）で取る。プロファイルの道すじを動きから決めるため
// node tools/boatcast/track.mjs OUT "01kiryu:20261108:6:219-253,272-300;..."
import { writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { withChrome, replayUrl } from './session.mjs';
import { sampleGrid } from './sampler.mjs';
const [out, plan, stop] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
const hhmm = () => { const d = new Date(Date.now() + 9 * 3600e3); return d.getUTCHours() * 100 + d.getUTCMinutes(); };
await withChrome(async ({ cdp, open }) => {
  for (const item of plan.split(';').filter(Boolean)) {
    if (hhmm() >= Number(stop || 2200)) { console.log('stop: time'); return; }
    const [slug, date, race, segs] = item.split(':');
    try {
      const v = await open(replayUrl({ slug, date, race }));
      for (const seg of segs.split(',')) {
        const file = `${out}/${slug.slice(0, 2)}-${date}-${race}-${seg}`;
        if (existsSync(file + '.json')) continue;
        const [a, b] = seg.split('-').map(Number);
        const g = await sampleGrid(cdp, a, b, { rate: 2, w: 240, h: 135, width: v.width || 1920, height: v.height || 1080 });
        const meta = g.meta.filter((m) => m.mt !== undefined);
        const n = 240 * 135, gray = Buffer.alloc(meta.length * n);
        for (let f = 0; f < meta.length; f++) for (let i = 0; i < n; i++) gray[f * n + i] = (g.rgb[(f * n + i) * 3] + g.rgb[(f * n + i) * 3 + 1] + g.rgb[(f * n + i) * 3 + 2]) / 3;
        writeFileSync(file + '.bin', gray); writeFileSync(file + '.json', JSON.stringify({ times: meta.map((m) => m.mt), w: 240, h: 135, size: [v.width, v.height] }));
        console.log('ok', slug, seg, meta.length);
      }
    } catch (e) { console.log('fail', slug, date, race, String(e?.message || e).slice(0, 100)); }
  }
});
