"""Nightly entry points for the independent (video-measured) exhibition metrics.

  python -m tools.independent_metrics ingest   --store PRIVATE/metrics --input PRIVATE/rows.json
  python -m tools.independent_metrics rate     --store PRIVATE/metrics --through 20261112 --output PRIVATE/ratings.json
  python -m tools.independent_metrics validate --store PRIVATE/metrics --through 20261112

`rows.json` is {"rows": [{date, venue, race, boat, motor, rider, metric, seconds, source: "video", profile, parts}]}.
The store and every output stay outside site/. Fleet starts come from the same ledger the motor pages use;
a venue whose fleet start is unknown or pending is skipped, so an old motor's numbers are never carried over.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from scraper import independent_metrics as im
from scraper import motor_generation

ROOT = Path(__file__).resolve().parents[1]


def private(path):
    path = Path(path).resolve()
    if path.is_relative_to(ROOT / "site"):
        raise SystemExit("independent metrics must stay outside site/")
    return path


def fleet_starts(through, data=ROOT / "site" / "data"):
    periods = motor_generation.live_periods(data, through)
    return {venue: period["date"] for venue, period in periods["venues"].items()
            if venue not in periods["pending"]}


def schedules(data=ROOT / "site" / "data"):
    out = defaultdict(list)
    for path in (data / "meetings").glob("*.json"):
        meeting = json.loads(path.read_text(encoding="utf-8"))
        out[meeting["jcd"]].append((meeting["start"], meeting["end"]))
    return out


def rate(store, through, starts, meeting_dates):
    rows = store.rows(through=through)
    baselines = im.rider_baselines(im.race_deviations(rows), through)
    venues = {}
    for venue in sorted(im.VENUES):
        start = starts.get(venue)
        ratings = im.venue_ratings(rows, venue, through, start, baselines=baselines,
                                   schedule=meeting_dates.get(venue) or None)
        if ratings:
            venues[venue] = {"period": start, "motors": im.by_motor(ratings)}
    return {"version": 1, "through": through, "source": "video", "venues": venues}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("ingest", "rate", "validate"):
        p = sub.add_parser(name)
        p.add_argument("--store", required=True, type=Path)
        if name == "ingest":
            p.add_argument("--input", required=True, type=Path)
        else:
            p.add_argument("--through", required=True)
        if name == "rate":
            p.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    store = im.Store(private(args.store))
    if args.command == "ingest":
        counts = store.upsert(json.loads(args.input.read_text(encoding="utf-8-sig"))["rows"])
        print(json.dumps(counts))
        if counts["invalid"]:
            raise SystemExit(f"{counts['invalid']} invalid rows were skipped")
        return
    im.day(args.through)
    starts = fleet_starts(args.through)
    if args.command == "rate":
        result = rate(store, args.through, starts, schedules())
        output = private(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
        print("venues", len(result["venues"]), "motors", sum(len(v["motors"]) for v in result["venues"].values()))
    else:
        rows = store.rows(through=args.through)
        devs = im.race_deviations(rows)
        plain = im.carry_over(devs, starts)
        adjusted = im.carry_over(devs, starts, im.rider_baselines(devs, args.through))
        for metric in im.METRICS:
            if metric in plain:
                print(f"{metric}: switches {plain[metric][0]}  r plain {plain[metric][1]}  r rider-adjusted {adjusted[metric][1]}")
        if not plain:
            print("not enough rider switches yet")


if __name__ == "__main__":
    main()
