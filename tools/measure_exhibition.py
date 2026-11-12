"""Measure reviewed exhibition segments. Inputs and outputs stay in private storage."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import ExitStack, contextmanager
import errno
import hashlib
import json
import os
from pathlib import Path
import tempfile

from scraper.exhibition_segments import (
    SEGMENTS, VENUES, calibration_image, camera_check, frame_loader, measure, profile_geometry,
    race_identity, usable_frames,
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


def measure_files(manifest, profile, review, calibration=None):
    path, data, sha = manifest_at(manifest)
    return measure(data, read(profile), read(review), path.parent, manifest_sha256=sha,
                   calibration=private(calibration) if calibration is not None else None)


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
        "lap_evidence": {},
        "boats": {str(i): [] for i in range(1, 7)},
        "identity": {},
        "available_frames": [{"file": k, "mediaTime": v["time"]} for k, v in
                             sorted(frames.items(), key=lambda p: p[1]["time"])],
    }


def scan_camera(manifest, profile, calibration):
    path, data, sha = manifest_at(manifest)
    config = read(profile)
    day, venue, race = race_identity(data)
    size, _, anchors = profile_geometry(config)
    if config["venue"] != venue:
        raise ValueError("profile_venue_mismatch")
    frames = usable_frames(data)
    load = frame_loader(path.parent, size, frames, coordinate_space=config.get("coordinate_space", "screenshot"))
    check = camera_check(load, calibration_image(config, size, private(calibration)), anchors)
    rows = []
    for name, frame in sorted(frames.items(), key=lambda entry: entry[1]["time"]):
        try:
            status = "match" if check(name) else "landmarks_changed"
        except ValueError as error:
            status = str(error)
        rows.append({"file": name, "media_time": frame["time"], "status": status})
    return {"date": day, "venue": venue, "race": race, "profile_id": config["id"],
            "manifest_sha256": sha, "profile_sha256": digest(config),
            "status_counts": dict(Counter(row["status"] for row in rows)), "frames": rows}


def inventory(stadiums, directory, results=()):
    stadium_map = read(stadiums).get("stadiums", {})
    profiles = defaultdict(list)
    for path in sorted(Path(directory).glob("*.json")):
        profile = read(path)
        profile_geometry(profile)
        profiles[profile["venue"]].append(profile["id"])
    measured = defaultdict(list)
    for path in results:
        data = read(path)
        result = data.get("result", data)
        code = result["venue"]
        if code not in VENUES or result["profile_id"] not in profiles[code]:
            raise ValueError("result_profile_not_in_inventory")
        measured[code].append({"date": result["date"], "race": result["race"],
                               "pinned_calibration_matched": result.get("quality_checks") ==
                               "pinned_camera_and_continuous_track_v2",
                               "all_six_required_sections": all(result["coverage"].get(name) == 6
                                                               for name in ("turn_entry", "turn_exit", "back_stretch"))})
    venues = []
    for code in sorted(VENUES):
        registered = stadium_map.get(code, {})
        sample = {"date": registered.get("date"), "race": registered.get("race")}
        venues.append({"venue": code, "name": registered.get("name"),
                       "playback_evidence": registered.get("evidence"),
                       "replay_sample": sample if all(sample.values()) else None,
                       "camera_profiles": profiles[code],
                       "measurement_samples": measured[code],
                       "state": "profile_available" if profiles[code] else "camera_profile_needed"})
    return {"venue_count": len(venues),
            "playback_verified_venues": sum(v["playback_evidence"] == "pr-tool-homesv" for v in venues),
            "camera_profile_venues": sum(bool(v["camera_profiles"]) for v in venues),
            "venues": venues}


@contextmanager
def output_lock(root):
    path = root / ".exhibition-batch.lock"
    with ExitStack() as stack:
        try:
            stack.enter_context(exclusive(path))
        except OSError as error:
            if error.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK) or not path.is_file():
                raise
            yield False
            return
        yield True


def revision(result):
    return digest({key: value for key, value in result.items() if key != "revision"})


def store_result(path, result, reason=None, replacement_version=None):
    """Save immutable candidates and change the selected result only with a reason."""
    if reason is not None and (not isinstance(reason, str) or not reason.strip() or len(reason) > 500):
        raise ValueError("invalid_replacement_reason")
    prior = read(path) if path.exists() else None
    if path.exists() and not isinstance(prior, dict):
        raise ValueError("invalid_existing_result")
    keys = ("date", "venue", "race", "lap")
    if prior is not None and tuple(prior[key] for key in keys) != tuple(result[key] for key in keys):
        raise ValueError("output_belongs_to_different_race")
    versions = path.parent / ".exhibition-versions" / path.name
    new = revision(result)
    if (reason is None) != (replacement_version is None) or (reason is not None and replacement_version != new):
        raise ValueError("replacement_must_name_exact_candidate_version")
    old = revision(prior) if prior is not None else None

    def archive(value, version):
        target = versions / f"{version}.json"
        body = {k: v for k, v in value.items() if k != "revision"}
        if target.exists():
            if read(target) != body:
                raise ValueError("archive_integrity_mismatch")
        else:
            write(target, body)

    archive(result, new)
    status = "reference" if any(result["coverage"].values()) else "no_usable_sections"
    saved = {"status": status, "version": new, "coverage": result["coverage"]}
    if old == new:
        return saved
    if prior is not None:
        archive(prior, old)
        before, after = measured_sections(prior), measured_sections(result)
        changed = sorted(key for key in before.keys() & after.keys() if before[key] != after[key])
        difference = {"added": sorted(after.keys() - before.keys()),
                      "removed": sorted(before.keys() - after.keys()), "changed": changed}
        if reason is None:
            return {"status": "candidate_saved", "version": old, "candidate_version": new,
                    "coverage": prior["coverage"], "candidate_coverage": result["coverage"],
                    "section_difference": difference}
        event = {"version": new, "previous_version": old, "replacement_reason": reason.strip(),
                 "section_difference": difference}
        history = (prior.get("revision") or {}).get("history", [])
        result = {**result, "revision": {"history": [*history, event]}}
        saved.update(previous_version=old, section_difference=difference)
    write(path, result)
    return saved


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
    with output_lock(root) as acquired:
        if not acquired:
            return {"status_counts": {"already_running": 1}}
        for key, job in sorted(zip(expected, jobs)):
            day, venue, race = key
            row = {"date": day, "venue": venue, "race": race}
            path = root / f"{day}-{venue}-{race:02}.json"
            inputs = ("manifest", "profile", "review", "calibration")
            if not all(job.get(k) for k in inputs):
                row.update(status="input_pending", missing=[k for k in inputs if not job.get(k)])
            else:
                stage = "input"
                try:
                    result = measure_files(*(index.parent / job[k] for k in inputs))
                    if key != (result["date"], result["venue"], result["race"]):
                        raise ValueError("queue_and_manifest_race_mismatch")
                    stage = "result"
                    row.update(store_result(path, result, job.get("replacement_reason"), job.get("replacement_version")))
                except FileNotFoundError:
                    if stage == "input":
                        row.update(status="input_pending", missing=["file"])
                    else:
                        row.update(status="result_io_error")
                except OSError:
                    row.update(status=f"{stage}_io_error")
                except (AttributeError, TypeError, KeyError, ValueError) as error:
                    detail = str(error)
                    row.update(status="invalid_input", reason=detail if detail.isidentifier() else "invalid_format")
            rows.append(row)
        summary = {"jobs": len(rows), "status_counts": dict(Counter(r["status"] for r in rows)),
                   "rating_ready": False, "races": rows}
        write(root / "summary.json", summary)
    return summary


def measured_sections(result):
    return {(boat["boat"], name): section for boat in result["boats"]
            for name, section in boat["segments"].items() if section["status"] == "reference"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command, arguments in (
        ("measure", ("manifest", "profile", "review", "calibration", "output")),
        ("template", ("manifest", "profile", "output")),
        ("scan-camera", ("manifest", "profile", "calibration", "output")),
        ("inventory", ("stadiums", "profiles", "output")),
        ("batch", ("index", "output")),
    ):
        p = sub.add_parser(command)
        for argument in arguments:
            p.add_argument("--" + argument, required=True, type=Path)
        if command == "measure":
            p.add_argument("--replacement-reason")
            p.add_argument("--replacement-version")
        if command == "inventory":
            p.add_argument("--result", type=Path, action="append", default=[])
    args = parser.parse_args()
    if args.command == "measure":
        output = private(args.output)
        if output.name.lower() == "summary.json" or output.suffix.lower() != ".json" or ".exhibition-versions" in output.parts:
            parser.error("output must be a result JSON outside the version archive")
        output.parent.mkdir(parents=True, exist_ok=True)
        with output_lock(output.parent) as acquired:
            if not acquired:
                print('{"status":"already_running"}')
                return
            result = measure_files(args.manifest, args.profile, args.review, args.calibration)
            print(json.dumps(store_result(output, result, args.replacement_reason, args.replacement_version),
                             ensure_ascii=False))
    elif args.command == "template":
        write(args.output, template(args.manifest, args.profile))
    elif args.command == "scan-camera":
        output = private(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        result = scan_camera(args.manifest, args.profile, args.calibration)
        with output_lock(output.parent) as acquired:
            if not acquired:
                print('{"status":"already_running"}')
                return
            if output.exists():
                parser.error("scan-camera requires a new output file")
            write(output, result)
        print(json.dumps(result["status_counts"]))
    elif args.command == "inventory":
        result = inventory(args.stadiums, args.profiles, args.result)
        write(args.output, result)
        print(f"{result['playback_verified_venues']}/24 replay routes; "
              f"{result['camera_profile_venues']}/24 venues with a camera profile")
    else:
        print(json.dumps(run_batch(args.index, args.output)["status_counts"]))


if __name__ == "__main__":
    main()
