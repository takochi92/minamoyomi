"""選手ごと・コースごとの「条件別」成績（直近2年）。出走表の「このコースの成績」に使う。

  python -m scraper.coursest     # 毎朝の history ジョブで windmap のあとに実行 → scraper/coursest.json.gz

条件：a＝全部、v<場>＝この場、w<風>＝風（弱い・追い風・向かい風・横風）、h<波>＝波高（0〜2cm・3〜5cm・6cm以上）
値：[出走, 1着, 3着内, ST合計(1/100秒), STの件数]（ST は F・L・不明を除く）
風は競走成績の方角を、windmap.json の場ごとのずれで「水面図の向き」に直してから、追い風・向かい風・横風に分ける。
"""
from __future__ import annotations

import gzip
import json
import math
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from . import windmap
from .history import JST, load_all

OUT = Path(__file__).parent / "coursest.json.gz"
DAYS = 730
WAVE = ["0〜2cm", "3〜5cm", "6cm以上"]


def wave_key(cm):
    if cm is None:
        return None
    return "h0" if cm <= 2 else ("h1" if cm <= 5 else "h2")


def wind_type(tail, speed):
    """predict.wind_info と同じ分け方。風速2m以下は「弱い」にまとめる"""
    if not speed or speed <= 2:
        return "弱い"
    return "追い風" if tail >= 0.5 else ("向かい風" if tail <= -0.5 else "横風")


def hist_wind(jcd, compass, speed, wm):
    """競走成績の風（方角・風速）→ 風の種類。場の対応表がなければ風が弱いときだけ分かる"""
    if not speed or speed <= 2 or compass == "無風":
        return "弱い"
    m = wm.get(jcd)
    if not m or compass not in windmap.COMPASS:
        return None
    icon = (windmap.COMPASS.index(compass) - m["offset"]) % 16
    return wind_type(math.sin(math.radians(icon * 22.5)), speed)


def build(races: list, wm: dict) -> dict:
    r_ = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: [0, 0, 0, 0, 0])))
    al = defaultdict(lambda: defaultdict(lambda: [0, 0, 0, 0, 0]))
    for r in races:
        ents = [e for e in r[11] if e[2]]
        if len(ents) < 5:
            continue
        keys = ["a", "v" + r[1]]
        w = hist_wind(r[1], r[4], r[5], wm)
        if w:
            keys.append("w" + w)
        h = wave_key(r[6])
        if h:
            keys.append(h)
        for e in ents:
            pl = e[5] if isinstance(e[5], int) else 9
            ok = e[3] is not None and not e[4]
            add = [1, int(pl == 1), int(pl <= 3), e[3] if ok else 0, int(ok)]
            for k in keys:
                for v in (r_[e[1]][e[2]][k], al[e[2]][k]):
                    for i in range(5):
                        v[i] += add[i]
    return {"r": {t: {str(c): dict(d) for c, d in cs.items()} for t, cs in r_.items()},
            "all": {str(c): dict(d) for c, d in al.items()}}


def load() -> dict:
    if not OUT.exists():
        return {}
    with gzip.open(OUT, "rt", encoding="utf-8") as f:
        return json.load(f)


def main():
    today = datetime.now(JST)
    races = load_all((today - timedelta(days=DAYS)).strftime("%Y%m%d"))
    j = build(races, windmap.load())
    dates = sorted({r[0] for r in races})
    j["window"] = f"{dates[0]}-{dates[-1]}" if dates else ""
    with gzip.open(OUT, "wt", encoding="utf-8") as f:
        json.dump(j, f, ensure_ascii=False, separators=(",", ":"))
    print("coursest:", j["window"], len(j["r"]), "racers")


if __name__ == "__main__":
    main()
