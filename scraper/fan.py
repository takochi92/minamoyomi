"""公式「ボートレーサー期別成績」（ファン手帳データ fanYYMM.lzh）から選手名簿を作る。

  python -m scraper.fan            # 公式から最新の期別成績を取得して scraper/racers.json を更新

使う項目：登番・氏名・よみ・支部・級別・年齢・出身地・勝率（固定長 Shift_JIS）
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
            "birthplace": _s(line[-6:]), "win": win,
        }
    return out


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
