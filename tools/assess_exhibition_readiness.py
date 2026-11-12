"""Check measurement coverage and repeatability before developing motor grades."""
from __future__ import annotations

import argparse
from collections import defaultdict
from itertools import combinations
import json
from pathlib import Path
from statistics import median

from scraper.exhibition_segments import SHA256, finite, race_identity
from tools.measure_exhibition import output_lock, private, read, write


CANDIDATES = {"turning": "turn_total", "acceleration": "exit_recovery", "straight": "back_stretch"}
BOATS = set(range(1, 7))


def section_values(result, name):
    values = {}
    seen = set()
    for row in result["boats"]:
        boat = row["boat"]
        if type(boat) is not int or boat not in BOATS or boat in seen:
            raise ValueError("invalid_result_boat_numbers")
        seen.add(boat)
        section = row["segments"].get(name, {})
        if section.get("status") != "reference":
            continue
        value = section.get("video_seconds")
        bounds = section.get("bracket_range_video_seconds")
        if (not finite(value) or not isinstance(bounds, list) or len(bounds) != 2
                or not all(finite(bound) for bound in bounds) or not 0 < bounds[0] <= value <= bounds[1]):
            raise ValueError("invalid_result_interval")
        values[boat] = value
    return values


def compare_pair(first, second):
    if set(first) != BOATS or set(second) != BOATS:
        return {"status": "fewer_than_six_common_boats"}
    centres = sorted((first[boat] + second[boat]) / 2 for boat in BOATS)
    separation = median([b - a for a, b in zip(centres, centres[1:])])
    disagreement = max(abs(first[boat] - second[boat]) for boat in BOATS)
    return {"status": "passed" if separation > 0 and disagreement <= separation / 3 + 1e-9 else "disagreement_too_large",
            "median_adjacent_gap_seconds": round(separation, 6),
            "largest_reader_difference_seconds": round(disagreement, 6)}


def prepare_results(entries):
    groups = defaultdict(list)
    for reader, result in entries:
        day, venue, race = race_identity({"date": result["date"], "venue": {"jo": result["venue"]},
                                         "race": result["race"]})
        if not isinstance(reader, str) or not reader.strip():
            raise ValueError("reviewer_id_required")
        reader = reader.strip().casefold()
        if result.get("quality_checks") != "pinned_camera_and_continuous_track_v2":
            continue
        lap = result.get("lap")
        hashes = tuple(result.get(key) for key in ("manifest_sha256", "profile_sha256", "review_sha256"))
        if type(lap) is not int or lap not in (1, 2) or not all(isinstance(v, str) and SHA256.fullmatch(v) for v in hashes):
            raise ValueError("result_provenance_required")
        groups[(day, venue, race, lap, *hashes[:2])].append((reader, hashes[2], result))
    return groups


def assess(entries, *, min_races=3, min_dates=2):
    """Screen candidate metrics. A passing screen still emits no motor grades."""
    if type(min_races) is not int or type(min_dates) is not int or min_races < 1 or min_dates < 1:
        raise ValueError("positive_pilot_sample_limits_required")
    entries = list(entries)
    groups = prepare_results(entries)
    report = {}
    for label, name in CANDIDATES.items():
        races = defaultdict(lambda: {"max_boats": 0, "paired_checks": []})
        for key, records in groups.items():
            row = races[key[:3]]
            values = [(reader, digest, section_values(result, name)) for reader, digest, result in records]
            row["max_boats"] = max(row["max_boats"], *(len(v) for _, _, v in values))
            for (a_reader, a_hash, a), (b_reader, b_hash, b) in combinations(values, 2):
                if a_reader == b_reader or a_hash == b_hash:
                    continue
                row["paired_checks"].append(compare_pair(a, b))
        passed = [key for key, row in races.items()
                  if row["paired_checks"] and all(c["status"] == "passed" for c in row["paired_checks"])]
        by_venue = defaultdict(list)
        for day, venue, _ in passed:
            by_venue[venue].append(day)
        ready_venues = sorted(venue for venue, days in by_venue.items()
                              if len(days) >= min_races and len(set(days)) >= min_dates)
        report[label] = {
            "segment": name,
            "six_boat_races": sum(r["max_boats"] == 6 for r in races.values()),
            "paired_passing_races": len(passed),
            "paired_passing_dates": len({day for day, _, _ in passed}),
            "repeatability_screen_passed": bool(ready_venues),
            "venues_passing_repeatability_screen": ready_venues,
            "races": [{"date": day, "venue": venue, "race": race, **row}
                      for (day, venue, race), row in sorted(races.items())],
        }
    return {"schema": 1, "input_results": len(entries), "comparable_capture_groups": len(groups),
            "pilot_minimums": {"races": min_races, "dates": min_dates, "boats_per_race": 6,
                               "max_reader_difference_fraction_of_median_adjacent_gap": 1 / 3},
            "metrics": report, "rating_ready": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    index = private(args.index)
    records = read(index)["results"]
    report = assess((row["reviewer"], read(private(index.parent / row["path"]))) for row in records)
    output = private(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output_lock(output.parent) as acquired:
        if not acquired:
            print('{"status":"already_running"}')
            return
        if output.exists():
            parser.error("requires a new output file")
        write(output, report)
    print(json.dumps({metric: item["repeatability_screen_passed"] for metric, item in report["metrics"].items()}))


if __name__ == "__main__":
    main()
