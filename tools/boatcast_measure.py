"""BOATCAST exhibition replays -> video-measured section times (numbers only), in one command.

  python -m tools.boatcast_measure run --date 20261114 --venue 04 [--races 1,2,...] [--store PRIVATE/metrics]
  python -m tools.boatcast_measure analyze --captures .bc-tmp/cap --date 20261114 --venue 04
  python -m tools.boatcast_measure compare --files research/boatcast-measure/20261114-04.json ...

run:  replay (Chrome on the assigned port, tools/boatcast/measure-capture.mjs) -> every frame of the two
      fixed-camera shots, numbers only -> curves per boat -> rows in the independent-metrics format ->
      self-check -> the temporary numbers are deleted. The rows file keeps every boat, with the reason
      when a boat is left unmeasured, and the resolution / frame count of each shot.
No video or image is written anywhere.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from scraper import boatcast_measure as bm
from scraper import independent_metrics as im

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools" / "boatcast"
OUT = ROOT / "research" / "boatcast-measure"
WORK = ROOT / ".bc-tmp" / "measure"
MAX_SKIPPED_SHARE = .01
PROFILE_VERSION = "v1"


def jst_now():
    return datetime.now(timezone(timedelta(hours=9))).isoformat(timespec="seconds")


def profile(venue):
    return json.loads((TOOLS / "profiles" / f"{venue}.json").read_text(encoding="utf-8"))


def race_file(date, venue, race):
    path = ROOT / "site" / "data" / "races" / date / f"{venue}{race:02d}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def entries(race):
    """frame -> (motor, rider, parts) from the official race card and exhibition sheet."""
    boats = ((race or {}).get("racelist") or {}).get("boats") or []
    parts = {b["frame"]: [str(p)[:20] for p in (b.get("parts") or [])][:10]
             for b in ((race or {}).get("before") or {}).get("boats") or []}
    out = {}
    for b in boats:
        if b.get("motor_no") and b.get("toban"):
            out[b["frame"]] = (int(b["motor_no"]), str(b["toban"]), parts.get(b["frame"], []))
    return out


def analyze_race(capture_dir, prof, date, venue, race):
    manifest = json.loads((capture_dir / "manifest.json").read_text(encoding="utf-8"))
    card = entries(race_file(date, venue, race))
    report = {"race": race, "capture": manifest.get("status"), "failure": manifest.get("failure"), "shots": {}}
    rows = []
    if manifest.get("status") != "ok":
        return rows, report
    boats = sorted(card)
    done = {}
    for name, cfg in prof["shots"].items():
        if name not in manifest["shots"]:
            report["shots"][name] = {"missing": True}
            continue
        records, info = bm.measure_shot(capture_dir, name, cfg)
        if cfg.get("dropUncovered"):
            # a turn seen from the side leaves a second trace (the wake on the way out) that never spans the gates
            records = [r for r in records if "gates_not_covered" not in r["reasons"] and r.get("cover", 0) >= .25]
            for i, r in enumerate(records):
                r["order"] = i + 1
        shot_reasons = []
        if info["skipped"] and info["skipped"] > MAX_SKIPPED_SHARE * info["frames"]:
            shot_reasons.append("frames_skipped")
        if not info["sizes"] or len(info["sizes"]) != 1 or info["sizes"][0] != "1920x1080":
            shot_reasons.append("resolution")
        if cfg.get("alignWith") and len(records) != len(boats) and cfg["alignWith"] in done:
            bm.assign_by_reference(records, done[cfg["alignWith"]])
        elif cfg.get("colours"):
            bm.assign_by_colour(records, boats, cfg["colours"])
        else:
            bm.assign_boats(records, boats, use_plate=False)
        if cfg.get("lineSlope"):
            bm.line_correct(records, cfg["lineSlope"])
        if cfg.get("maxLineOffset"):
            bm.line_check(records, cfg["maxLineOffset"])
        for r in records:
            r["reasons"] += shot_reasons
        good = [r for r in records if not r["reasons"] and "boat" in r]
        if len(good) < im.MIN_BOATS_IN_RACE:
            for r in good:
                r["reasons"].append("too_few_boats_in_race")
            good = []
        for r in good:
            motor, rider, parts = card[r["boat"]]
            rows.append({"schema": im.SCHEMA, "date": date, "venue": venue, "race": race, "boat": r["boat"],
                         "motor": motor, "rider": rider, "metric": cfg["metric"], "source": "video",
                         "seconds": r["seconds"], "profile": f"{venue}-{name}-{PROFILE_VERSION}", "parts": parts})
        report["shots"][name] = {**info, "metric": cfg["metric"], "boats": records}
        done[name] = records
    return rows, report


def analyze(captures, date, venue, races, prof):
    rows, reports = [], []
    for race in races:
        d = Path(captures) / f"{date}-{venue}-{race:02d}"
        if not (d / "manifest.json").is_file():
            reports.append({"race": race, "capture": "missing"})
            continue
        try:
            r, rep = analyze_race(d, prof, date, venue, race)
        except Exception as e:          # one bad race must not lose the others; it is reported
            r, rep = [], {"race": race, "capture": "ok", "analysis_error": f"{type(e).__name__}: {e}"[:200]}
        rows += r
        reports.append(rep)
    return rows, reports


def self_check(path, rows, reports, races):
    """Fail loudly: the saved file must read back to the same rows, every row must pass the store's
    own validation, and each race-metric must hold two or more boats."""
    problems = []
    back = json.loads(path.read_text(encoding="utf-8"))
    if back["rows"] != rows:
        problems.append("rows_do_not_read_back")
    for row in rows:
        try:
            im.clean_row(row)
        except ValueError as e:
            problems.append(f"invalid_row:{row['race']}:{row['boat']}:{e}")
    per = {}
    for row in rows:
        per.setdefault((row["race"], row["metric"]), []).append(row["boat"])
    for key, boats in per.items():
        if len(boats) < im.MIN_BOATS_IN_RACE or len(set(boats)) != len(boats):
            problems.append(f"race_metric_boats:{key}")
    captured = sum(1 for r in reports if r.get("capture") == "ok")
    summary = {"races": len(races), "captured": captured, "rows": len(rows),
               "by_metric": {m: sum(1 for r in rows if r["metric"] == m) for m in im.METRICS if any(r["metric"] == m for r in rows)},
               "problems": problems, "pass": not problems and captured > 0 and len(rows) > 0}
    return summary


def write(date, venue, rows, reports, prof, out_dir=OUT):
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{date}-{venue}.json"
    doc = {"schema": 1, "date": date, "venue": venue, "created_at": jst_now(),
           "method": "boatcast-fixed-camera-space-time-v1", "profile_established": prof.get("established"),
           "rows": rows, "report": reports}
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1, allow_nan=False) + "\n", encoding="utf-8")
    return path


def run(args):
    prof = profile(args.venue)
    races = [int(x) for x in args.races.split(",")] if args.races else list(range(1, 13))
    work = Path(args.work).resolve() / f"{args.date}-{args.venue}"
    work.mkdir(parents=True, exist_ok=True)
    try:
        cmd = ["node", str(TOOLS / "measure-capture.mjs"), "--date", args.date, "--venue", args.venue,
               "--races", ",".join(map(str, races)), "--out", str(work), "--rate", str(args.rate)]
        if args.shots:
            cmd += ["--shots", args.shots]
        print("capture:", " ".join(cmd[2:]), flush=True)
        subprocess.run(cmd, cwd=TOOLS, check=False)
        rows, reports = analyze(work, args.date, args.venue, races, prof)
        path = write(args.date, args.venue, rows, reports, prof, Path(args.out))
        summary = self_check(path, rows, reports, races)
        if args.store and summary["pass"]:
            # only metrics that matched the official numbers go into the ratings
            adopted = {cfg["metric"] for cfg in prof["shots"].values() if cfg.get("adopted")}
            summary["store"] = im.Store(Path(args.store)).upsert([r for r in rows if r["metric"] in adopted])
            summary["not_adopted"] = sorted({r["metric"] for r in rows} - adopted)
        print(json.dumps(summary, ensure_ascii=False))
        print("saved:", path.relative_to(ROOT) if path.is_relative_to(ROOT) else path)
        return 0 if summary["pass"] else 1
    finally:
        if not args.keep:
            shutil.rmtree(work, ignore_errors=True)


# ------------------------------------------------------------------ comparison with official numbers
def _dev(values):
    m = sum(values) / len(values)
    return [v - m for v in values]


def official(date, venue, race):
    r = race_file(date, venue, race)
    if not r:
        return {}
    ex = {b["frame"]: b.get("exhibit_time") for b in (r.get("before") or {}).get("boats") or []}
    ori = r.get("oriten") or {}
    items, rows = ori.get("items", []), ori.get("rows", {})
    out = {}
    for b in range(1, 7):
        o = {"exhibition": ex.get(b)}
        for label, key in (("直線", "straight"), ("一周", "lap"), ("まわり足", "turn"), ("半周ラップ", "lap")):
            if label in items:
                vals = rows.get(str(b)) or []
                i = items.index(label)
                o[key] = vals[i] if i < len(vals) else None
        out[b] = o
    return out


def spearman(a, b):
    ra, rb = np.argsort(np.argsort(a)), np.argsort(np.argsort(b))
    return float(np.corrcoef(ra, rb)[0, 1])


# ------------------------------------------------------------------ yardsticks (what "agrees" means)
OFFICIAL_KEYS = ("exhibition", "straight", "turn", "lap", "accel_index")


def official_values(venue, dates, key):
    """{(date, race, boat): official time} for one item; accel_index = dev(直線) - dev(展示) of the race."""
    out = {}
    for date in dates:
        for race in range(1, 13):
            off = official(date, venue, race)
            if not off:
                continue
            if key == "accel_index":
                if all(isinstance(off[b].get("straight"), (int, float)) and isinstance(off[b].get("exhibition"), (int, float))
                       and off[b]["straight"] > 0 and off[b]["exhibition"] > 0 for b in range(1, 7)):
                    st, ex = _dev([off[b]["straight"] for b in range(1, 7)]), _dev([off[b]["exhibition"] for b in range(1, 7)])
                    for b in range(1, 7):
                        out[(date, race, b)] = st[b - 1] - ex[b - 1]
                continue
            for b in range(1, 7):
                v = off[b].get(key)
                if isinstance(v, (int, float)) and not isinstance(v, bool) and 0 < v < 120:
                    out[(date, race, b)] = float(v)
    return out


def card_values(venue, dates):
    """{(date, race, boat): (motor, rider, motor 2連対率, rider national win rate)} from the race cards."""
    out = {}
    for date in dates:
        for race in range(1, 13):
            r = race_file(date, venue, race)
            for b in ((r or {}).get("racelist") or {}).get("boats") or []:
                if b.get("motor_no") and b.get("toban"):
                    out[(date, race, b["frame"])] = (int(b["motor_no"]), str(b["toban"]), b.get("motor_2"), b.get("nat_win"))
    return out


def race_deviations(values, min_boats=3):
    by = {}
    for (date, race, boat), v in values.items():
        by.setdefault((date, race), {})[boat] = v
    out = {}
    for key, boats in by.items():
        if len(boats) >= min_boats:
            m = sum(boats.values()) / len(boats)
            for b, v in boats.items():
                out[key + (b,)] = v - m
    return out


def _meeting_of(dates):
    """Consecutive race days at the venue form one meeting (a gap of more than one day starts a new one)."""
    out, start, prev = {}, None, None
    for d in sorted(set(dates)):
        cur = datetime.strptime(d, "%Y%m%d")
        if prev is None or (cur - prev).days > 1:
            start = d
        out[d], prev = start, cur
    return out


def yardstick(values, venue, against=None, min_runs=4):
    """How well one item (video or official) works as a motor measure, by four yardsticks:
    1. per race: rank correlation with an official item over the same boats (mean over races)
    2. split-half reliability: per meeting and per motor-rider pair, the mean of odd vs even runs
    3. meeting means against the official item's meeting means
    4. meeting means against motor 2連対率 and the rider's national win rate (time: smaller = better,
       so agreement is a negative correlation)"""
    dev = race_deviations(values)
    dates = sorted({k[0] for k in dev})
    card = card_values(venue, dates)
    meet = _meeting_of(dates)
    out = {"boats": len(dev), "races": len({k[:2] for k in dev})}
    ref = race_deviations(official_values(venue, dates, against)) if against else None
    if ref:
        per_race, xs, ys = [], [], []
        for key in sorted({k[:2] for k in dev}):
            boats = [b for b in range(1, 7) if key + (b,) in dev and key + (b,) in ref]
            if len(boats) >= 4:
                a, b = [dev[key + (x,)] for x in boats], [ref[key + (x,)] for x in boats]
                if np.std(a) > 0 and np.std(b) > 0:
                    per_race.append(spearman(a, b))
            xs += [dev[key + (x,)] for x in boats]
            ys += [ref[key + (x,)] for x in boats]
        if per_race:
            out["per_race_spearman"] = [round(float(np.mean(per_race)), 3), round(float(np.std(per_race, ddof=1) / np.sqrt(len(per_race))), 3), len(per_race)]
        if len(xs) > 3:
            out["pooled_pearson"] = round(float(np.corrcoef(xs, ys)[0, 1]), 3)
    runs = {}
    for key in sorted(dev):
        if key in card:
            motor, rider = card[key][:2]
            runs.setdefault((meet[key[0]], motor, rider), []).append(key)
    pairs = {k: v for k, v in runs.items() if len(v) >= min_runs}
    if len(pairs) >= 5:
        odd = [np.mean([dev[k] for k in v[0::2]]) for v in pairs.values()]
        even = [np.mean([dev[k] for k in v[1::2]]) for v in pairs.values()]
        r = float(np.corrcoef(odd, even)[0, 1])
        out["split_half"] = {"pairs": len(pairs), "r": round(r, 3), "meeting_reliability": round(2 * r / (1 + r), 3) if r > -1 else None}
        mean = {k: float(np.mean([dev[x] for x in v])) for k, v in pairs.items()}
        ks = list(pairs)
        m2 = [(mean[k], card[pairs[k][0]][2]) for k in ks if isinstance(card[pairs[k][0]][2], (int, float))]
        win = [(mean[k], card[pairs[k][0]][3]) for k in ks if isinstance(card[pairs[k][0]][3], (int, float))]
        if len(m2) >= 5:
            out["meeting_vs_motor2"] = round(spearman(*map(list, zip(*m2))), 3)
        if len(win) >= 5:
            out["meeting_vs_rider_win"] = round(spearman(*map(list, zip(*win))), 3)
        if ref:
            both = [(mean[k], np.mean([ref[x] for x in pairs[k] if x in ref])) for k in ks
                    if sum(x in ref for x in pairs[k]) >= min_runs // 2]
            if len(both) >= 5:
                out["meeting_vs_official"] = round(spearman(*map(list, zip(*both))), 3)
    return out


def compare(files):
    """Within-race deviations of the video times against the official ones (pooled correlation)."""
    pairs = {}
    for f in files:
        doc = json.loads(Path(f).read_text(encoding="utf-8"))
        for metric in ("straight", "acceleration"):
            by_race = {}
            for row in doc["rows"]:
                if row["metric"] == metric:
                    by_race.setdefault(row["race"], {})[row["boat"]] = row["seconds"]
            for race, got in by_race.items():
                off = official(doc["date"], doc["venue"], race)
                boats = [b for b in sorted(got) if off.get(b)]
                if len(boats) < 3:
                    continue
                vid = _dev([got[b] for b in boats])
                for key in ("exhibition", "straight", "lap", "turn", "accel_index"):
                    if key == "accel_index":
                        if all(off[b].get("straight") and off[b].get("exhibition") for b in range(1, 7)):
                            st = _dev([off[b]["straight"] for b in range(1, 7)])
                            ex = _dev([off[b]["exhibition"] for b in range(1, 7)])
                            vals = [st[b - 1] - ex[b - 1] for b in boats]
                        else:
                            continue
                    else:
                        vals = [off[b].get(key) for b in boats]
                        if not all(isinstance(v, (int, float)) for v in vals):
                            continue
                        vals = _dev(vals)
                    pairs.setdefault((metric, key), []).append((vid, vals))
    out = {}
    for (metric, key), races in sorted(pairs.items()):
        x = np.concatenate([np.asarray(v) for v, _ in races])
        y = np.concatenate([np.asarray(o) for _, o in races])
        per_race = [spearman(v, o) for v, o in races if len(v) >= 4]
        out[f"{metric}~{key}"] = {"races": len(races), "boats": int(len(x)),
                                  "pearson_pooled": round(float(np.corrcoef(x, y)[0, 1]), 3),
                                  "spearman_race_mean": round(float(np.mean(per_race)), 3) if per_race else None}
    return out


def yardstick_report(files, venue, metric):
    """The video item against the official item of the same section (profile: shots.<name>.official),
    next to the official items themselves on the same days."""
    prof = profile(venue)
    against = next((cfg.get("official") for cfg in prof["shots"].values() if cfg["metric"] == metric), None)
    values = {}
    for f in files:
        doc = json.loads(Path(f).read_text(encoding="utf-8"))
        for row in doc["rows"]:
            if row["metric"] == metric:
                values[(row["date"], row["race"], row["boat"])] = row["seconds"]
    dates = sorted({k[0] for k in values})
    out = {"video": {"metric": metric, "official_section": against, **yardstick(values, venue, against)}}
    for key in OFFICIAL_KEYS:
        v = official_values(venue, dates, key)
        if v:
            out[f"official_{key}"] = yardstick(v, venue, against if key != against else None)
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run")
    r.add_argument("--date", required=True)
    r.add_argument("--venue", required=True)
    r.add_argument("--races")
    r.add_argument("--out", default=str(OUT))
    r.add_argument("--work", default=str(WORK))
    r.add_argument("--store")
    r.add_argument("--rate", type=float, default=.5, help="playback rate of the measured shots (0.5 keeps every frame)")
    r.add_argument("--keep", action="store_true", help="keep the temporary numbers (for checking)")
    r.add_argument("--shots", help="only these fixed-camera shots, e.g. straight (default: every shot of the profile)")
    a = sub.add_parser("analyze")
    a.add_argument("--captures", required=True)
    a.add_argument("--date", required=True)
    a.add_argument("--venue", required=True)
    a.add_argument("--races")
    a.add_argument("--out", default=str(OUT))
    c = sub.add_parser("compare")
    c.add_argument("--files", nargs="+", required=True)
    y = sub.add_parser("yardstick", help="video item and the official items by the same four yardsticks")
    y.add_argument("--files", nargs="+", required=True)
    y.add_argument("--venue", required=True)
    y.add_argument("--metric", default="straight")
    args = p.parse_args(argv)
    if args.command == "run":
        return run(args)
    if args.command == "analyze":
        prof = profile(args.venue)
        races = [int(x) for x in args.races.split(",")] if args.races else list(range(1, 13))
        rows, reports = analyze(Path(args.captures), args.date, args.venue, races, prof)
        path = write(args.date, args.venue, rows, reports, prof, Path(args.out))
        summary = self_check(path, rows, reports, races)
        print(json.dumps(summary, ensure_ascii=False))
        return 0 if summary["pass"] else 1
    if args.command == "yardstick":
        print(json.dumps(yardstick_report(args.files, args.venue, args.metric), ensure_ascii=False, indent=1))
        return 0
    print(json.dumps(compare(args.files), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
