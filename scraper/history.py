"""公式の競走成績（Kファイル）と番組表（Bファイル）を蓄積し、コース戦績を集計する。

  python -m scraper.history --days 3      # 直近3日分を取得（毎朝の定期実行）
  python -m scraper.history --days 1100   # 過去3年分をまとめて取得（初回のみ・30分程度）
  python -m scraper.history --stats-only  # 取得せず集計だけやり直す

保存先
  history/YYYYMM.jsonl.gz       1レース1行（直近約3年を保持。モデル学習に使う）
  scraper/course_stats.json.gz  直近365日の集計（本番の予想で使う）
"""
from __future__ import annotations

import argparse
import gzip
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from .bfile import parse_b
from .fetch import UA
from .kfile import parse_k
from .lzh import unlzh
from .model import STATS_PATH, Stats

JST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent.parent
HIST = ROOT / "history"
URL = "https://www1.mbrace.or.jp/od2/{kind}/{ym}/{k}{ymd}.lzh"
WINDOW_DAYS = 365
KEEP_DAYS = 1150


def to_record(race: dict, b: dict) -> list:
    """学習・集計共通の1レース記録（model.Stats の docstring 参照）"""
    E = []
    for e in race["entries"]:
        E.append([e["frame"], e["toban"], e["course"],
                  round(e["st"] * 100) if e["st"] is not None else None, e["st_flag"],
                  e["place"] if e["place"] is not None else e["code"],
                  round(e["exhibit_time"] * 100) if e.get("exhibit_time") else None,
                  b.get((race["jcd"], race["rno"], e["frame"]))])
    return [race["date"], race["jcd"], race["rno"], race["kimarite"], race["wind_dir"], race["wind_speed"], race["wave"],
            int(race["fixed"]), race.get("trifecta"), race.get("trifecta_payout"), race.get("trifecta_ninki"), E]


def _month_file(ym):
    return HIST / f"{ym}.jsonl.gz"


def load_month(ym) -> dict:
    p, out = _month_file(ym), {}
    if p.exists():
        with gzip.open(p, "rt", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                out[(r[0], r[1], r[2])] = r
    return out


def save_month(ym, races: dict):
    HIST.mkdir(exist_ok=True)
    with gzip.open(_month_file(ym), "wt", encoding="utf-8") as f:
        for k in sorted(races):
            f.write(json.dumps(races[k], ensure_ascii=False, separators=(",", ":")) + "\n")


def load_all(since: str = "") -> list:
    out = []
    for p in sorted(HIST.glob("*.jsonl.gz")):
        if since and p.name[:6] < since[:6]:
            continue
        with gzip.open(p, "rt", encoding="utf-8") as f:
            out += [r for r in map(json.loads, f) if r[0] >= since]
    return out


def _get(s, kind, date):
    r = s.get(URL.format(kind=kind, ym=date[:6], k=kind.lower(), ymd=date[2:]), timeout=30)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return unlzh(r.content).decode("cp932", errors="replace")


def download(days: int, today: datetime | None = None):
    today = today or datetime.now(JST)
    s = requests.Session()
    s.headers["User-Agent"] = UA
    months = {}
    for d in range(days, 0, -1):
        date = (today - timedelta(days=d)).strftime("%Y%m%d")
        ym = date[:6]
        if ym not in months:
            months[ym] = load_month(ym)
        if any(k[0] == date for k in months[ym]):
            continue
        try:
            kt = _get(s, "K", date)
            if not kt:
                continue
            bt = _get(s, "B", date)
            b = parse_b(bt) if bt else {}
            races = parse_k(kt)
        except Exception as e:
            print("skip", date, e)
            continue
        for r in races:
            months[ym][(r["date"], r["jcd"], r["rno"])] = to_record(r, b)
        print(date, len(races), "races")
        time.sleep(1.0)
    for ym, races in months.items():
        save_month(ym, races)
    limit = (today - timedelta(days=KEEP_DAYS)).strftime("%Y%m")
    for p in HIST.glob("*.jsonl.gz"):
        if p.name[:6] < limit:
            p.unlink()


def build_stats(today: datetime | None = None):
    today = today or datetime.now(JST)
    start = (today - timedelta(days=WINDOW_DAYS)).strftime("%Y%m%d")
    races = load_all(start)
    S = Stats()
    for r in races:
        S.apply(r)
    j = S.to_json()
    dates = sorted({r[0] for r in races})
    j["window"] = f"{dates[0]}-{dates[-1]}" if dates else ""
    j["races"] = len(races)
    with gzip.open(STATS_PATH, "wt", encoding="utf-8") as f:
        json.dump(j, f, ensure_ascii=False, separators=(",", ":"))
    print("stats:", j["window"], len(races), "races")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--stats-only", action="store_true")
    a = ap.parse_args(argv)
    if not a.stats_only:
        download(a.days)
    build_stats()


if __name__ == "__main__":
    main()
