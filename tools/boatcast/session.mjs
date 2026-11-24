// 1つの Chrome（ポート 9454・自分のプロファイル）でプレイヤーを開き、終わったら自分の Chrome だけ閉じる。
import { CdpClient } from './cdp.mjs';
import { launchChrome } from './chrome.mjs';
import { waitForVideo, ensurePlaying, watchNetwork } from './player.mjs';
import { DEFAULT_PORT, DEFAULT_PROFILE } from './args.mjs';

export function replayUrl({ slug, date, race, bitrate = 'high' }) {
  const u = new URL('https://front.player.boatrace-cdn.jp/player/vod');
  for (const [k, v] of Object.entries({ service: 'boatcast', stadium: slug, raceType: 'exhibition', raceDate: date, raceNumber: String(race), autoplay: '0', bitrate })) u.searchParams.set(k, v);
  return u.toString();
}

export async function withChrome(fn, { port = Number(process.env.BOATCAST_PORT || DEFAULT_PORT), profile = process.env.BOATCAST_PROFILE || DEFAULT_PROFILE, log = () => {} } = {}) {
  const chrome = await launchChrome({ port, profile, log });
  let cdp;
  try {
    cdp = await CdpClient.connect({ port });
    await cdp.enable();
    const net = watchNetwork(cdp);
    const open = async (url) => {
      net.httpErrors.length = 0;
      await cdp.navigate(url);
      const v = await waitForVideo(cdp, net, { timeoutMs: 45000 });
      const p = await ensurePlaying(cdp);
      if (!p.progressed) throw new Error('再生が進みません');
      await cdp.evaluate(`document.querySelector('video').pause()`);
      return v;
    };
    return await fn({ cdp, net, open, chrome });
  } finally {
    try { await cdp?.close(); } catch { /* 閉じ済み */ }
    await chrome.stop();
  }
}
