// 失敗の段階（stage）と推定原因（cause）を分けて出す。
//   decode      … video.error に PIPELINE_ERROR_DECODE 系 → 起動フラグ不足の可能性
//   geo         … セグメント取得が 403、または画面に「視聴は許可されていません」系の文言 → 実行環境のIPが日本国内でない可能性
//   player-load … video 要素が出ない／duration が NaN のまま → レース未開催・リプレイ未公開の可能性
//   cdp         … 対象ページが取れない／ポート競合 → ポートを変更して再試行
// 「視聴は許可されていません」系の実際の文言は未確認（TODO）。GEO_TEXT_RE は広めの当て推量で、実機で見えた文言に合わせて直すこと。

import { redactText } from './redact.mjs';

export const STAGES = ['cdp', 'player-load', 'decode', 'geo'];

export const GEO_TEXT_RE = /視聴.{0,12}(許可|できません|ご利用いただけません)|許可されていません|お住まいの地域|海外.{0,8}(視聴|利用)|地域制限|not available in your (country|region)/i;
const MEDIA_PATH_RE = /\.(m3u8|ts|m4s|mp4|mpd|aac|cmfv|cmfa)(\/|$)|\/(manifest|playlist|segment|chunk|vod|hls)/i;
const DECODE_RE = /PIPELINE_ERROR_DECODE|DECODER_ERROR|DEMUXER_ERROR_COULD_NOT_OPEN|MEDIA_ERR_DECODE/i;

export const HINTS = {
  decode:
    'video.error が PIPELINE_ERROR_DECODE 系です。Chrome の起動フラグ不足の可能性があります。' +
    ' --headless=new --disable-gpu --disable-accelerated-video-decode --autoplay-policy=no-user-gesture-required が必須です。' +
    ' --attach で既存の Chrome に繋いでいる、または --chrome で別の Chrome を指定している場合は、その起動フラグを確認してください',
  geo:
    'セグメント取得が 403、または視聴不可の表示が出ています。実行環境のIPが日本国内でない可能性があります' +
    '（海外／データセンターIPは地域制限で 403 になる。日本国内の家庭回線の homesv では 403 にならないことを確認済み）。クラウド上では実行しないでください',
  'player-load':
    'video 要素が出ない、または duration が NaN のままです。レース未開催・リプレイ未公開の可能性があります（公開される時刻は未確認）。' +
    ' 日付・レース番号・場コードを見直し、レース後しばらくしてから再試行してください',
  cdp:
    '対象ページが取れない、またはデバッグポートが競合しています。--port を変えて再試行してください（例: --port 9455）。' +
    ' 9447 は艇ろぐ投稿ジョブ、9453 は分業相手の割当てなので使わないこと。使用中の Chrome は落とさず、空いているポートに変えるだけにします',
};

export class StageError extends Error {
  /** @param {'cdp'|'player-load'|'decode'|'geo'} stage */
  constructor(stage, cause, extra = {}) {
    super(redactText(`[${stage}] ${cause}`));
    this.name = 'StageError';
    this.stage = stage;
    this.cause_ = redactText(cause);
    this.hint = HINTS[stage];
    this.extra = extra;
  }
  toJSON() {
    return { stage: this.stage, cause: this.cause_, hint: this.hint, ...this.extra };
  }
}

/**
 * 状況から失敗の段階を決める。
 * @param {object} ctx
 * @param {string} [ctx.cdpError]       CDP 側の例外メッセージ
 * @param {object} [ctx.video]          { has, duration, error:{code,message} }
 * @param {Array}  [ctx.httpErrors]     [{host, path, status}]
 * @param {string} [ctx.pageText]       画面の文言
 * @returns {{stage:string, cause:string, hint:string}}
 */
export function classifyFailure(ctx = {}) {
  const { cdpError, video, httpErrors = [], pageText = '' } = ctx;
  const mk = (stage, cause) => ({ stage, cause: redactText(cause), hint: HINTS[stage] });
  if (cdpError) return mk('cdp', `CDP の操作に失敗しました: ${cdpError}`);

  const err = video?.error;
  const decodeErr = err && (err.code === 3 || DECODE_RE.test(err.message || ''));
  const mediaForbidden = httpErrors.filter((e) => e.status === 403 && MEDIA_PATH_RE.test(e.path || ''));
  const anyForbidden = httpErrors.filter((e) => e.status === 403);
  const geoText = GEO_TEXT_RE.test(pageText || '');
  const noDuration = !video?.has || !Number.isFinite(video.duration) || video.duration <= 0;

  if (mediaForbidden.length || geoText || (anyForbidden.length && noDuration && !decodeErr)) {
    const where = (mediaForbidden[0] || anyForbidden[0]);
    return mk('geo', geoText
      ? '画面に視聴不可系の文言が出ています'
      : `配信の取得が 403 でした（${where.host}${where.path}）`);
  }
  if (decodeErr) return mk('decode', `video.error code=${err.code} ${err.message || ''}`.trim());
  if (err) return mk('player-load', `video.error code=${err.code} ${err.message || ''}`.trim());
  if (!video?.has) return mk('player-load', 'video 要素が見つかりません');
  if (!Number.isFinite(video.duration)) return mk('player-load', 'duration が NaN のままです');
  return mk('player-load', `duration が不正です（${video.duration}）`);
}
