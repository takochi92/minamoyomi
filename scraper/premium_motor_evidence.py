"""Build and validate official-only, three-meeting motor evidence."""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path
from statistics import mean, median

from .premium_motor import MIN_FIELD, ROOT, build, day, load_inputs, observations, profile, write_private

METRICS = ("exhibition", "straight", "turn", "acceleration", "overall")
MIN_RIDER_MEETINGS = 3


def prepare(records):
    series = defaultdict(list)
    for (date, venue, _), race in sorted(records.items()):
        title = (race.get("racelist") or {}).get("title", "").strip()
        if title and (race.get("result") or {}).get("finished"):
            series[venue].append((date, title, tuple(observations(race, venue))))
    return series


def meetings(rows, cutoff, boundary, schedule):
    result = []
    for date, title, values in rows:
        if date < boundary:
            continue
        if date > cutoff:
            break
        official_start = next((s for s, e in schedule.get(title, {}).items() if s <= date <= e), None)
        if not result or result[-1][0] != title or (
            official_start and result[-1][1] != official_start
        ) or (day(date) - day(result[-1][2][-1][0])).days > 3:
            result.append((title, official_start or date, []))
        result[-1][2].append((date, values))
    return result


def rider_reference(series, schedules, cutoff):
    """Build venue-scaled rider references using only already completed meetings."""
    prior = defaultdict(lambda: defaultdict(list))
    scales = {}
    for venue, rows in series.items():
        schedule = schedules.get(venue, {})
        magnitudes = defaultdict(list)
        events = meetings(rows, cutoff, "", schedule)
        for index, (title, start, entries) in enumerate(events):
            official_end = schedule.get(title, {}).get(start)
            # Older schedules are sparse. A later meeting already observed at this
            # venue also establishes that the preceding meeting ended.
            if official_end is None and index == len(events) - 1:
                continue
            if official_end is not None and official_end > cutoff:
                continue
            for _, values in entries:
                for metric, motor, rider, delta in values:
                    if metric in METRICS:
                        magnitudes[metric].append(abs(delta))
                        prior[metric, rider][venue, start, motor].append(delta)
        for metric, values in magnitudes.items():
            scale = mean(values)
            if scale > 0:
                scales[venue, metric] = scale
    return prior, scales


def rider_correction(reference, venue, metric, motor, rider):
    prior, scales = reference
    scale = scales.get((venue, metric))
    if not scale:
        return None
    other_meetings = defaultdict(list)
    for (old_venue, start, old_motor), values in prior.get((metric, rider), {}).items():
        if (old_venue, old_motor) != (venue, motor) and len(values) >= 2:
            other_meetings[old_venue, start].extend(values)
    baseline = [mean(values) / scales[old_venue, metric]
                for (old_venue, _), values in other_meetings.items()]
    if len(baseline) < MIN_RIDER_MEETINGS:
        return None
    return scale * sum(baseline) / (len(baseline) + 4)


def estimate(series, history, schedules, cutoff):
    """Return unadjusted and rider-adjusted estimates using data through the cutoff."""
    as_of = day(cutoff)
    references = {}
    output = {}
    for venue, rows in series.items():
        boundaries = {v["history_boundary"] for v in history.get(venue, {}).values()
                      if v.get("history_boundary") and v.get("history_boundary_source")
                      in ("official_confirmed", "zero_rate_inferred")}
        if len(boundaries) != 1:
            continue
        boundary = next(iter(boundaries))
        fleet = history[venue]
        boundary_source = ("official_confirmed" if any(
            row.get("history_boundary") == boundary and row.get("history_boundary_source") == "official_confirmed"
            for row in fleet.values()
        ) else "zero_rate_inferred")
        schedule = schedules.get(venue, {})
        events = meetings(rows, cutoff, boundary, schedule)
        samples = defaultdict(list)
        for _, start, entries in events[-3:]:
            before = (day(start) - timedelta(days=1)).strftime("%Y%m%d")
            if before not in references:
                references[before] = rider_reference(series, schedules, before)
            reference = references[before]
            for date, values in entries:
                for metric, motor, rider, delta in values:
                    if metric not in METRICS or motor not in fleet:
                        continue
                    correction = rider_correction(reference, venue, metric, motor, rider)
                    samples[metric, motor].append(
                        (day(date), start, rider, delta, correction or 0, correction is not None)
                    )
        output[venue] = {}
        for (metric, motor), values in sorted(samples.items()):
            if len({r for _, _, r, *_ in values}) < 2 or len({m for _, m, *_ in values}) < 2:
                continue
            raw = profile([v[:4] for v in values], as_of)
            if raw is None:
                continue
            adjusted = profile([(d, m, r, v - c) for d, m, r, v, c, _ in values], as_of)
            output[venue].setdefault(metric, {})[motor] = {
                "raw": raw, "adjusted": adjusted, "riders": sorted({v[2] for v in values}),
                "corrected_runs": sum(v[5] for v in values),
                "motor_generation_start": boundary,
                "motor_generation_source": boundary_source,
                "meeting_starts": sorted({v[1] for v in values}),
            }
    return output


def backfill(estimates, cutoff):
    """Summarize historical observations against the sampled venue fleet."""
    venues = {}
    for venue, metrics in estimates.items():
        for metric, motors in metrics.items():
            if len(motors) < MIN_FIELD:
                continue
            center = median(v["raw"][0]["delta"] for v in motors.values())
            for motor, evidence in motors.items():
                score = evidence["raw"][0]
                venues.setdefault(venue, {}).setdefault(motor, {})[metric] = {
                    **score, "field": len(motors), "venue_delta": round(score["delta"] - center, 4),
                    "riders": len(evidence["riders"]), "basis": "official_recent_meetings",
                    "motor_generation_start": evidence["motor_generation_start"],
                    "motor_generation_source": evidence["motor_generation_source"],
                    "meeting_starts": evidence["meeting_starts"],
                }
    return {"through": cutoff, "venues": venues}


def gap_counts(archive, history, schedules, data, race_day):
    """Count places where historical observations could supplement current form."""
    cutoff = data["through"]
    current = build(archive, history, cutoff, schedules)["venues"]
    races = ROOT / "site" / "data" / "races" / race_day
    if not 0 < (day(race_day) - day(cutoff)).days <= 3:
        raise ValueError("race day must follow the cutoff by at most three days")
    totals = {metric: Counter() for metric in ("turn", "acceleration", "overall")}
    for path in sorted(races.glob("????.json")):
        race = json.loads(path.read_text(encoding="utf-8"))
        venue = race["jcd"]
        card = race.get("racelist") or {}
        boats = card.get("boats") or []
        eligible = len(boats) == 6 and sum(b.get("motor_2") == 0 for b in boats) < 5
        for entry in boats:
            motor, rider = str(entry.get("motor_no")), str(entry.get("toban"))
            pairing = current.get(venue, {}).get("pairings", {}).get(motor, {}).get(rider, {})
            historical = data["venues"].get(venue, {}).get(motor, {})
            for metric, counts in totals.items():
                score = pairing.get(metric, {})
                if (eligible and score.get("title") == card.get("title", "").strip()
                        and score.get("through") and (day(race_day) - day(score["through"])).days <= 3):
                    counts["current_meeting"] += 1
                elif eligible and metric in historical:
                    counts["historical_evidence"] += 1
                else:
                    counts["missing"] += 1
    if not any(totals.values()):
        raise ValueError("race day has no local racecards")
    return totals


def replay(series, history, schedules, cutoff, end):
    estimates = estimate(series, history, schedules, cutoff)
    reference = rider_reference(series, schedules, cutoff)
    later = defaultdict(list)
    for venue, rows in series.items():
        for date, _, values in rows:
            if not cutoff < date <= end:
                continue
            for metric, motor, rider, delta in values:
                motor_est = estimates.get(venue, {}).get(metric, {}).get(motor)
                if motor_est and rider not in motor_est["riders"]:
                    later[metric, venue, motor, rider].append((delta, motor_est))
    results = defaultdict(list)
    with_rider = defaultdict(list)
    for (metric, venue, motor, rider), rows in later.items():
        actual = mean(v for v, _ in rows)
        estimate_row = rows[0][1]
        raw, adjusted = (estimate_row[k][0]["delta"] for k in ("raw", "adjusted"))
        errors = (abs(actual), abs(actual - .25 * raw), abs(actual - .25 * adjusted))
        results[metric].append(errors)
        correction = rider_correction(reference, venue, metric, motor, rider)
        if estimate_row["corrected_runs"] and correction is not None:
            with_rider[metric].append((
                abs(actual - correction), abs(actual - correction - .25 * raw),
                abs(actual - correction - .25 * adjusted),
            ))
    summary = defaultdict(dict)
    for metric, errors in sorted(results.items()):
        summary[metric]["all"] = {
            "pairs": len(errors),
            **dict(zip(("venue_mean_mae", "motor_mae", "adjusted_mae"),
                       (round(mean(e), 6) for e in zip(*errors)))),
        }
    for metric, errors in with_rider.items():
        summary[metric]["with_rider"] = {
            "pairs": len(errors),
            **dict(zip(("rider_mae", "rider_and_raw_motor_mae", "rider_and_adjusted_motor_mae"),
                       (round(mean(e), 6) for e in zip(*errors)))),
        }
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--through", required=True)
    parser.add_argument("--holdout", nargs=2, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--race-day", help="Compare gaps on local racecards for YYYYMMDD")
    parser.add_argument("--timestamped-only", action="store_true",
                        help="Exclude official rows without a verified pre-deadline capture time")
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / "private"):
        parser.error("write this candidate under private/")
    archive, history, schedules = load_inputs()
    if args.timestamped_only:
        archive = {key: value for key, value in archive.items()
                   if value.get("provenance") == "timestamped_pre_deadline"}
    if not any(d == args.through for d, _, _ in archive):
        parser.error("cutoff has no official results")
    series = prepare(archive)
    data = backfill(estimate(series, history, schedules, args.through), args.through)
    data["source_rows"] = dict(sorted(Counter(
        value.get("provenance", "unknown")
        for (date, _, _), value in archive.items() if date <= args.through
    ).items()))
    counts = Counter()
    for motors in data["venues"].values():
        counts.update({k for scores in motors.values() for k in scores})
    print("venues", len(data["venues"]), "motors", sum(map(len, data["venues"].values())),
          "coverage", dict(sorted(counts.items())))
    if args.race_day:
        try:
            gaps = gap_counts(archive, history, schedules, data, args.race_day)
        except ValueError as exc:
            parser.error(str(exc))
        data["racecard_gaps"] = {"date": args.race_day, "metrics": gaps}
        print("racecard_gaps", args.race_day, json.dumps(gaps, sort_keys=True))
    data["holdouts"] = []
    for cutoff, end in args.holdout:
        if day(end) <= day(cutoff) or end > args.through:
            parser.error("holdout must be later than its cutoff and within the archived period")
        result = replay(series, history, schedules, cutoff, end)
        data["holdouts"].append({"cutoff": cutoff, "end": end, "metrics": result})
        print(cutoff, end, json.dumps(result, sort_keys=True))
    write_private(output, json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False))


if __name__ == "__main__":
    main()
