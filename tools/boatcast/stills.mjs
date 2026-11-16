// 調査用：指定秒のフル解像度の静止画を一時保存（プロファイル作り用。検証後に消す）
// node tools/boatcast/stills.mjs OUT "01kiryu:20261108:6:200,230;02toda:..."
import { writeFileSync, mkdirSync } from 'node:fs';
import { withChrome, replayUrl } from './session.mjs';
const [out, plan] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
await withChrome(async ({ cdp, open }) => {
  for (const item of plan.split(';').filter(Boolean)) {
    const [slug, date, race, times] = item.split(':');
    try {
      await open(replayUrl({ slug, date, race }));
      for (const s of times.split(',')) {
        const url = await cdp.evaluate(`new Promise(res=>{const v=document.querySelector('video');v.pause();v.addEventListener('seeked',()=>setTimeout(()=>{const c=document.createElement('canvas');c.width=v.videoWidth;c.height=v.videoHeight;c.getContext('2d').drawImage(v,0,0);res(c.toDataURL('image/jpeg',0.85))},500),{once:true});v.currentTime=${s};})`);
        writeFileSync(`${out}/${slug.slice(0, 2)}-${date}-${race}-${s}.jpg`, Buffer.from(url.split(',')[1], 'base64'));
      }
      console.log('ok', slug, date, race);
    } catch (e) { console.log('fail', slug, date, race, String(e?.message || e).slice(0, 80)); }
  }
});
