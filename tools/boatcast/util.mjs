// 小さな道具（出力先の作成・時刻・PNGサイズ）。

import { mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';

/** 日本時間の ISO 風文字列（例 2026-11-12T20:15:30+09:00） */
export function nowJst(now = new Date()) {
  const j = new Date(now.getTime() + 9 * 3600 * 1000);
  return j.toISOString().replace(/\.\d+Z$/, '+09:00');
}

/**
 * 既存のフォルダを壊さない出力先を作る。<base>/<name> があれば <name>-2、<name>-3 … と空きを探す。
 * mkdir は recursive にしない（同時に作られても取り合わない）。親フォルダだけ recursive で作る。
 * @returns {string} 作ったフォルダのパス
 */
export function makeUniqueDir(base, name) {
  mkdirSync(base, { recursive: true });
  for (let i = 1; i < 1000; i++) {
    const p = path.join(base, i === 1 ? name : `${name}-${i}`);
    try {
      mkdirSync(p);
      return p;
    } catch (e) {
      if (e.code !== 'EEXIST') throw e;
    }
  }
  throw new Error(`出力先を作れません: ${base}/${name}`);
}

/** 既存ファイルを上書きしない書き込み。あれば -2, -3 … を付ける。実際に書いたパスを返す */
export function writeNew(dir, file, data) {
  const ext = path.extname(file);
  const stem = file.slice(0, file.length - ext.length);
  for (let i = 1; i < 1000; i++) {
    const p = path.join(dir, i === 1 ? file : `${stem}-${i}${ext}`);
    try {
      writeFileSync(p, data, { flag: 'wx' });
      return p;
    } catch (e) {
      if (e.code !== 'EEXIST') throw e;
    }
  }
  throw new Error(`書き込み先がありません: ${dir}/${file}`);
}

/** フレーム画像のファイル名。f_0010s.png / 小数は f_0012p5s.png */
export function frameFileName(sec) {
  const [i, f] = String(sec).split('.');
  return `f_${i.padStart(4, '0')}${f ? `p${f}` : ''}s.png`;
}

/** PNG の幅・高さ（IHDR）。PNG でなければ null */
export function pngSize(buf) {
  if (!buf || buf.length < 24 || buf.readUInt32BE(0) !== 0x89504e47) return null;
  return { width: buf.readUInt32BE(16), height: buf.readUInt32BE(20) };
}
