"""公式の直前情報の風向アイコン（is-wind1〜16）を、競走成績の方角（北・北東…）に直す対応表を、場ごとに作る。

  python -m scraper.windmap     # 毎朝の history ジョブで実行 → scraper/windmap.json

直前情報のアイコンは「水面図の上での向き」なので、場によって方角とのずれが違う。
同じレースの「直前情報のアイコン」と「競走成績の方角」を突き合わせて、場ごとのずれ（16方位で何コマか）を多数決で決める。
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from .history import load_all

ROOT = Path(__file__).parent
OUT = ROOT / "windmap.json"
DATA = ROOT.parent / "site" / "data" / "races"
COMPASS = ["北", "北北東", "北東", "東北東", "東", "東南東", "南東", "南南東", "南", "南南西", "南西", "西南西", "西", "西北西", "北西", "北北西"]


def build() -> dict:
    hist = {f"{r[0]}-{r[1]}-{r[2]}": r for r in load_all()}
    votes = defaultdict(Counter)
    for p in DATA.glob("*/*.json"):
        try:
            race = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        w = ((race.get("before") or {}).get("weather") or {})
        icon = w.get("wind_dir")
        if not icon or not isinstance(icon, int) or icon > 16 or not (w.get("wind_speed") or 0) >= 2:
            continue
        r = hist.get(f"{race.get('date')}-{race.get('jcd')}-{race.get('rno')}")
        if not r or r[4] not in COMPASS:
            continue
        votes[race["jcd"]][(COMPASS.index(r[4]) - (icon - 1)) % 16] += 1
    out = {}
    for jcd, c in votes.items():
        off, n = c.most_common(1)[0]
        if n >= 5:
            out[jcd] = {"offset": off, "n": n, "of": sum(c.values())}
    return out


def load() -> dict:
    if not OUT.exists():
        return {}
    return json.loads(OUT.read_text(encoding="utf-8"))


def to_compass(jcd: str, icon) -> str | None:
    """直前情報のアイコン番号 → 方角。対応表がまだ無い場は None"""
    m = load().get(jcd)
    if not m or not icon or not isinstance(icon, int) or icon > 16:
        return None
    return COMPASS[(icon - 1 + m["offset"]) % 16]


def main():
    m = build()
    OUT.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    print("windmap:", len(m), "venues")


if __name__ == "__main__":
    main()
