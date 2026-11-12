"""Measure reviewed exhibition segments. Inputs and outputs stay in private storage."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import os
from pathlib import Path
import tempfile

from scraper.exhibition_segments import (
    SEGMENTS, VENUES, measure, profile_geometry, race_identity, usable_frames,
)
from scraper.turn_measurement import digest
from tools.exhibition_pipeline import exclusive


ROOT = Path(__file__).resolve().parents[1]


def private(path):
    path = Path(path).resolve()
    if path.is_relative_to(ROOT / "site"):
        raise ValueError("keep_exhibition_research_outside_public_site")
    return path


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write(path, value):
    path = private(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as f:
        f.write(content)
        staged = Path(f.name)
    try:
        os.replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)


def manifest_at(path):
    path = private(path)
    raw = path.read_bytes()
    return path, json.loads(raw.decode("utf-8-sig")), hashlib.sha256(raw).hexdigest()


def measure_files(manifest, profile, review):
    path, data, sha = manifest_at(manifest)
    return measure(data, read(profile), read(review), path.parent, manifest_sha256=sha)


def template(manifest, profile):
    _, data, sha = manifest_at(manifest)
    config = read(profile)
    day, venue, race = race_identity(data)
    profile_geometry(config)
    if config["venue"] != venue:
        raise ValueError("profile_venue_mismatch")
    frames = usable_frames(data)
    return {
        "schema": 1, "manifest_sha256": sha, "profile_sha256": digest(config),
        "race": {"date": day, "venue": venue, "race": race},
        "window": [], "camera_reference": None, "camera_layout_reviewed": False,
        "boats": {str(i): [] for i in range(1, 7)},
        "available_frames": [{"file": k, "mediaTime": v["time"]} for k, v in
                             sorted(frames.items(), key=lambda p: p[1]["time"])],
    }


def inventory(stadiums, directory):
    stadium_map = read(stadiums).get("stadiums", {})
    profiles = defaultdict(list)
    for path in sorted(Path(directory).glob("*.json")):
        profile = read(path)
        profile_geometry(profile)
        profiles[profile["venue"]].append(profile["id"])
    venues = []
    for code in sorted(VENUES):
        registered = stadium_map.get(code, {})
        sample = {"date": registered.get("date"), "race": registered.get("race")}
        venues.append({"venue": code, "name": registered.get("name"),
                       "playback_evidence": registered.get("evidence"),
                       "replay_sample": sample if all(sample.values()) else None,
                       "camera_profiles": profiles[code],
                       "state": "profile_available" if profiles[code] else "camera_profile_needed"})
    return {"venue_count": len(venues),
            "playback_verified_venues": sum(v["playback_evidence"] == "pr-tool-homesv" for v in venues),
            "camera_profile_venues": sum(bool(v["camera_profiles"]) for v in venues),
            "venues": venues}


def run_batch(index, output):
    """One pass over an explicit queue. Repeat safely after a missing input is supplied."""
    index = Path(index).resolve()
    root = private(output)
    root.mkdir(parents=True, exist_ok=True)
    jobs = read(index)["jobs"]
    expected = [race_identity({"date": job["date"], "venue": {"jo": job["venue"]}, "race": job["race"]})
                for job in jobs]
    if len(expected) != len(set(expected)):
        raise ValueError("duplicate_race_in_batch")
    rows = []
    with exclusive(root / ".exhibition-batch.lock"):
        for key, job in sorted(zip(expected, jobs)):
            day, venue, race = key
            row = {"date": day, "venue": venue, "race": race}
            path = root / f"{day}-{venue}-{race:02}.json"
            if not all(job.get(k) for k in ("manifest", "profile", "review")):
                row.update(status="input_pending", missing=[k for k in ("manifest", "profile", "review") if not job.get(k)])
            else:
                try:
                    result = measure_files(*(index.parent / job[k] for k in ("manifest", "profile", "review")))
                    if key != (result["date"], result["venue"], result["race"]):
                        raise ValueError("queue_and_manifest_race_mismatch")
                    prior = read(path) if path.exists() else None
                    if prior and not measured_sections(prior) <= measured_sections(result):
                        row.update(status="prior_result_kept", coverage=prior["coverage"],
                                   candidate_coverage=result["coverage"])
                    else:
                        if prior != result:
                            write(path, result)
                        row.update(status="reference" if any(result["coverage"].values()) else "no_usable_sections",
                                   coverage=result["coverage"])
                except FileNotFoundError:
                    row.update(status="input_pending", missing=["file"])
                except (AttributeError, TypeError, KeyError, ValueError) as error:
                    detail = str(error)
                    row.update(status="invalid_input", reason=detail if detail.isidentifier() else "invalid_format")
            rows.append(row)
        summary = {"jobs": len(rows), "status_counts": dict(Counter(r["status"] for r in rows)),
                   "rating_ready": False, "races": rows}
        write(root / "summary.json", summary)
    return summary


def measured_sections(result):
    return {(boat["boat"], name) for boat in result["boats"]
            for name, section in boat["segments"].items() if section["status"] == "reference"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command, arguments in (
        ("measure", ("manifest", "profile", "review", "output")),
        ("template", ("manifest", "profile", "output")),
        ("inventory", ("stadiums", "profiles", "output")),
        ("batch", ("index", "output")),
    ):
        p = sub.add_parser(command)
        for argument in arguments:
            p.add_argument("--" + argument, required=True, type=Path)
    args = parser.parse_args()
    if args.command == "measure":
        result = measure_files(args.manifest, args.profile, args.review)
        write(args.output, result)
        print(json.dumps(result["coverage"]))
    elif args.command == "template":
        write(args.output, template(args.manifest, args.profile))
    elif args.command == "inventory":
        result = inventory(args.stadiums, args.profiles)
        write(args.output, result)
        print(f"{result['playback_verified_venues']}/24 replay routes; "
              f"{result['camera_profile_venues']}/24 venues with a camera profile")
    else:
        print(json.dumps(run_batch(args.index, args.output)["status_counts"]))


if __name__ == "__main__":
    main()
