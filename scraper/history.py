"""公式の競走成績（Kファイル）と番組表（Bファイル）を蓄積し、コース戦績を集計する。

  python -m scraper.history --days 3      # 直近3日分を取得（毎朝の定期実行）
  python -m scraper.history --days 1850   # 過去5年分をまとめて取得（取得済みの日は飛ばす・不足分だけで30分程度）
  python -m scraper.history --stats-only  # 取得せず集計だけやり直す

保存先
  history/YYYYMM.jsonl.gz       1レース1行（直近約3年を保持。モデル学習に使う）
  scraper/course_stats.json.gz  直近365日の集計（本番の予想で使う）
  scraper/exstats.json.gz       直近2年の選手ごとの展示タイム1位回数（出走表の「いつもの展示」）
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
EX_DAYS = 730      # 展示1位率は2年分
EXSTATS_PATH = Path(__file__).parent / "exstats.json.gz"
KEEP_DAYS = 1850   # 約5年分を残す（学習に使う）


def to_record(race: dict, b: dict) -> list:
    """学習・集計共通の1レース記録（model.Stats の docstring 参照）"""
    E = []
    for e in race["entries"]:
        E.append([e["frame"], e["toban"], e["course"],
                  round(e["st"] * 100) if e["st"] is not None else None, e["st_flag"],
                  e["place"] if e["place"] is not None else e["code"],
                  round(e["exhibit_time"] * 100) if e.get("exhibit_time") else None,
                  b.get((race["jcd"], race["rno"], e["frame"])), e.get("motor_no")])
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
        have = [v for k, v in months[ym].items() if k[0] == date]
        # 取得済みの日は飛ばす。ただしモーター番号が入っていない古い記録は取り直す（モーターの機歴に使う）
        if have and all(len(e) >= 9 and e[8] is not None for v in have for e in v[11]):
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


def ex_counts(races: list) -> dict:
    """登番 → [展示タイムがそろった出走, 6艇中いちばん速かった回数]（同タイムの1位は全員1位）"""
    out = {}
    for r in races:
        xs = [(e[6], e[1]) for e in r[11] if len(e) > 6 and e[6]]
        if len(xs) != 6:
            continue
        best = min(x for x, _ in xs)
        for x, t in xs:
            c = out.setdefault(t, [0, 0])
            c[0] += 1
            c[1] += int(x == best)
    return out


def ex_rank_table(races: list) -> dict:
    """コース → 展示タイムの順位(1〜6) → [出走, 1着, 3着内]（読みもの「展示タイムの見方」用）"""
    out = {}
    for r in races:
        es = [e for e in r[11] if len(e) > 6 and e[6] and e[2]]
        if len(es) != 6:
            continue
        xs = sorted(e[6] for e in es)
        for e in es:
            pl = e[5] if isinstance(e[5], int) else 9
            c = out.setdefault(str(e[2]), {}).setdefault(str(xs.index(e[6]) + 1), [0, 0, 0])
            c[0] += 1
            c[1] += int(pl == 1)
            c[2] += int(pl <= 3)
    return out


def build_exstats(today: datetime | None = None):
    today = today or datetime.now(JST)
    races = load_all((today - timedelta(days=EX_DAYS)).strftime("%Y%m%d"))
    dates = sorted({r[0] for r in races})
    j = {"window": f"{dates[0]}-{dates[-1]}" if dates else "", "r": ex_counts(races), "rank": ex_rank_table(races)}
    # 従来の直近2年集計は維持し、期別は保存済み全履歴で別に集計する。
    # 適用期と審査期間を分離。期別結果をその期の過去レース予想に戻して使わない。
    from .exhibition_profile import profiles
    all_races = [r for r in load_all() if r[0] < today.strftime("%Y%m%d")]
    j["term_profiles"] = profiles(all_races)
    with gzip.open(EXSTATS_PATH, "wt", encoding="utf-8") as f:
        json.dump(j, f, ensure_ascii=False, separators=(",", ":"))
    print("exstats:", j["window"], len(j["r"]), "racers")


def load_exstats(full: bool = False) -> dict:
    if not EXSTATS_PATH.exists():
        return {}
    with gzip.open(EXSTATS_PATH, "rt", encoding="utf-8") as f:
        j = json.load(f)
    return j if full else j.get("r", {})


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--stats-only", action="store_true")
    a = ap.parse_args(argv)
    if not a.stats_only:
        download(a.days)
    build_stats()
    build_exstats()


if __name__ == "__main__":
    main()
