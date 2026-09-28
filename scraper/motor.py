"""モーターの機歴（場ごと・モーター番号ごと）。

  python -m scraper.motor      # scraper/motor.json.gz を作る（毎朝の history ジョブの中で fstart から呼ばれる）

・展示タイム：そのレースの6艇平均との差（マイナス＝速い）を、そのモーターの直近150日で平均
・前節：直近の開催（連続した日付のまとまり）での展示タイム差・成績
・オリジナル展示（一周・まわり足・直線）：サイトに保存している直近14日分のレースから、6艇平均との差
"""
from __future__ import annotations

import gzip
import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from .history import load_all

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).parent / "motor.json.gz"
DAYS = 150


def _d(s):
    return datetime.strptime(s, "%Y%m%d")


def build(races: list, race_files: list[dict]) -> dict:
    by = defaultdict(list)          # (jcd, motor) -> [(date, exdev, place, kimarite_if_win)]
    for r in sorted(races, key=lambda r: (r[0], r[1], r[2])):
        E = r[11]
        if any(len(e) < 9 or e[8] is None for e in E):
            continue
        exs = [e[6] for e in E if e[6]]
        m = sum(exs) / len(exs) if len(exs) >= 5 else None
        for e in E:
            dev = round((e[6] - m) / 100, 3) if (m is not None and e[6]) else None
            by[(r[1], e[8])].append((r[0], dev, e[5], r[3] if e[5] == 1 else ""))
    # オリジナル展示（直近14日）
    ori = defaultdict(list)          # (jcd, motor) -> [(date, {item: dev})]
    for race in race_files:
        o, rl = race.get("oriten"), (race.get("racelist") or {}).get("boats") or []
        if not o or len(rl) != 6:
            continue
        items, rows = o.get("items") or [], o.get("rows") or {}
        if len(rows) < 5:
            continue
        means = {}
        for k, it in enumerate(items):
            vals = [v[k] for v in rows.values() if len(v) > k and v[k]]
            if len(vals) >= 5:
                means[it] = sum(vals) / len(vals)
        for b in rl:
            v = rows.get(str(b["frame"]))
            if not v or b.get("motor_no") is None:
                continue
            ori[(race["jcd"], b["motor_no"])].append((race.get("date", ""), {it: round(v[k] - means[it], 3) for k, it in enumerate(items) if it in means and len(v) > k and v[k]}))
    out = defaultdict(dict)
    for (jcd, mno), xs in by.items():
        devs = [x[1] for x in xs if x[1] is not None]
        if len(devs) < 5:
            continue
        # 前節：最後の日付から遡って、2日以上空くまでを1開催とみなす
        dates = sorted({x[0] for x in xs})
        last = [dates[-1]]
        for d in reversed(dates[:-1]):
            if (_d(last[-1]) - _d(d)).days <= 2:
                last.append(d)
            else:
                break
        ls = [x for x in xs if x[0] in set(last)]
        ld = [x[1] for x in ls if x[1] is not None]
        oo = [x for x in ori.get((jcd, mno), []) if x[0] in set(last)] or ori.get((jcd, mno), [])
        oavg = {}
        for _, dct in oo:
            for it, v in dct.items():
                oavg.setdefault(it, []).append(v)
        out[jcd][str(mno)] = {
            "n": len(xs), "ex": round(sum(devs) / len(devs), 3),
            "win": sum(1 for x in xs if x[2] == 1), "top2": sum(1 for x in xs if x[2] in (1, 2)),
            "makuri": sum(1 for x in xs if x[3] in ("まくり", "まくり差し")),
            "last": {"from": last[-1], "to": last[0], "n": len(ls), "ex": round(sum(ld) / len(ld), 3) if ld else None,
                     "win": sum(1 for x in ls if x[2] == 1), "makuri": sum(1 for x in ls if x[3] in ("まくり", "まくり差し")),
                     "ori": {it: round(sum(v) / len(v), 3) for it, v in oavg.items()}, "ori_n": len(oo)},
        }
    # 場の中での順位（展示タイム差が小さい＝速い順）
    for jcd, ms in out.items():
        order = sorted(ms, key=lambda k: ms[k]["ex"])
        for i, k in enumerate(order):
            ms[k]["rank"] = i + 1
            ms[k]["of"] = len(order)
    return out


def load() -> dict:
    if not OUT.exists():
        return {}
    with gzip.open(OUT, "rt", encoding="utf-8") as f:
        return json.load(f)


def main():
    since = (datetime.now() - timedelta(days=DAYS)).strftime("%Y%m%d")
    races = load_all(since)
    files = []
    for p in sorted((ROOT / "site" / "data" / "races").glob("*/*.json")):
        try:
            files.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass
    data = build(races, files)
    with gzip.open(OUT, "wt", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"motor: {sum(len(v) for v in data.values())} motors")


if __name__ == "__main__":
    main()
