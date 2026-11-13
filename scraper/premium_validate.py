"""Check trial ratings on later races with a different rider."""
import argparse
from collections import defaultdict
from statistics import mean

from .premium_motor import build, day, load_inputs, observations


def evaluate(records, history, schedules, cutoff, end):
    if day(end) <= day(cutoff):
        raise ValueError("holdout end must be later than the cutoff")
    snapshot = build(records, history, cutoff, schedules)["venues"]
    previous_riders = defaultdict(set)
    held_out = defaultdict(list)
    for (date, venue, _), race in sorted(records.items()):
        field = snapshot.get(venue)
        if not field or not field["period"] <= date <= end:
            continue
        for metric, motor, rider, delta in observations(race):
            if date <= cutoff:
                previous_riders[venue, metric, motor].add(rider)
            elif rider not in previous_riders[venue, metric, motor]:
                score = field["motors"].get(motor, {}).get(metric)
                if score:
                    held_out[venue, metric, motor, rider].append((delta, score))

    for metric in ("exhibition", "straight"):
        groups = [(mean(v for v, _ in rows), rows[0][1])
                  for key, rows in held_out.items() if key[1] == metric]
        if not groups:
            continue
        by_grade = defaultdict(list)
        for value, score in groups:
            by_grade[score["grade"]].append(value)
        print(metric, len(groups),
              "baseline", round(mean(abs(v) for v, _ in groups), 5),
              "unadjusted", round(mean(abs(v - s["delta"]) for v, s in groups), 5),
              "25% trial", round(mean(abs(v - .25 * s["delta"]) for v, s in groups), 5),
              "grades", {g: (len(v), round(mean(v), 4)) for g, v in sorted(by_grade.items())})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", nargs=2, action="append", required=True, metavar=("CUTOFF", "END"))
    args = parser.parse_args()
    inputs = load_inputs()
    for cutoff, end in args.window:
        print(cutoff, "→", end)
        evaluate(*inputs, cutoff, end)


if __name__ == "__main__":
    main()
