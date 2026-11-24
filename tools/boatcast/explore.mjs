// 場の profile を作るための調査用。縮小グリッド（数値）と、指定秒の静止画を出力先に一時保存する。
// 出力先は作業フォルダ内（.bc-tmp など）にし、profile を決めたら消すこと。リポジトリには入れない。
// 調査用：全体の縮小グリッド（数値）と、指定秒のフル解像度の静止画（.bc-tmp に一時保存。検証後に消す）
import { writeFileSync, mkdirSync } from 'node:fs';
import { withChrome, replayUrl } from './session.mjs';
import { sampleGrid } from './sampler.mjs';
const [slug, date, race, out, rate, stills] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
await withChrome(async ({ cdp, open }) => {
  const v = await open(replayUrl({ slug, date, race, bitrate: process.env.BR || 'high' }));
  const t = Date.now();
  const g = await sampleGrid(cdp, 0, v.duration - 0.2, { rate: Number(rate || 2) });
  writeFileSync(`${out}/grid.bin`, g.rgb); writeFileSync(`${out}/grid.json`, JSON.stringify({ meta: g.meta, why: g.why, size: g.size, duration: v.duration }));
  console.log('grid', g.meta.length, 'frames', g.why, ((Date.now() - t) / 1000).toFixed(1) + 's');
  for (const s of (stills || '').split(',').filter(Boolean)) {
    const r = await cdp.evaluate(`window.__bc ? null : null`);
    const url = await cdp.evaluate(`new Promise(res=>{const v=document.querySelector('video');v.pause();v.addEventListener('seeked',()=>setTimeout(()=>{const c=document.createElement('canvas');c.width=v.videoWidth;c.height=v.videoHeight;c.getContext('2d').drawImage(v,0,0);res(c.toDataURL('image/png'))},400),{once:true});v.currentTime=${s};})`);
    writeFileSync(`${out}/still-${s}.png`, Buffer.from(url.split(',')[1], 'base64'));
  }
});
