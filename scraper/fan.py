"""公式「ボートレーサー期別成績」（ファン手帳データ fanYYMM.lzh）から選手名簿を作る。

  python -m scraper.fan            # 公式から最新の期別成績を取得して scraper/racers.json を更新

使う項目：登番・氏名・よみ・支部・級別・性別・年齢・出身地・勝率・養成期（固定長 Shift_JIS）
養成期と性別は、値がそれらしいか（登番が大きいほど期が新しい、など）を確かめてから入れる。
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from .fetch import UA
from .lzh import unlzh

PATH = Path(__file__).parent / "racers.json"
URL = "https://www.boatrace.jp/static_extra/pc_static/download/data/kibetsu/fan{ym}.lzh"


def _s(b: bytes) -> str:
    return re.sub(r"[\s　]+", "", b.decode("cp932", errors="replace"))


def parse_fan(raw: bytes) -> dict:
    out = {}
    for line in raw.split(b"\r\n"):
        if len(line) < 100 or not line[:4].isdigit():
            continue
        name_raw = line[4:20].decode("cp932", errors="replace")
        parts = [p for p in re.split(r"　{2,}", name_raw.strip("　 ")) if p]
        name = " ".join(p.replace("　", "") for p in parts) if len(parts) > 1 else name_raw.replace("　", "").strip()
        try:
            win = int(line[58:62]) / 100
        except ValueError:
            win = None
        out[line[:4].decode()] = {
            "name": name, "kana": line[20:35].decode("cp932", errors="replace").strip(),
            "branch": _s(line[35:39]), "class": line[39:41].decode(), "age": int(line[49:51]) if line[49:51].isdigit() else None,
            "birthplace": _s(line[-6:]), "win": win, "_raw": line,
        }
    _add_ki_sex(out)
    for v in out.values():
        v.pop("_raw", None)
    return out


KI_AT = 195          # 公式レイアウトでの養成期の位置（算出期間の直後・3桁）。ずれていても近くを探す
SEX_AT = 48          # 性別（1=男・2=女）


def _ki_score(rows, at):
    """登番の順に並べたとき、期が増えていく（ほぼ減らない）か。値の種類が多いことも条件"""
    vals = []
    for t, raw in rows:
        b = raw[at:at + 3]
        if not b.strip().isdigit():
            return 0.0, None
        vals.append((int(t), int(b)))
    ks = [k for _, k in vals]
    if not ks or len(set(ks)) < 30 or min(ks) < 1 or max(ks) > 200:
        return 0.0, None
    vals.sort()
    ok = sum(1 for a, b in zip(vals, vals[1:]) if b[1] >= a[1])
    return ok / max(1, len(vals) - 1), dict((str(t).zfill(4), k) for t, k in vals)


def _add_ki_sex(out):
    rows = [(t, v["_raw"]) for t, v in out.items()]
    if len(rows) < 100:
        return
    best = (0.0, None)
    for at in [KI_AT] + [KI_AT + d for d in (-3, -2, -1, 1, 2, 3)]:
        sc = _ki_score(rows, at)
        if sc[0] > best[0]:
            best = sc
    if best[0] >= 0.97:
        for t, k in best[1].items():
            if t in out:
                out[t]["ki"] = k
    else:
        print("養成期が読めなかったので入れません", round(best[0], 3))
    sx = [raw[SEX_AT:SEX_AT + 1] for _, raw in rows]
    women = sx.count(b"2") / len(sx)
    if all(x in (b"1", b"2") for x in sx) and 0.03 <= women <= 0.35:
        for t, raw in rows:
            if raw[SEX_AT:SEX_AT + 1] == b"2":
                out[t]["lady"] = True
    else:
        print("性別が読めなかったので入れません")


def latest_urls(today=None):
    today = today or datetime.now(timezone(timedelta(hours=9)))
    y = today.year % 100
    cands = []
    for yy in (y, y - 1):
        for mm in ("10", "04"):
            cands.append(f"{yy:02d}{mm}")
    return [URL.format(ym=c) for c in sorted(cands, reverse=True)]


def main():
    s = requests.Session()
    s.headers["User-Agent"] = UA
    for url in latest_urls():
        r = s.get(url, timeout=30)
        if r.status_code == 200 and r.content[2:7] == b"-lh5-":
            data = parse_fan(unlzh(r.content))
            PATH.write_text(json.dumps({"source": url.rsplit("/", 1)[-1], "racers": data}, ensure_ascii=False), encoding="utf-8")
            print("racers", len(data), url)
            return
    print("fan file not found")


if __name__ == "__main__":
    main()
