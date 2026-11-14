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
    for name, cfg in prof["shots"].items():
        if name not in manifest["shots"]:
            report["shots"][name] = {"missing": True}
            continue
        records, info = bm.measure_shot(capture_dir, name, cfg)
        shot_reasons = []
        if info["skipped"] and info["skipped"] > MAX_SKIPPED_SHARE * info["frames"]:
            shot_reasons.append("frames_skipped")
        if not info["sizes"] or len(info["sizes"]) != 1 or info["sizes"][0] != "1920x1080":
            shot_reasons.append("resolution")
        bm.assign_boats(records, boats, use_plate=False)
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
    return rows, report


def analyze(captures, date, venue, races, prof):
    rows, reports = [], []
    for race in races:
        d = Path(captures) / f"{date}-{venue}-{race:02d}"
        if not (d / "manifest.json").is_file():
            reports.append({"race": race, "capture": "missing"})
            continue
        r, rep = analyze_race(d, prof, date, venue, race)
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
    work = Path(args.work) / f"{args.date}-{args.venue}"
    work.mkdir(parents=True, exist_ok=True)
    try:
        cmd = ["node", str(TOOLS / "measure-capture.mjs"), "--date", args.date, "--venue", args.venue,
               "--races", ",".join(map(str, races)), "--out", str(work)]
        print("capture:", " ".join(cmd[2:]), flush=True)
        subprocess.run(cmd, cwd=TOOLS, check=False)
        rows, reports = analyze(work, args.date, args.venue, races, prof)
        path = write(args.date, args.venue, rows, reports, prof, Path(args.out))
        summary = self_check(path, rows, reports, races)
        if args.store and summary["pass"]:
            summary["store"] = im.Store(Path(args.store)).upsert(rows)
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
    r.add_argument("--keep", action="store_true", help="keep the temporary numbers (for checking)")
    a = sub.add_parser("analyze")
    a.add_argument("--captures", required=True)
    a.add_argument("--date", required=True)
    a.add_argument("--venue", required=True)
    a.add_argument("--races")
    a.add_argument("--out", default=str(OUT))
    c = sub.add_parser("compare")
    c.add_argument("--files", nargs="+", required=True)
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
    print(json.dumps(compare(args.files), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
