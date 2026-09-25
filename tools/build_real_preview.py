"""ブラウザで取得した当日の実データ(JSON)から、プレビュー用のバンドルと当日の成績集計を作る（開発用）。

  python tools/build_real_preview.py today_full.json out.json "2026-09-25T20:40"

入力の各レース: rl(出走表) bi(直前情報) rs(結果: [3連単, 払戻, 決まり手, 単勝艇, 単勝払戻]) o3(3連単オッズ) o2(2連単) ot(単勝)
終わったレースの予想は、同じ直前情報で締切後に計算した「検証」。オッズは取得時点（終了レースは確定オッズ）。
"""
import json
import sys
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scraper import odds as O, parse, run  # noqa: E402
from scraper.model import load_model  # noqa: E402
from scraper.predict import VENUES, predict  # noqa: E402


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return float("nan")


src, dst, now_s = sys.argv[1], sys.argv[2], sys.argv[3]
BLEND = (load_model() or {}).get("blend")
NOW = datetime.fromisoformat(now_s)
DATE = NOW.strftime("%Y%m%d")
job = json.loads(Path(src).read_text(encoding="utf-8"))
AT = job.get("at", "")
files = {}
idx = {"date": DATE, "updated_at": NOW.strftime("%Y-%m-%dT%H:%M"), "venues": []}
tmp = Path(tempfile.mkdtemp())
report = defaultdict(lambda: defaultdict(int))

for v in job["venues"]:
    ven = {"jcd": v["jcd"], "name": VENUES[v["jcd"]]["name"], "title": v["title"], "grade": v["grade"],
           "timezone": v["tz"], "day": v["day"], "cancelled": False, "races": []}
    for r in sorted(v["races"], key=lambda x: x["r"]):
        rl = r.get("rl")
        if not rl or len(rl["b"]) != 6:
            continue
        rno = r["r"]
        dl = rl["dl"][rno - 1]
        racelist = {"boats": [{"frame": int(b[0]), "toban": b[1], "name": b[2], "class": b[3], "branch": b[4], "f": int(b[5] or 0),
                               "avg_st": b[6], "nat_win": b[7], "loc_win": b[8], "motor_2": b[9], "boat_2": b[10]} for b in rl["b"]],
                    "fixed_entry": bool(rl["fx"]), "race_name": rl["rn"]}
        bi = None
        if r.get("bi") and r["bi"]["b"]:
            B = r["bi"]
            st = []
            for i, (f, s) in enumerate(B["st"], 1):
                if f is None:
                    continue
                v2, flag = parse._st_value(s)
                st.append({"course": i, "frame": int(f), "st": v2, "flag": flag})
            w = B["w"] or [None] * 7
            bi = {"boats": [{"frame": int(b[0]), "exhibit_time": b[1] if b[1] and b[1] > 0 else None, "tilt": b[2], "parts": b[3], "propeller": ""}
                            for b in B["b"] if b[0] is not None],
                  "start_exhibition": st if len(st) == 6 else [],
                  "weather": {"as_of": w[0], "air_temp": w[1], "weather": w[2], "wind_speed": w[3], "water_temp": w[4], "wave_cm": w[5], "wind_dir": w[6]}}
            bi["exhibition_done"] = len(bi["boats"]) == 6 and all(b["exhibit_time"] for b in bi["boats"])
            if not bi["exhibition_done"]:
                bi = None
        race = {"date": DATE, "jcd": v["jcd"], "venue": ven["name"], "rno": rno, "deadline": dl, "race_name": rl["rn"], "racelist": racelist}
        if bi:
            race["before"] = bi
        pred = predict(v["jcd"], racelist, bi)
        pred["made_at"] = "検証" if r.get("rs") else NOW.strftime("%H:%M")
        race["prediction"] = pred
        if r.get("o3"):
            ov = [fnum(x) for x in r["o3"]]
            ex = {}
            for i, c in enumerate(r.get("o2") or []):
                a = i % 6 + 1
                b2 = [x for x in range(1, 7) if x != a][i // 6]
                if fnum(c) == fnum(c):
                    ex[f"{a}-{b2}"] = fnum(c)
            race["odds_pre"] = {"at": AT, "v": [None if x != x else x for x in ov], "ex": ex}
            val = O.value_bets(dict(zip(O.COMBOS, pred["p3"])), ov, BLEND)
            val["at"] = AT
            race["value"] = val
            reco = O.recommend(pred["p3"], ov)
            reco["at"] = AT
            race["reco"] = reco
        if r.get("ot") and pred.get("specialists"):
            race["win_odds"] = {"at": AT, "v": [None if fnum(x) != fnum(x) else fnum(x) for x in r["ot"]]}
        if r.get("rs"):
            tri, pay, kim, win, wpay = (list(r["rs"]) + [None, None])[:5]
            race["result"] = {"trifecta": tri, "trifecta_payout": pay, "kimarite": kim, "win": win, "win_payout": wpay, "finished": True}
            run.judge(race)
            rep = report[ven["name"]]
            rep["races"] += 1
            top = max(pred["boats"], key=lambda b: b["p_win"])
            rep["fav_win"] += int(win == top["frame"])
            order = sorted(zip(O.COMBOS, pred["p3"]), key=lambda x: -x[1])
            rep["top1"] += int(order[0][0] == tri)
            rep["main_hit"] += int(race["hit_main"]); rep["main_inv"] += race["invest_main"]; rep["main_ret"] += race["return_main"]
            rep["all_hit"] += int(race["hit"]); rep["all_inv"] += race["invest"]; rep["all_ret"] += race["return"]
            if "s_hit" in race:
                rep["s_boats"] += race["s_invest"] // 100; rep["s_hit"] += int(race["s_hit"]); rep["s_inv"] += race["s_invest"]; rep["s_ret"] += race["s_return"]
            if race.get("reco", {}).get("verdict") == "購入非推奨":
                rep["gachi"] += 1
            if "r_hit" in race:
                rep["r_races"] += 1; rep["r_hit"] += int(race["r_hit"]); rep["r_inv"] += race["r_invest"]; rep["r_ret"] += race["r_return"]
                if race.get("r_conf"):
                    rep["rc_races"] += 1; rep["rc_hit"] += int(race["r_hit"]); rep["rc_inv"] += race["r_invest"]; rep["rc_ret"] += race["r_return"]
            if "value_hit" in race:
                rep["v_races"] += 1; rep["v_hit"] += int(race["value_hit"]); rep["v_inv"] += race["v_invest"]; rep["v_ret"] += race["v_return"]
        files[f"races/{DATE}/{v['jcd']}{rno:02d}.json"] = race
        p = tmp / "races" / DATE / f"{v['jcd']}{rno:02d}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(race, ensure_ascii=False), encoding="utf-8")
        ven["races"].append(run.summarize(race))
    idx["venues"].append(ven)

run.DATA = tmp
run.build_stats()
stats = json.loads((tmp / "stats.json").read_text(encoding="utf-8"))
stats["note"] = f"プレビュー用：9/25の全レースを、同じ直前情報で締切後に計算し直した検証です（オッズは{AT}時点の確定オッズ）。締切前に掲載した実績ではありません。"
tot = defaultdict(int)
for v in report.values():
    for k, x in v.items():
        tot[k] += x
stats["day_report"] = {"venues": {k: dict(v) for k, v in report.items()}, "total": dict(tot)}
files["index.json"] = idx
files["venues.json"] = json.loads((ROOT / "scraper" / "venues.json").read_text(encoding="utf-8"))
files["stats.json"] = stats
files["model_report.json"] = json.loads((ROOT / "scraper" / "model_report.json").read_text(encoding="utf-8"))
files["now"] = int(NOW.replace(tzinfo=run.JST).timestamp() * 1000)
Path(dst).write_text(json.dumps(files, ensure_ascii=False), encoding="utf-8")
print(json.dumps(stats["day_report"], ensure_ascii=False))
