"""過去レースの確定3連単オッズと直前情報（展示の進入など）を集める（期待値の検証用）。途中で止めても続きから再開できる。

  python -m scraper.odds_backfill --max 15000     # 1回で最大15,000レース（約4〜5時間）
  python -m scraper.odds_backfill --days 3        # 直近3日分だけ（毎朝の定期実行）

公式サイトに残っている確定オッズはおおむね直近1年分。history/ にあるレースのうち、未取得のものを新しい順に取る。
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from . import odds as O
from . import parse
from .fetch import Fetcher
from .history import load_all

JST = timezone(timedelta(hours=9))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=15000)
    ap.add_argument("--days", type=int, default=365)
    a = ap.parse_args(argv)
    today = datetime.now(JST)
    since = (today - timedelta(days=a.days)).strftime("%Y%m%d")
    races = [r for r in load_all(since) if r[0] < today.strftime("%Y%m%d")]
    have = O.load_all()
    have_b = O.load_before()
    allk = {f"{r[0]}-{r[1]}-{r[2]}" for r in races}
    todo = sorted(allk - set(have), reverse=True)
    todo_b = sorted(allk - set(have_b), reverse=True)
    print("未取得", len(todo))
    f = Fetcher(max_requests=a.max)
    new = defaultdict(dict)
    miss = 0
    try:
        for k in todo:
            if f.exhausted:
                break
            d, j, r = k.split("-")
            v = O.parse_odds3t(f.get("odds3t", rno=r, jcd=j, hd=d))
            if v:
                new[d[:6]][k] = v
            else:
                miss += 1
                if miss > 300 and not new:   # 公式に残っていない古い期間に入ったら終了
                    break
        newb = {}
        for k in todo_b:
            if f.exhausted:
                break
            d, j, r = k.split("-")
            bi = parse.parse_beforeinfo(f.get("beforeinfo", rno=r, jcd=j, hd=d))
            if bi["start_exhibition"]:
                w = bi["weather"]
                newb[k] = {"entry": [s["frame"] for s in bi["start_exhibition"]],
                           "st": [s["st"] for s in bi["start_exhibition"]],
                           "tilt": {b["frame"]: b["tilt"] for b in bi["boats"]},
                           "wind": w.get("wind_speed"), "wind_dir": w.get("wind_dir"), "wave": w.get("wave_cm")}
        O.save_before(newb)
        print("直前情報", len(newb))
    finally:
        for ym, data in new.items():
            O.save_month(ym, {**O.load_month(ym), **data})
        print("取得", sum(len(v) for v in new.values()), "欠損", miss)


if __name__ == "__main__":
    main()
