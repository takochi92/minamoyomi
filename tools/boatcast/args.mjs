// capture.mjs / verify.mjs の引数解釈（外部依存なし）。環境変数でも既定値を変えられる。
//
//   BOATCAST_PORT      デバッグポート（既定 9454。9447 は艇ろぐ投稿ジョブ、9453 は分業相手の割当てなので使わない）
//   BOATCAST_PROFILE   Chrome のプロファイル（既定 /home/work/boatcast-check/profile-claude-code）
//   BOATCAST_OUT       出力先の親フォルダ（既定 /home/work/boatcast-check/claude-code/captures）
//   BOATCAST_CHROME    Chrome の実行ファイル（既定は google-chrome-stable / google-chrome / chromium を順に探す）
//   BOATCAST_CHROME_ARGS  Chrome に足す引数（空白区切り。必須フラグは常に付くので、足したいものだけ）

import { isValidDate } from './player-url.mjs';

export const DEFAULT_PORT = 9454;
export const DEFAULT_PROFILE = '/home/work/boatcast-check/profile-claude-code';
export const DEFAULT_OUT = '/home/work/boatcast-check/claude-code/captures';
export const DEFAULT_SECONDS = [10, 60, 120, 180, 200, 240, 280, 320];
export const RESERVED_PORTS = { 9447: '艇ろぐ投稿ジョブ', 9453: '分業相手（Codex）' };

export class ArgError extends Error {
  constructor(message) {
    super(message);
    this.name = 'ArgError';
  }
}

/** 日本時間の今日（YYYYMMDD） */
export function todayJst(now = new Date()) {
  const j = new Date(now.getTime() + 9 * 3600 * 1000);
  return j.toISOString().slice(0, 10).replace(/-/g, '');
}

function splitList(v) {
  return String(v).split(/[\s,]+/).filter((x) => x !== '');
}

export function parseSeconds(v) {
  const out = [];
  for (const s of splitList(v)) {
    const n = Number(s);
    if (!Number.isFinite(n) || n < 0) throw new ArgError(`取得秒数は 0 以上の数値で指定してください: ${s}`);
    if (!out.includes(n)) out.push(n);
  }
  if (!out.length) throw new ArgError('取得秒数が空です');
  return out.sort((a, b) => a - b);
}

export function parseRaces(list) {
  const out = [];
  for (const v of list) {
    for (const s of splitList(v)) {
      const n = Number(s);
      if (!Number.isInteger(n) || n < 1 || n > 12) throw new ArgError(`レース番号は 1〜12 の整数です: ${s}`);
      if (!out.includes(n)) out.push(n);
    }
  }
  return out;
}

function parsePositive(v, name) {
  const n = Number(v);
  if (!Number.isFinite(n) || n <= 0 || n > 600) throw new ArgError(`${name} は 1〜600 の秒数です: ${v}`);
  return n;
}

function parseNonNegative(v, name) {
  const n = Number(v);
  if (!Number.isFinite(n) || n < 0 || n > 10) throw new ArgError(`${name} は 0〜10 の秒数です: ${v}`);
  return n;
}

function parsePort(v) {
  const n = Number(v);
  if (!Number.isInteger(n) || n < 1024 || n > 65535) throw new ArgError(`ポートは 1024〜65535 の整数です: ${v}`);
  return n;
}

/** --flag value / --flag=value を { flag: [values...] } にする。値なしのフラグは true */
function tokenize(argv, boolFlags) {
  const out = {};
  const rest = [];
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (!a.startsWith('--')) { rest.push(a); continue; }
    let [k, v] = a.slice(2).split(/=(.*)/s, 2);
    if (boolFlags.has(k)) { out[k] = [true]; continue; }
    if (v === undefined) {
      v = argv[++i];
      if (v === undefined || v.startsWith('--')) throw new ArgError(`--${k} に値がありません`);
    }
    (out[k] ||= []).push(v);
  }
  return { flags: out, rest };
}

function common(flags, env) {
  const port = parsePort(flags.port?.[0] ?? env.BOATCAST_PORT ?? DEFAULT_PORT);
  return {
    port,
    profile: flags.profile?.[0] ?? env.BOATCAST_PROFILE ?? DEFAULT_PROFILE,
    chrome: flags.chrome?.[0] ?? env.BOATCAST_CHROME ?? null,
    extraChromeArgs: splitList(env.BOATCAST_CHROME_ARGS ?? ''),
    attach: Boolean(flags.attach),
    venue: flags.venue?.[0] ?? '04',
    padRace: Boolean(flags['pad-race']),
    playerUrl: flags['player-url']?.[0] ?? null,
    videoTimeoutMs: Math.round(parsePositive(flags['video-timeout']?.[0] ?? env.BOATCAST_VIDEO_TIMEOUT ?? 45, '--video-timeout') * 1000),
    frameToleranceSec: parseNonNegative(flags['frame-tolerance']?.[0] ?? env.BOATCAST_FRAME_TOLERANCE ?? 0.5, '--frame-tolerance'),
    reservedPortWarning: RESERVED_PORTS[port] ? `ポート ${port} は ${RESERVED_PORTS[port]} の割当てです。別のポートにしてください` : null,
  };
}

function dateOf(flags, required) {
  let d = flags.date?.[0];
  if (d === 'today') d = todayJst();
  if (d === undefined) {
    if (required) throw new ArgError('--date YYYYMMDD（または today）が必要です');
    return todayJst();
  }
  if (!isValidDate(d)) throw new ArgError(`日付は実在する YYYYMMDD で指定してください: ${d}`);
  return d;
}

const CAPTURE_BOOL = new Set(['attach', 'dry-run', 'help', 'pad-race']);
const VERIFY_BOOL = new Set(['attach', 'help', 'pad-race']);

/** capture.mjs の引数 */
export function parseCaptureArgs(argv, env = process.env) {
  const { flags, rest } = tokenize(argv, CAPTURE_BOOL);
  if (rest.length) throw new ArgError(`解釈できない引数があります: ${rest.join(' ')}（フラグは --date --race のように指定）`);
  if (flags.help) return { help: true };
  const races = parseRaces([...(flags.race ?? []), ...(flags.races ?? [])]);
  if (!races.length) throw new ArgError('--race 12 または --races 11,12 でレース番号を指定してください');
  const mode = flags.mode?.[0] ?? 'seek';
  if (!['seek', 'play', 'stream'].includes(mode)) throw new ArgError(`--mode は seek / play / stream です: ${mode}`);
  let stream = null;
  if (mode === 'stream') {
    const from = Number(flags.from?.[0]), to = Number(flags.to?.[0]);
    if (!Number.isFinite(from) || !Number.isFinite(to) || from < 0 || to <= from || to - from > 120) {
      throw new ArgError('--mode stream には --from 秒 と --to 秒 が必要です（0 <= from < to、幅は120秒まで）');
    }
    const rate = Number(flags.rate?.[0] ?? env.BOATCAST_STREAM_RATE ?? 0.5);
    if (!Number.isFinite(rate) || rate < 0.1 || rate > 1) throw new ArgError(`--rate は 0.1〜1 です: ${flags.rate?.[0]}`);
    const every = Number(flags['verify-every']?.[0] ?? 30);
    if (!Number.isInteger(every) || every < 1 || every > 600) throw new ArgError(`--verify-every は 1〜600 の整数です: ${flags['verify-every']?.[0]}`);
    stream = { from, to, rate, verifyEvery: every };
  }
  const c = common(flags, env);
  if (c.reservedPortWarning) throw new ArgError(c.reservedPortWarning);
  return {
    ...c,
    date: dateOf(flags, true),
    races,
    seconds: flags.seconds ? parseSeconds(flags.seconds.join(',')) : [...DEFAULT_SECONDS],
    out: flags.out?.[0] ?? env.BOATCAST_OUT ?? DEFAULT_OUT,
    mode,
    stream,
    dryRun: Boolean(flags['dry-run']),
  };
}

/** verify.mjs の引数 */
export function parseVerifyArgs(argv, env = process.env) {
  const { flags, rest } = tokenize(argv, VERIFY_BOOL);
  if (rest.length) throw new ArgError(`解釈できない引数があります: ${rest.join(' ')}`);
  if (flags.help) return { help: true };
  const races = parseRaces([...(flags.race ?? ['12'])]);
  const c = common(flags, env);
  if (c.reservedPortWarning) throw new ArgError(c.reservedPortWarning);
  return { ...c, date: dateOf(flags, false), race: races[0] };
}
