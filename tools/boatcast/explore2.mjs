// 場の profile を作るための調査用：矩形の格子点の値（数値）を一時保存する。作業フォルダ内に出し、使い終わったら消す。
// 調査用：矩形の格子点の RGB を、[t0,t1] の全コマで取る（数値のみ。.bc-tmp に一時保存）
import { writeFileSync, mkdirSync } from 'node:fs';
import { withChrome, replayUrl } from './session.mjs';
import { samplePoints } from './sampler.mjs';
const [slug, date, race, out, ...jobs] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
await withChrome(async ({ cdp, open }) => {
  await open(replayUrl({ slug, date, race }));
  for (const job of jobs) {   // name:t0:t1:x0:y0:x1:y1:stride
    const [name, t0, t1, x0, y0, x1, y1, st] = job.split(':'); const s = Number(st);
    const pts = []; let nx = 0, ny = 0;
    for (let y = Number(y0); y < Number(y1); y += s) { ny++; nx = 0; for (let x = Number(x0); x < Number(x1); x += s) { pts.push([x, y]); nx++; } }
    const t = Date.now();
    const r = await samplePoints(cdp, pts, Number(t0), Number(t1), { rate: 0.5 });
    writeFileSync(`${out}/${name}.bin`, r.rgb);
    writeFileSync(`${out}/${name}.json`, JSON.stringify({ meta: r.meta, why: r.why, size: r.size, nx, ny, x0: Number(x0), y0: Number(y0), stride: s }));
    console.log(name, r.meta.length, r.why, ((Date.now() - t) / 1000).toFixed(0) + 's');
  }
});
