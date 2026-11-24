// 「撮った画像が、どのフレームか」の判定と記録（ブラウザ不要の純粋なロジック。テストしやすいように分けている）。
//
// 3つの時刻を混ぜない：
//   requestedSec … 指定秒（人が頼んだ秒。クランプ後は targetSec）
//   playerPosition … プレイヤー（video.currentTime）の再生位置
//   frame.mediaTime … 実際に表示されたフレームの時刻（requestVideoFrameCallback の metadata.mediaTime）
// 同じ映像で mediaTime が同じ画像は、計測上は「同じコマ」。指定秒や再生位置が違っても、別の測定値として数えない。
// 時刻を取得できない・別のコマを撮った可能性がある画像は measurable=false（計測に使わない）。

import { createHash } from 'node:crypto';

export const TOLERANCE_BEFORE_SEC = 0.5;   // seek モード：表示フレームが指定秒より何秒前まで許すか
export const TOLERANCE_AFTER_SEC = 0.1;    // 指定秒より後ろに何秒までずれてよいか（丸め誤差・タイムスタンプのずれ用）

export const REASONS = {
  'frame-time-unavailable': '表示フレームの時刻（mediaTime）を取得できませんでした',
  'seek-not-completed': 'シーク完了（seeked）を確認できませんでした',
  'frame-changed-during-capture': '撮影の前後で表示フレームが変わりました（別のコマを撮った可能性）',
  'frame-time-off-target': '表示フレームの時刻が指定秒から離れすぎています（別のコマの可能性）',
  'play-frame-range-only': 'play モードで撮影中にフレームが進みました（画像に対応するフレーム時刻を1つに決められず、範囲だけ記録）',
};

export function sha256(buf) {
  return createHash('sha256').update(buf).digest('hex');
}

/** mediaTime を比較用の文字列にする（マイクロ秒で丸める）。取得できなければ null */
export function mediaTimeKey(mediaTime) {
  return Number.isFinite(mediaTime) ? mediaTime.toFixed(6) : null;
}

/**
 * 1枚の画像を計測に使えるか判定する。
 * @param {object} o
 * @param {'seek'|'play'} o.mode
 * @param {number} o.targetSec           指定秒（クランプ後）
 * @param {{supported:boolean, mediaTime:number|null}} o.frame
 * @param {boolean} o.seeked             seeked を確認できたか
 * @param {boolean|null} o.stable        撮影の前後で表示フレームが変わらなかったか（null＝フレーム時刻を監視できず、確かめられない）
 * @param {number} [o.toleranceBefore]
 * @param {number} [o.toleranceAfter]
 * @returns {{measurable:boolean, reasons:string[], frameOffsetSec:number|null}}
 */
export function judgeFrame({ mode, targetSec, frame, seeked, stable, toleranceBefore = TOLERANCE_BEFORE_SEC, toleranceAfter = TOLERANCE_AFTER_SEC }) {
  const reasons = [];
  const has = Boolean(frame?.supported) && Number.isFinite(frame?.mediaTime);
  if (!has && !frame?.ambiguous) reasons.push('frame-time-unavailable');   // ambiguous＝play で撮影中にフレームが進み、1つに決められない（理由は play-frame-range-only 側に出す）
  if (!seeked) reasons.push('seek-not-completed');
  if (stable === false) reasons.push(mode === 'play' ? 'play-frame-range-only' : 'frame-changed-during-capture');
  const offset = has ? frame.mediaTime - targetSec : null;
  if (has && mode === 'seek' && (offset < -toleranceBefore || offset > toleranceAfter)) reasons.push('frame-time-off-target');
  return { measurable: reasons.length === 0, reasons, frameOffsetSec: offset };
}

/**
 * 同じ mediaTime の画像を「同じコマ」にまとめる（計測可能な画像だけが対象）。
 * frames[i] に frameId / duplicateOf / independentMeasurement を書き込み、要約を返す。
 * 同じコマかどうかは mediaTime で決める。画像の sha256 が違っても、同じコマとして扱う
 *   （プレイヤーのシークバーなど、画面の部品が再生位置で変わるだけのことがあるため。duplicates[].identicalImages=false と注記するだけで、警告にはしない）。
 * 警告（anomalies）にするのは「画像のバイト列が同じなのに mediaTime が違う」場合だけ
 *   （古い画面を撮った疑い。別のコマの画像のはずが、同じ画像になっている）。
 */
export function markDuplicates(frames) {
  const first = new Map();     // key → 最初の frame
  const groups = new Map();    // key → [frame...]
  for (const f of frames) {
    f.frameId = null;
    f.duplicateOf = null;
    f.independentMeasurement = false;
    const key = f.measurable ? mediaTimeKey(f.frame?.mediaTime) : null;
    if (key === null) continue;
    f.frameId = `m${key}`;
    if (!first.has(key)) {
      first.set(key, f);
      f.independentMeasurement = true;
      groups.set(key, [f]);
    } else {
      f.duplicateOf = first.get(key).file;
      groups.get(key).push(f);
    }
  }
  const duplicates = [...groups.entries()].filter(([, g]) => g.length > 1).map(([key, g]) => ({
    frameId: `m${key}`,
    mediaTime: g[0].frame.mediaTime,
    files: g.map((x) => x.file),
    requestedSecs: g.map((x) => x.requestedSec),
    identicalImages: g.every((x) => x.sha256 === g[0].sha256),
    note: g.every((x) => x.sha256 === g[0].sha256) ? null : '画像の内容は違うが同じコマ（シークバー等、画面の部品の違いの可能性）',
  }));
  const anomalies = [];
  const byHash = new Map();
  for (const f of frames.filter((x) => x.measurable && x.sha256)) {
    if (!byHash.has(f.sha256)) byHash.set(f.sha256, []);
    byHash.get(f.sha256).push(f);
  }
  for (const [, g] of byHash) {
    const keys = new Set(g.map((x) => mediaTimeKey(x.frame?.mediaTime)));
    if (keys.size > 1) anomalies.push({ kind: 'same-image-different-mediaTime', files: g.map((x) => x.file), mediaTimes: g.map((x) => x.frame.mediaTime) });
  }
  return {
    rule: '同じ映像で mediaTime が同じ画像は同じコマ（独立した計測値としては1つだけ数える）。時刻が取れない・別のコマの可能性がある画像は計測可にしない',
    images: frames.length,
    measurableImages: frames.filter((f) => f.measurable).length,
    uniqueFrames: first.size,
    independentMeasurements: frames.filter((f) => f.independentMeasurement).length,
    duplicates,
    notMeasurable: frames.filter((f) => !f.measurable).map((f) => ({ file: f.file, reasons: f.notMeasurableReasons })),
    anomalies,
  };
}

/** manifest.json の frames を、人が読む表にする（report.mjs 用）。問題があれば problems に入る */
export function summarizeManifest(m) {
  const rows = (m.frames || []).map((f) => ({
    file: f.file,
    requestedSec: f.requestedSec,
    playerPosition: f.playerPosition?.afterShot ?? f.playerPosition?.beforeShot ?? null,
    mediaTime: f.frame?.mediaTime ?? null,
    measurable: Boolean(f.measurable),
    duplicateOf: f.duplicateOf ?? null,
    reasons: f.notMeasurableReasons || [],
    sha256: (f.sha256 || '').slice(0, 12),
  }));
  const problems = [];
  if (m.status !== 'ok') problems.push(`status=${m.status}`);
  for (const r of rows) if (!r.measurable) problems.push(`${r.file}: 計測可ではありません（${r.reasons.join(', ') || '理由不明'}）`);
  for (const a of m.measurement?.anomalies || []) problems.push(`要確認 ${a.kind}: ${a.files.join(', ')}`);
  return { rows, problems };
}
