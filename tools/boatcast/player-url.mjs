// BOATCAST 展示リプレイのプレイヤーURLを組み立てる。
//
// 検証済み（平和島 12R・2026-11-12 の実測）
//   ・場ページ：https://race.boatcast.jp/?jo=04
//   ・プレイヤー：https://front.player.boatrace-cdn.jp/player/vod?service=boatcast&stadium=04heiwajima
//                 &raceType=exhibition&raceDate=<YYYYMMDD>&raceNumber=<レース番号>&autoplay=0&bitrate=low
// 未検証（TODO。推測で埋めない）
//   ・平和島以外の場の stadium 表記
//   ・レース本編リプレイの raceType の値
//   ・bitrate=low 以外の画質
//   ・1桁のレース番号（1〜9R）を「1」と書くか「01」と書くか（12R しか実測していない。下の padRace で切り替えて確かめる）

export const PLAYER_BASE = 'https://front.player.boatrace-cdn.jp/player/vod';
export const VENUE_PAGE_BASE = 'https://race.boatcast.jp/';

/**
 * 場コード（jo）→ { name, slug, verified }
 * slug が null の場は stadium 表記が未検証。TODO: 実機で場ページから確かめて埋める。
 */
export const STADIUMS = {
  '01': { name: '桐生', slug: null, verified: false }, // TODO: stadium 表記を実機で確認
  '02': { name: '戸田', slug: null, verified: false }, // TODO
  '03': { name: '江戸川', slug: null, verified: false }, // TODO
  '04': { name: '平和島', slug: '04heiwajima', verified: true },
  '05': { name: '多摩川', slug: null, verified: false }, // TODO
  '06': { name: '浜名湖', slug: null, verified: false }, // TODO
  '07': { name: '蒲郡', slug: null, verified: false }, // TODO
  '08': { name: '常滑', slug: null, verified: false }, // TODO
  '09': { name: '津', slug: null, verified: false }, // TODO
  '10': { name: '三国', slug: null, verified: false }, // TODO
  '11': { name: 'びわこ', slug: null, verified: false }, // TODO
  '12': { name: '住之江', slug: null, verified: false }, // TODO
  '13': { name: '尼崎', slug: null, verified: false }, // TODO
  '14': { name: '鳴門', slug: null, verified: false }, // TODO
  '15': { name: '丸亀', slug: null, verified: false }, // TODO
  '16': { name: '児島', slug: null, verified: false }, // TODO
  '17': { name: '宮島', slug: null, verified: false }, // TODO
  '18': { name: '徳山', slug: null, verified: false }, // TODO
  '19': { name: '下関', slug: null, verified: false }, // TODO
  '20': { name: '若松', slug: null, verified: false }, // TODO
  '21': { name: '芦屋', slug: null, verified: false }, // TODO
  '22': { name: '福岡', slug: null, verified: false }, // TODO
  '23': { name: '唐津', slug: null, verified: false }, // TODO
  '24': { name: '大村', slug: null, verified: false }, // TODO
};

/** raceType：検証済みは exhibition（展示）だけ。本編リプレイの値は TODO */
export const RACE_TYPES = {
  exhibition: { verified: true },
  // TODO: レース本編リプレイの raceType の値は未確認。実機で確かめるまで定義しない
};

/** 検証済みの画質は low（854×480）だけ */
export const BITRATES = { low: { verified: true, size: '854x480' } };

export class UrlBuildError extends Error {
  constructor(message) {
    super(message);
    this.name = 'UrlBuildError';
  }
}

/** 場の指定（'04' / 4 / '平和島' / 'heiwajima' / '04heiwajima'）を { jo, name, slug } にする。未検証の場は例外 */
export function resolveVenue(input = '04') {
  const raw = String(input).trim();
  let jo = null;
  if (/^\d{1,2}$/.test(raw)) jo = raw.padStart(2, '0');
  else {
    for (const [code, v] of Object.entries(STADIUMS)) {
      if (v.name === raw || (v.slug && (v.slug === raw || v.slug.replace(/^\d+/, '') === raw.toLowerCase()))) jo = code;
    }
  }
  if (!jo || !STADIUMS[jo]) throw new UrlBuildError(`場が分かりません: ${raw}（場コード 01〜24 か、平和島）`);
  const v = STADIUMS[jo];
  if (!v.slug) {
    throw new UrlBuildError(`${v.name}（jo=${jo}）の stadium 表記は未検証です（TODO）。検証済みなのは 04 平和島だけです。` +
      `実機で場ページ https://race.boatcast.jp/?jo=${jo} から確かめてから STADIUMS に追記してください`);
  }
  return { jo, name: v.name, slug: v.slug, label: v.slug.replace(/^\d+/, '') };
}

/** YYYYMMDD として実在する日付か */
export function isValidDate(s) {
  if (!/^\d{8}$/.test(String(s))) return false;
  const y = Number(s.slice(0, 4)), m = Number(s.slice(4, 6)), d = Number(s.slice(6, 8));
  const dt = new Date(Date.UTC(y, m - 1, d));
  return dt.getUTCFullYear() === y && dt.getUTCMonth() === m - 1 && dt.getUTCDate() === d;
}

/**
 * プレイヤーURLを組み立てる。
 * @param {object} o
 * @param {string} o.date      YYYYMMDD
 * @param {string|number} [o.venue='04']  場コード・場名
 * @param {number} o.race      1〜12
 * @param {string} [o.raceType='exhibition']
 * @param {string} [o.bitrate='low']
 * @param {boolean} [o.padRace=false]  1桁のレース番号を 01 の形にする（未検証。12R 以外で再生できないときの切り分け用）
 */
export function buildPlayerUrl({ date, venue = '04', race, raceType = 'exhibition', bitrate = 'low', padRace = false } = {}) {
  if (!isValidDate(date)) throw new UrlBuildError(`日付は実在する YYYYMMDD で指定してください: ${date}`);
  const n = Number(race);
  if (!Number.isInteger(n) || n < 1 || n > 12) throw new UrlBuildError(`レース番号は 1〜12 の整数です: ${race}`);
  if (!RACE_TYPES[raceType]?.verified) {
    throw new UrlBuildError(`raceType=${raceType} は未検証です（TODO）。検証済みなのは exhibition（展示）だけです`);
  }
  if (!BITRATES[bitrate]?.verified) {
    throw new UrlBuildError(`bitrate=${bitrate} は未検証です（TODO）。検証済みなのは low（854×480）だけです`);
  }
  const v = resolveVenue(venue);
  const u = new URL(PLAYER_BASE);
  u.searchParams.set('service', 'boatcast');
  u.searchParams.set('stadium', v.slug);
  u.searchParams.set('raceType', raceType);
  u.searchParams.set('raceDate', date);
  u.searchParams.set('raceNumber', padRace ? String(n).padStart(2, '0') : String(n));
  u.searchParams.set('autoplay', '0');
  u.searchParams.set('bitrate', bitrate);
  return u.toString();
}

/** 場ページのURL（人が見る用。解析には使わない） */
export function venuePageUrl(venue = '04') {
  const v = resolveVenue(venue);
  return `${VENUE_PAGE_BASE}?jo=${v.jo}`;
}
