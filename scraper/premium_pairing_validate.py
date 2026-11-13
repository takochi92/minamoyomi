"""Replay the premium pairing grades against the next day's official timings."""
import argparse
from collections import defaultdict
from datetime import timedelta
from random import Random
from statistics import mean

from .premium_motor import build, day, load_inputs, observations


def replay(records, history, schedules, start, end):
    seen = set()
    result = defaultdict(list)
    by_date = defaultdict(list)
    for (d, venue, _), race in records.items():
        by_date[d].append((venue, race))
    for date in sorted(d for d in by_date if start <= d <= end):
        cutoff = (day(date) - timedelta(days=1)).strftime("%Y%m%d")
        fields = build(records, history, cutoff, schedules, include_unqualified=True)["venues"]
        observations_by_pair = defaultdict(list)
        for venue, race in by_date[date]:
            if venue not in fields:
                continue
            title = (race.get("racelist") or {}).get("title", "").strip()
            for metric, motor, rider, value in observations(race, venue):
                score = fields[venue]["pairings"].get(motor, {}).get(rider, {}).get(metric)
                if not score or score["title"] != title or (day(date) - day(score["through"])).days > 3:
                    continue
                key = (metric, venue, score["start"], title, motor, rider)
                if key not in seen:
                    observations_by_pair[key].append((value, score))
        for key, rows in observations_by_pair.items():
            seen.add(key)
            metric, venue, meeting, title, _, _ = key
            score = rows[0][1]
            result[metric, venue].append(((venue, meeting, title), score["grade"], mean(v for v, _ in rows), score["delta"]))
    return result


def summary(rows):
    if not rows:
        return None
    by_meeting = defaultdict(list)
    for row in rows:
        by_meeting[row[0]].append(row)
    counts = {grade: sum(r[1] == grade for r in rows) for grade in "ABCD"}
    means = {grade: mean(r[2] for r in rows if r[1] == grade) for grade in counts if counts[grade]}
    clusters = list(by_meeting.values())
    meeting_gaps = []
    for meeting in clusters:
        fastest = [r[2] for r in meeting if r[1] == "A"]
        slowest = [r[2] for r in meeting if r[1] == "D"]
        if fastest and slowest:
            meeting_gaps.append(mean(slowest) - mean(fastest))
    gains = []
    gaps = []
    if len(clusters) >= 5:
        rng = Random(71)
        for _ in range(1000):
            sample = [row for cluster in rng.choices(clusters, k=len(clusters)) for row in cluster]
            a = [r[2] for r in sample if r[1] == "A"]
            d = [r[2] for r in sample if r[1] == "D"]
            if a and d:
                gaps.append(mean(d) - mean(a))
            gains.append(mean(abs(y) - abs(y - .5 * pred) for _, _, y, pred in sample))
    def interval(values):
        if not values:
            return None
        values.sort()
        return [round(values[int((len(values)-1)*p)], 4) for p in (.025, .975)]
    return {"pairs": len(rows), "meetings": len(clusters),
            "ordered": len(means) == 4 and all(means[a] < means[b] for a, b in zip("ABC", "BCD")),
            "meetings_a_faster": [sum(g > 0 for g in meeting_gaps), len(meeting_gaps)],
            "counts": counts, "means": {g: round(v, 4) for g, v in means.items()},
            "gap": round(means["D"] - means["A"], 4) if "A" in means and "D" in means else None,
            "gap_ci": interval(gaps), "gain_ci": interval(gains),
            "baseline_mae": round(mean(abs(y) for _, _, y, _ in rows), 4),
            "adjusted_mae": round(mean(abs(y - .5 * pred) for _, _, y, pred in rows), 4)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--by-venue", action="store_true")
    args = parser.parse_args()
    data = replay(*load_inputs(), args.start, args.end)
    for metric in ("turn", "acceleration"):
        for (kind, venue), rows in sorted(data.items()):
            if metric == kind and (args.by_venue or kind == "acceleration"):
                print(metric, venue, summary(rows))
        print(metric, "all", summary([r for (kind, _), rows in data.items() if kind == metric for r in rows]))


if __name__ == "__main__":
    main()
