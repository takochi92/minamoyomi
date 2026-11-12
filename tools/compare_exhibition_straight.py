"""Compare a replay straight-section measurement with official race data."""
from __future__ import annotations

import argparse
from hashlib import sha256
from itertools import combinations
import json
from pathlib import Path
from statistics import correlation
import unicodedata
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup

from scraper.exhibition_segments import finite, race_identity
from scraper.parse import parse_beforeinfo, parse_oriten, parse_racelist
from tools.measure_exhibition import private, write


BOATS = set(range(1, 7))


def normal_name(value):
    return "".join(unicodedata.normalize("NFKC", value).split())


def validate_page_identity(html, page, expected):
    date, venue, race = expected
    soup = BeautifulSoup(html, "html.parser")
    links = [urlsplit(a["href"]) for a in soup.select("th:not(.is-thColor2) > a[href]")
             if a.get_text(strip=True) == f"{race}R"]
    query = {"hd": [date], "jcd": [venue], "rno": [str(race)]}
    if not any(link.path == f"/owpc/pc/race/{page}" and parse_qs(link.query) == query for link in links):
        raise ValueError(f"official_{page}_race_mismatch")


def official_rows(original, before, racelist, expected):
    validate_page_identity(before, "beforeinfo", expected)
    validate_page_identity(racelist, "racelist", expected)
    data = parse_oriten(original)
    if not data or data["items"].count("直線") != 1:
        raise ValueError("official_straight_column_missing")
    column = data["items"].index("直線")
    riders = {row["frame"]: row for row in parse_racelist(racelist)["boats"]}
    display = {row["frame"]: row for row in parse_beforeinfo(before)["boats"]}
    lines = [line.split("\t") for line in original.splitlines()]
    listed = [line for line in lines if len(line) >= column + 3 and line[0].strip().isdigit()]
    names = {int(line[0]): normal_name(line[1]) for line in listed}
    if (set(riders) != BOATS or set(display) != BOATS or set(names) != BOATS
            or len(listed) != 6 or set(data["rows"]) != {str(n) for n in BOATS}):
        raise ValueError("six_official_boats_required")
    rows = []
    for boat in sorted(BOATS):
        rider, timing = riders[boat], display[boat]
        if names[boat] != normal_name(rider["name"]) or names[boat] != normal_name(timing["name"]):
            raise ValueError(f"official_name_mismatch_boat_{boat}")
        values = data["rows"][str(boat)]
        straight = values[column] if len(values) > column else None
        if not finite(straight) or straight <= 0:
            straight = None
        rows.append({"boat": boat, "name": rider["name"], "racer_id": rider["toban"], "motor": rider["motor_no"],
                     "official_straight_seconds": straight, "official_exhibition_seconds": timing["exhibit_time"]})
    return rows


def midranks(values):
    return [1 + sum(other < value for other in values)
            + (sum(other == value for other in values) - 1) / 2 for value in values]


def compare(result, official, expected):
    identity = race_identity({"date": result["date"], "venue": {"jo": result["venue"]}, "race": result["race"]})
    if identity != expected:
        raise ValueError("video_result_race_mismatch")
    boats = {row["boat"]: row for row in result["boats"]}
    if len(result["boats"]) != len(boats) or not set(boats) <= BOATS:
        raise ValueError("invalid_video_boat_numbers")
    rows = []
    for original in official:
        section = boats.get(original["boat"], {}).get("segments", {}).get("back_stretch", {})
        value = section.get("video_seconds") if section.get("status") == "reference" else None
        bounds = section.get("bracket_range_video_seconds") if value is not None else None
        if value is not None and (not finite(value) or not isinstance(bounds, list) or len(bounds) != 2
                                  or not all(finite(x) for x in bounds) or not 0 < bounds[0] <= value <= bounds[1]):
            raise ValueError("invalid_video_interval")
        rows.append({**original, "video_seconds": value, "video_frame_bounds": bounds,
                     "video_status": section.get("status", "not_measured")})
    metrics = {}
    for column in ("official_straight_seconds", "official_exhibition_seconds"):
        matched = [row for row in rows if row[column] is not None and row["video_seconds"] is not None]
        x = [row[column] for row in matched]
        y = [row["video_seconds"] for row in matched]
        point_rho = round(correlation(midranks(x), midranks(y)), 3) if len(set(x)) >= 2 and len(set(y)) >= 2 else None
        counts = {"confirmed_same_direction": 0, "confirmed_opposite_direction": 0,
                  "video_bounds_overlap": 0, "official_tie": 0}
        for a, b in combinations(matched, 2):
            if a[column] == b[column]:
                counts["official_tie"] += 1
                continue
            lo_a, hi_a = a["video_frame_bounds"]
            lo_b, hi_b = b["video_frame_bounds"]
            if hi_a >= lo_b and hi_b >= lo_a:
                counts["video_bounds_overlap"] += 1
            elif (hi_a < lo_b) == (a[column] < b[column]):
                counts["confirmed_same_direction"] += 1
            else:
                counts["confirmed_opposite_direction"] += 1
        metrics[column] = {"paired_boats": len(matched), "point_estimate_spearman": point_rho, **counts}
    return {"date": identity[0], "venue": identity[1], "race": identity[2], "lap": result["lap"],
            "video_time_basis": result["time_basis"], "official_and_video_same_distance_verified": False,
            "video_measurement_method": result.get("measurement_method", result.get("measurement_mode")),
            "rows": rows, "comparison": metrics, "rating_ready": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True)
    parser.add_argument("--venue", required=True)
    parser.add_argument("--race", required=True, type=int)
    for name in ("result", "original", "before", "racelist", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    identity = race_identity({"date": args.date, "venue": {"jo": args.venue}, "race": args.race})
    output = private(args.output)
    sources = {name: private(getattr(args, name)) for name in ("result", "original", "before", "racelist")}
    if output in sources.values():
        parser.error("output must differ from the inputs")
    raw = {name: path.read_bytes() for name, path in sources.items()}
    saved = json.loads(raw["result"].decode("utf-8-sig"))
    original, before, racelist = (raw[name].decode("utf-8-sig") for name in ("original", "before", "racelist"))
    official = official_rows(original, before, racelist, identity)
    result = compare(saved.get("manual_result", saved), official, identity)
    result["official_sources"] = {
        "straight": f"https://race.boatcast.jp/txt/{args.venue}/bc_oriten_{args.date}_{args.venue}_{args.race:02}.txt",
        "exhibition": f"https://www.boatrace.jp/owpc/pc/race/beforeinfo?rno={args.race}&jcd={args.venue}&hd={args.date}",
        "entrants": f"https://www.boatrace.jp/owpc/pc/race/racelist?rno={args.race}&jcd={args.venue}&hd={args.date}",
    }
    result["input_sha256"] = {name: sha256(body).hexdigest() for name, body in raw.items()}
    write(output, result)
    print(json.dumps(result["comparison"], ensure_ascii=False))


if __name__ == "__main__":
    main()
