"""モーターの機歴（場ごと・モーター番号ごと）。

  python -m scraper.motor      # scraper/motor.json.gz を作る（毎朝の history ジョブの中で fstart から呼ばれる）

・展示タイム：そのレースの6艇平均との差（マイナス＝速い）を、その場のモーターが新しくなってからの全レースで平均
  （モーターの入れ替え日は、番組表のモーター2連率がその場の全艇で0.00になった開催の初日から自動で判定）
・前節：直近の開催（連続した日付のまとまり）での展示タイム差・成績
・オリジナル展示（一周・まわり足・直線）：サイトに保存している直近14日分のレースから、6艇平均との差
"""
from __future__ import annotations

import gzip
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .history import load_all

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).parent / "motor.json.gz"
DAYS = 450   # 入れ替えが見つからない場のための上限（モーターはふつう1年で入れ替え）


def _d(s):
    return datetime.strptime(s, "%Y%m%d")


def renewals(races: list) -> dict:
    """場ごとの、いちばん新しいモーター入れ替え日（YYYYMMDD）。
    新モーターの最初の開催は、番組表のモーター2連率が全艇0.00になる。その開催の初日を入れ替え日とする。"""
    day = defaultdict(lambda: [0, 0])
    for r in races:
        for e in r[11]:
            b = e[7] if len(e) > 7 else None
            if b and len(b) > 5 and b[5] is not None:
                d = day[(r[1], r[0])]
                d[0] += 1
                d[1] += int(b[5] == 0)
    flagged = defaultdict(list)
    for (jcd, date), (n, z) in day.items():
        if n >= 24 and z / n >= 0.9:
            flagged[jcd].append(date)
    out = {}
    for jcd, ds in flagged.items():
        ds.sort()
        first = ds[-1]
        for d in reversed(ds[:-1]):
            if (_d(first) - _d(d)).days <= 3:
                first = d
            else:
                break
        out[jcd] = first
    return out


def build(races: list, race_files: list[dict]) -> dict:
    renew = renewals(races)
    verified = json.loads(Path(__file__).with_name("motor_renewals.json").read_text(encoding="utf-8"))
    by = defaultdict(list)          # (jcd, motor) -> [(date, exdev, place, kimarite_if_win)]
    for r in sorted(races, key=lambda r: (r[0], r[1], r[2])):
        if r[0] < renew.get(r[1], ""):
            continue
        E = r[11]
        if any(len(e) < 9 or e[8] is None for e in E):
            continue
        exs = [e[6] for e in E if e[6]]
        m = sum(exs) / len(exs) if len(exs) >= 5 else None
        for e in E:
            dev = round((e[6] - m) / 100, 3) if (m is not None and e[6]) else None
            by[(r[1], e[8])].append((r[0], dev, e[5], r[3] if e[5] == 1 else "", e[1], r[2]))
    # 表示用の全使用履歴。予想用の従来集計・直近2節は変更しない。
    # 他艇の番号欠落で、番号が確認できる艇まで履歴から落とさない。
    history = defaultdict(list)
    unknown = Counter()
    through = {}
    for r in sorted(races, key=lambda r: (r[0], r[1], r[2])):
        if r[0] < renew.get(r[1], ""):
            continue
        through[r[1]] = r[0]
        for entry in r[11]:
            if len(entry) <= 8 or entry[8] is None:
                unknown[r[1]] += 1
                continue
            history[(r[1], str(entry[8]))].append({
                "date": r[0], "rno": r[2], "toban": str(entry[1]),
                "place": entry[5], "frame": entry[0], "course": entry[2]})
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
            if not v or b.get("motor_no") is None or race.get("date", "") < renew.get(race["jcd"], ""):
                continue
            ori[(race["jcd"], b["motor_no"])].append((race.get("date", ""), {it: round(v[k] - means[it], 3) for k, it in enumerate(items) if it in means and len(v) > k and v[k]}))
    out = defaultdict(dict)
    for (jcd, mno), xs in by.items():
        devs = [x[1] for x in xs if x[1] is not None]
        # 開催ごとに分ける（日付が2日より空いたら別の開催）
        dates = sorted({x[0] for x in xs})
        meets = [[dates[0]]]
        for d in dates[1:]:
            if (_d(d) - _d(meets[-1][-1])).days <= 2:
                meets[-1].append(d)
            else:
                meets.append([d])
        last = sorted(meets[-1], reverse=True)
        ls = [x for x in xs if x[0] in set(last)]
        hist = []
        for m in reversed(meets[-2:]):
            mx = sorted((x for x in xs if x[0] in set(m)), key=lambda x: (x[0], x[5]))
            users = Counter(x[4] for x in mx)
            hist.append({"from": m[0], "to": m[-1], "toban": users.most_common(1)[0][0] if users else "",
                         "res": [x[2] if isinstance(x[2], int) else str(x[2]) for x in mx]})
        base = {"since": renew.get(jcd, xs[0][0]), "n": len(xs),
                "win": sum(1 for x in xs if x[2] == 1), "top2": sum(1 for x in xs if x[2] in (1, 2)),
                "top3": sum(1 for x in xs if x[2] in (1, 2, 3)), "meets": hist}
        if len(devs) < 5:
            out[jcd][str(mno)] = {**base, "ex": None, "makuri": 0, "last": {}}
            continue
        ld = [x[1] for x in ls if x[1] is not None]
        oo = [x for x in ori.get((jcd, mno), []) if x[0] in set(last)] or ori.get((jcd, mno), [])
        oavg = {}
        for _, dct in oo:
            for it, v in dct.items():
                oavg.setdefault(it, []).append(v)
        out[jcd][str(mno)] = {
            **base, "ex": round(sum(devs) / len(devs), 3),
            "makuri": sum(1 for x in xs if x[3] in ("まくり", "まくり差し")),
            "last": {"from": last[-1], "to": last[0], "n": len(ls), "ex": round(sum(ld) / len(ld), 3) if ld else None,
                     "win": sum(1 for x in ls if x[2] == 1), "makuri": sum(1 for x in ls if x[3] in ("まくり", "まくり差し")),
                     "ori": {it: round(sum(v) / len(v), 3) for it, v in oavg.items()}, "ori_n": len(oo)},
        }
    for (jcd, mno), rows in history.items():
        periods = []
        for row in rows:
            if (not periods or periods[-1]["toban"] != row["toban"]
                    or (_d(row["date"]) - _d(periods[-1]["to"])).days > 2):
                periods.append({"from": row["date"], "to": row["date"],
                                "toban": row["toban"], "races": []})
            periods[-1]["to"] = row["date"]
            periods[-1]["races"].append(row)
        m = out[jcd].setdefault(mno, {})
        m.update({"history": list(reversed(periods)), "history_n": len(rows),
                  "history_first": rows[0]["date"], "history_last": rows[-1]["date"],
                  "history_as_of": through[jcd], "history_unknown_motor": unknown[jcd],
                  "history_boundary": renew.get(jcd),
                  "history_boundary_source": "zero_rate_inferred" if jcd in renew else "unknown"})
        # 表示の分母は選手責任外の失格・欠場を除外。予想用の既存値は維持。
        counted = [r for r in rows if r['place'] not in ('S0', 'L0', 'K0')]
        m['history_stats'] = {'n': len(counted),
                              'top2': sum(r['place'] in (1, 2) for r in counted),
                              'top3': sum(r['place'] in (1, 2, 3) for r in counted)}
        # 確認済み日付と推定世代が一致する場合だけ公式確認済みとする。
        if renew.get(jcd) and verified.get(jcd, {}).get("date") == renew[jcd]:
            m["history_boundary_source"] = "official_confirmed"
            m["history_boundary_url"] = verified[jcd]["url"]
    # 場の中での順位（展示タイム差が小さい＝速い順）
    for jcd, ms in out.items():
        order = sorted((k for k in ms if ms[k].get("ex") is not None), key=lambda k: ms[k]["ex"])
        for i, k in enumerate(order):
            ms[k]["rank"] = i + 1
            ms[k]["of"] = len(order)
    return out


def load() -> dict:
    if not OUT.exists():
        return {}
    with gzip.open(OUT, "rt", encoding="utf-8") as f:
        return json.load(f)


def display_stats(m):
    """画面用の出走回数・連対数。旧保存形式にも対応する。"""
    return m.get('history_stats') or m


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
    from .motoradj import current_context
    today=datetime.now(timezone(timedelta(hours=9))).strftime('%Y%m%d')
    # 学習と同じ日付順の計算法・全履歴。現在日の結果は含めない。
    for j, ms in current_context([r for r in load_all() if r[0]<today]).items():
        for mno, v in ms.items():
            data.setdefault(j, {}).setdefault(mno, {}).update(v)
    # ページ生成などが同時に読む場合も、書きかけのgzipを渡さない。
    temp = OUT.with_suffix('.gz.tmp')
    with gzip.open(temp, "wt", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    temp.replace(OUT)
    print(f"motor: {sum(len(v) for v in data.values())} motors")
    for jcd, d in sorted(renewals(races).items()):
        print("  renewal", jcd, d)


if __name__ == "__main__":
    main()
