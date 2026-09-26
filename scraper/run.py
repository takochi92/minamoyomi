"""定期実行のエントリポイント。GitHub Actions から 5 分おきに呼ばれる想定。

  python -m scraper.run            # 通常更新
  python -m scraper.run --now 2026-09-25T15:30   # 時刻を指定して動作確認

1回の実行でやること:
  1. その日の最初の実行なら、開催場一覧と締切時刻を取得
  2. 締切 2 時間前になったレースの出走表を取得 → 事前予想
  3. 締切 35 分前〜締切のレースは直前情報を取得 → 展示が出揃えば直前予想（締切後は予想を固定）
  4. 締切 12 分後以降のレースは結果を取得 → 的中判定
  5. 的中率・回収率を集計して stats.json を更新
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import parse
from .fetch import Fetcher
from . import odds as O
from .model import load_model
from .predict import VENUES, predict

JST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "site" / "data"
KEEP_DAYS = 14


def _load(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _save(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(p)


def _dl(date: str, hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    d = datetime.strptime(date, "%Y%m%d").replace(tzinfo=JST)
    return d + timedelta(hours=h, minutes=m)


def race_path(date, jcd, rno) -> Path:
    return DATA / "races" / date / f"{jcd}{rno:02d}.json"


def init_day(f: Fetcher, date: str) -> dict:
    venues = []
    for v in parse.parse_index(f.index(date)):
        if v["jcd"] not in VENUES:
            continue
        v["name"] = VENUES[v["jcd"]]["name"]
        deadlines = {}
        if not v["cancelled"]:
            try:
                deadlines = parse.parse_deadlines(f.racelist(v["jcd"], 1, date))
            except Exception:
                traceback.print_exc()
        v["races"] = [{"rno": r, "deadline": t} for r, t in sorted(deadlines.items())]
        venues.append(v)
    return {"date": date, "venues": venues}


def summarize(race: dict) -> dict:
    """index.json に載せる軽量サマリ。"""
    pred = race.get("prediction") or {}
    s = {"rno": race["rno"], "deadline": race["deadline"], "stage": pred.get("stage", "")}
    if pred:
        s["confidence"] = pred["confidence"]["label"]
        s["level"] = pred["confidence"]["level"]
        s["honmei"] = [m["combo"] for m in pred["bets"]["main"][:3]]
    if race.get("result", {}).get("finished"):
        s["result"] = race["result"]["trifecta"]
        s["payout"] = race["result"]["trifecta_payout"]
        s["hit"] = race.get("hit")
    if race.get("reco"):
        rc = race["reco"]
        s["reco"] = {"verdict": rc["verdict"], "comp": rc["comp"], "n": len(rc["bets"]), "top": rc["bets"][0]["combo"] if rc["bets"] else None,
                     "market_hit": rc["market_hit"], "ai_hit": rc["ai_hit"]}
        if "r_hit" in race:
            s["reco"]["hit"] = race["r_hit"]
    if pred and pred.get("in_worry"):
        s["in_worry"] = pred["in_worry"]["level"]
    spec = pred.get("specialists") if pred else None
    if spec:
        s["spec"] = [{"frame": x["frame"], "course": x["course"]} for x in spec]
        if "s_hit" in race:
            s["spec_hit"] = race["s_hit"]
    if race.get("value"):
        s["value"] = len(race["value"]["bets"])
        if race["value"]["bets"]:
            s["value_top"] = race["value"]["bets"][0]
        if "value_hit" in race:
            s["value_hit"] = race["value_hit"]
    return s


def judge(race: dict):
    pred, res = race.get("prediction"), race.get("result")
    if not pred or not res or not res.get("finished"):
        return
    bought = [b["combo"] for b in pred["bets"]["main"] + pred["bets"]["sub"]]
    hit = res["trifecta"] in bought
    race["hit"] = hit
    race["invest"] = 100 * len(bought)
    race["return"] = (res["trifecta_payout"] or 0) if hit else 0
    main = [b["combo"] for b in pred["bets"]["main"]]
    race["hit_main"] = res["trifecta"] in main
    race["invest_main"] = 100 * len(main)
    race["return_main"] = (res["trifecta_payout"] or 0) if race["hit_main"] else 0
    reco = race.get("reco")
    if reco and reco["bets"] and reco["verdict"] in ("推奨", "自信あり") and reco.get("final", True):
        # 表示している「合成オッズ配分（1,000円）」どおりに買った場合で集計
        alloc = reco.get("alloc") or {b["combo"]: 100 for b in reco["bets"]}
        race["r_hit"] = res["trifecta"] in alloc
        race["r_invest"] = sum(alloc.values())
        race["r_return"] = (res["trifecta_payout"] or 0) * alloc[res["trifecta"]] // 100 if race["r_hit"] else 0
        race["r_conf"] = reco["verdict"] == "自信あり"
    spec = pred.get("specialists") or []
    if spec and res.get("win"):
        race["s_invest"] = 100 * len(spec)
        race["s_hit"] = any(s["frame"] == res["win"] for s in spec)
        race["s_return"] = (res.get("win_payout") or 0) if race["s_hit"] else 0
    val = race.get("value")
    if val and val["bets"] and val.get("final", True):
        combos = [b["combo"] for b in val["bets"]]
        race["value_hit"] = res["trifecta"] in combos
        race["v_invest"] = 100 * len(combos)
        race["v_return"] = (res["trifecta_payout"] or 0) if race["value_hit"] else 0


def process_race(f: Fetcher, date: str, v: dict, r: dict, now: datetime) -> dict:
    jcd, rno = v["jcd"], r["rno"]
    path = race_path(date, jcd, rno)
    race = _load(path) or {"date": date, "jcd": jcd, "venue": v["name"], "rno": rno, "deadline": r["deadline"]}
    dl = _dl(date, r["deadline"])
    changed = False

    # 1) 出走表
    if "racelist" not in race and dl - timedelta(hours=2) <= now <= dl + timedelta(minutes=30):
        rl = parse.parse_racelist(f.racelist(jcd, rno, date))
        if len(rl.get("boats", [])) == 6:
            race["racelist"] = rl
            race["race_name"] = rl.get("race_name", "")
            changed = True

    # 2) 直前情報（締切前のみ予想を更新＝締切後は固定）
    if "racelist" in race and dl - timedelta(minutes=35) <= now < dl and not race.get("before_final"):
        bi = parse.parse_beforeinfo(f.beforeinfo(jcd, rno, date))
        race["before"] = bi
        if bi["exhibition_done"] and not race.get("oriten"):
            try:
                ot = parse.parse_oriten(f.oriten(jcd, rno, date)) if hasattr(f, "oriten") else None
            except Exception:
                ot = None
            if ot:
                race["oriten"] = ot
        if bi["exhibition_done"] and now >= dl - timedelta(minutes=8):
            race["before_final"] = True
        changed = True

    if "racelist" in race and now < dl and changed:
        race["prediction"] = predict(jcd, race["racelist"], race.get("before"))
        race["prediction"]["made_at"] = now.strftime("%H:%M")

    # 2b) 締切35分前〜締切：オッズを毎回取り直して表示。3連単オッズ × AI で期待値判定（締切後は固定）
    if race.get("prediction") and dl - timedelta(minutes=35) <= now < dl:
        ov = O.parse_odds3t(f.odds3t(jcd, rno, date))
        if ov:
            at = now.strftime("%H:%M")
            ex = O.parse_odds2t(f.odds2tf(jcd, rno, date)) or {}
            race["odds_pre"] = {"at": at, "v": [None if x != x else x for x in ov], "ex": ex}
            model = load_model() or {}
            val = O.value_bets(dict(zip(O.COMBOS, race["prediction"]["p3"])), ov, model.get("blend"))
            val["at"] = at
            val["final"] = now >= dl - timedelta(minutes=7)
            race["value"] = val
            reco = O.recommend(race["prediction"]["p3"], ov)
            reco["at"], reco["final"] = at, val["final"]
            race["reco"] = reco
            changed = True
        if race["prediction"].get("specialists"):
            wo = O.parse_oddstf(f.oddstf(jcd, rno, date))
            if wo:
                race["win_odds"] = {"at": now.strftime("%H:%M"), "v": [None if x != x else x for x in wo]}

    # 3) 結果
    if now >= dl + timedelta(minutes=12) and not race.get("result", {}).get("finished") and race.get("result_tries", 0) < 6:
        res = parse.parse_result(f.result(jcd, rno, date))
        race["result_tries"] = race.get("result_tries", 0) + 1
        race["result"] = res
        judge(race)
        changed = True

    if changed:
        race["updated_at"] = now.strftime("%Y-%m-%dT%H:%M")
        _save(path, race)
    return race


def build_stats():
    days = sorted(p.name for p in (DATA / "races").glob("*") if p.is_dir()) if (DATA / "races").exists() else []
    hist = _load(DATA / "history.json", {})
    for d in days:
        agg = {"races": 0, "hits": 0, "invest": 0, "return": 0, "hits_main": 0, "invest_main": 0, "return_main": 0, "best": [],
               "v_checked": 0, "v_races": 0, "v_hits": 0, "v_invest": 0, "v_return": 0, "v_best": [],
               "s_boats": 0, "s_hits": 0, "s_invest": 0, "s_return": 0,
               "r_races": 0, "r_hits": 0, "r_invest": 0, "r_return": 0, "rc_races": 0, "rc_hits": 0, "rc_invest": 0, "rc_return": 0, "gachi": 0}
        for p in sorted((DATA / "races" / d).glob("*.json")):
            r = _load(p, {})
            if r.get("hit") is None:
                continue
            if r.get("value") is not None:
                agg["v_checked"] += 1
            if r.get("reco", {}).get("verdict") == "購入非推奨":
                agg["gachi"] += 1
            if "r_hit" in r:
                agg["r_races"] += 1; agg["r_hits"] += int(r["r_hit"]); agg["r_invest"] += r["r_invest"]; agg["r_return"] += r["r_return"]
                if r.get("r_conf"):
                    agg["rc_races"] += 1; agg["rc_hits"] += int(r["r_hit"]); agg["rc_invest"] += r["r_invest"]; agg["rc_return"] += r["r_return"]
            if "s_hit" in r:
                agg["s_boats"] += r["s_invest"] // 100
                agg["s_hits"] += int(r["s_hit"])
                agg["s_invest"] += r["s_invest"]
                agg["s_return"] += r["s_return"]
            if "value_hit" in r:
                agg["v_races"] += 1
                agg["v_hits"] += int(r["value_hit"])
                agg["v_invest"] += r["v_invest"]
                agg["v_return"] += r["v_return"]
                if r["value_hit"]:
                    agg["v_best"].append({"venue": r["venue"], "rno": r["rno"], "combo": r["result"]["trifecta"],
                                          "payout": r["result"]["trifecta_payout"], "jcd": r["jcd"]})
            agg["races"] += 1
            agg["hits"] += int(r["hit"])
            agg["invest"] += r["invest"]
            agg["return"] += r["return"]
            agg["hits_main"] += int(r["hit_main"])
            agg["invest_main"] += r["invest_main"]
            agg["return_main"] += r["return_main"]
            if r["hit"]:
                agg["best"].append({"venue": r["venue"], "rno": r["rno"], "combo": r["result"]["trifecta"],
                                    "payout": r["result"]["trifecta_payout"], "jcd": r["jcd"]})
        agg["best"] = sorted(agg["best"], key=lambda x: -(x["payout"] or 0))[:5]
        agg["v_best"] = sorted(agg["v_best"], key=lambda x: -(x["payout"] or 0))[:5]
        hist[d] = agg
    _save(DATA / "history.json", hist)

    def total(keys):
        t = {"races": 0, "hits": 0, "invest": 0, "return": 0, "hits_main": 0, "invest_main": 0, "return_main": 0,
             "v_checked": 0, "v_races": 0, "v_hits": 0, "v_invest": 0, "v_return": 0,
             "s_boats": 0, "s_hits": 0, "s_invest": 0, "s_return": 0,
             "r_races": 0, "r_hits": 0, "r_invest": 0, "r_return": 0, "rc_races": 0, "rc_hits": 0, "rc_invest": 0, "rc_return": 0, "gachi": 0}
        for k in keys:
            for f in t:
                t[f] += hist[k].get(f, 0)
        return t

    keys = sorted(hist)
    stats = {
        "all": total(keys),
        "last7": total(keys[-7:]),
        "last30": total(keys[-30:]),
        "days": [{"date": k, **{f: hist[k].get(f, 0) for f in ("races", "hits", "invest", "return", "v_races", "v_invest", "v_return")}} for k in keys[-30:]],
        "v_best": sorted([dict(b, date=k) for k in keys[-30:] for b in hist[k].get("v_best", [])], key=lambda x: -(x["payout"] or 0))[:10],
        "best": sorted([dict(b, date=k) for k in keys[-30:] for b in hist[k]["best"]], key=lambda x: -(x["payout"] or 0))[:10],
    }
    _save(DATA / "stats.json", stats)


def prune(today: str):
    base = DATA / "races"
    if not base.exists():
        return
    limit = (datetime.strptime(today, "%Y%m%d") - timedelta(days=KEEP_DAYS)).strftime("%Y%m%d")
    for p in base.iterdir():
        if p.is_dir() and p.name < limit:
            shutil.rmtree(p)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--now", help="JST 時刻 (例 2026-09-25T15:30)")
    ap.add_argument("--max-requests", type=int, default=120)
    a = ap.parse_args(argv)
    now = datetime.fromisoformat(a.now).replace(tzinfo=JST) if a.now else datetime.now(JST)
    date = now.strftime("%Y%m%d")
    f = Fetcher(max_requests=a.max_requests)

    idx = _load(DATA / "index.json")
    if not idx or idx.get("date") != date:
        if now.hour < 7:
            print("race day not started yet")
            return 0
        idx = init_day(f, date)

    # 締切の近い順に処理（リクエスト上限に達しても直近レースを優先）
    jobs = [(v, r) for v in idx["venues"] for r in v["races"]]
    jobs.sort(key=lambda x: abs((_dl(date, x[1]["deadline"]) - now).total_seconds()))
    summaries = {}
    for v, r in jobs:
        if f.exhausted:
            break
        try:
            race = process_race(f, date, v, r, now)
        except Exception:
            traceback.print_exc()
            race = _load(race_path(date, v["jcd"], r["rno"])) or {"rno": r["rno"], "deadline": r["deadline"]}
        summaries[(v["jcd"], r["rno"])] = summarize(race)
    for v in idx["venues"]:
        v["races"] = [summaries.get((v["jcd"], r["rno"]), r) for r in v["races"]]

    idx["updated_at"] = now.strftime("%Y-%m-%dT%H:%M")
    _save(DATA / "index.json", idx)
    shutil.copyfile(Path(__file__).parent / "venues.json", DATA / "venues.json")
    if (Path(__file__).parent / "model_report.json").exists():
        shutil.copyfile(Path(__file__).parent / "model_report.json", DATA / "model_report.json")
    build_stats()
    prune(date)
    print(f"done: {f.count} requests")
    return 0


if __name__ == "__main__":
    sys.exit(main())
