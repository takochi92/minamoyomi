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
    SEGMENTS, VENUES, frame_loader, make_anchor_patches, measure, profile_geometry, race_identity, usable_frames,
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


class Busy(RuntimeError):
    """Another batch holds the lock for this output directory."""


def locked(root):
    """Exclusive lock for an output directory. Raises Busy instead of leaking BlockingIOError."""
    import contextlib

    @contextlib.contextmanager
    def hold():
        try:
            with exclusive(root / ".exhibition-batch.lock"):
                yield
        except BlockingIOError as error:
            raise Busy("exhibition_batch_already_running") from error
    return hold()


def inputs_of(result):
    return tuple(result.get(k) for k in ("manifest_sha256", "profile_sha256", "review_sha256"))


def store(path, result, *, replace_reason=None):
    """Guarded write shared by `measure` and `batch`. Call while holding the directory lock.

    - same content: nothing happens ("unchanged")
    - a result that loses measured (boat, section) pairs is refused unless a reason is given
    - any other change keeps the previous file under history/ before writing
    Returns (status, prior_coverage_or_None).
    """
    prior = read(path) if path.exists() else None
    if prior == result:
        return "unchanged", None
    if prior is not None:
        loses = not measured_sections(prior) <= measured_sections(result)
        if loses and not replace_reason:
            return "prior_result_kept", prior["coverage"]
        stamp = (prior.get("review_sha256") or "unknown")[:12]
        archive = path.parent / "history" / f"{path.stem}.{stamp}.json"
        n = 1
        while archive.exists():
            n += 1
            archive = path.parent / "history" / f"{path.stem}.{stamp}.{n}.json"
        write(archive, prior)
        write(path, {**result, "replaces": {"inputs": dict(zip(("manifest_sha256", "profile_sha256", "review_sha256"), inputs_of(prior))),
                                            "archived_as": f"history/{archive.name}", "reason": replace_reason,
                                            "lost_sections": len(measured_sections(prior) - measured_sections(result))}})
        return ("replaced_with_reason" if loses else "updated"), prior["coverage"]
    write(path, result)
    return "new", None


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


def inventory(stadiums, directory, measurements=None):
    """Venue ledger. Playback, calibration and measurement are separate facts:

    playback_evidence        … a replay started for this venue (from the capture tool's stadium map)
    camera_profiles          … gate profiles exist
    profiles_with_reference  … profiles that carry landmark patches (the view can be checked automatically)
    measured_races           … stored results for the venue; six_boat_races counts races where all six
                               boats have every configured section
    """
    stadium_map = read(stadiums).get("stadiums", {})
    profiles, referenced = defaultdict(list), defaultdict(list)
    for path in sorted(Path(directory).glob("*.json")):
        profile = read(path)
        profile_geometry(profile)
        profiles[profile["venue"]].append(profile["id"])
        if profile.get("anchor_patches"):
            referenced[profile["venue"]].append(profile["id"])
    measured = defaultdict(lambda: {"races": 0, "six_boat_races": 0})
    if measurements is not None:
        for path in sorted(Path(measurements).glob("????????-??-??.json")):
            try:
                result = read(path)
                configured = [n for n in SEGMENTS if any(b["segments"][n]["status"] != "gate_not_configured" for b in result["boats"])]
                row = measured[result["venue"]]
                row["races"] += any(result["coverage"].values())
                row["six_boat_races"] += bool(configured) and all(result["coverage"][n] == 6 for n in configured)
            except (OSError, AttributeError, TypeError, KeyError, ValueError):
                continue
    venues = []
    for code in sorted(VENUES):
        registered = stadium_map.get(code, {})
        sample = {"date": registered.get("date"), "race": registered.get("race")}
        if measured[code]["six_boat_races"]:
            state = "six_boats_measured"
        elif measured[code]["races"]:
            state = "partly_measured"
        elif referenced[code]:
            state = "profile_with_reference"
        elif profiles[code]:
            state = "profile_available"
        else:
            state = "camera_profile_needed"
        venues.append({"venue": code, "name": registered.get("name"),
                       "playback_evidence": registered.get("evidence"),
                       "replay_sample": sample if all(sample.values()) else None,
                       "camera_profiles": profiles[code],
                       "profiles_with_reference": referenced[code],
                       "measured_races": measured[code]["races"],
                       "six_boat_races": measured[code]["six_boat_races"],
                       "state": state})
    return {"venue_count": len(venues),
            "playback_verified_venues": sum(v["playback_evidence"] == "pr-tool-homesv" for v in venues),
            "camera_profile_venues": sum(bool(v["camera_profiles"]) for v in venues),
            "reference_profile_venues": sum(bool(v["profiles_with_reference"]) for v in venues),
            "six_boat_measured_venues": sum(bool(v["six_boat_races"]) for v in venues),
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
    with locked(root):
        for key, job in sorted(zip(expected, jobs), key=lambda pair: pair[0]):
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
                    reason = job.get("replace_reason")
                    if reason is not None and (not isinstance(reason, str) or not reason.strip()):
                        raise ValueError("invalid_replace_reason")
                    change, before = store(path, result, replace_reason=reason)
                    if change == "prior_result_kept":
                        row.update(status="prior_result_kept", coverage=before, candidate_coverage=result["coverage"])
                    else:
                        row.update(status="reference" if any(result["coverage"].values()) else "no_usable_sections",
                                   coverage=result["coverage"], change=change)
                        if before is not None:
                            row["previous_coverage"] = before
                except FileNotFoundError:
                    row.update(status="input_pending", missing=["file"])
                except OSError:
                    row.update(status="input_unreadable")
                except (AttributeError, TypeError, KeyError, ValueError) as error:
                    detail = str(error)
                    row.update(status="invalid_input", reason=detail if detail.isidentifier() else "invalid_format")
            rows.append(row)
        summary = {"jobs": len(rows), "status_counts": dict(Counter(r["status"] for r in rows)),
                   "rating_ready": False, "races": rows}
        write(root / "summary.json", summary)
    return summary


def profile_with_patches(manifest, profile, reference):
    """Copy of a profile with reference patches of its three landmarks taken from one reviewed frame."""
    path, data, _ = manifest_at(manifest)
    config = read(profile)
    size, _, anchors = profile_geometry(config)
    frames = usable_frames(data)
    if reference not in frames:
        raise ValueError("camera_reference_missing")
    image = frame_loader(path.parent, size, frames)(reference)
    return {**config, "anchor_patches": make_anchor_patches(image, anchors)}


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
        ("profile-patches", ("manifest", "profile", "output")),
    ):
        p = sub.add_parser(command)
        for argument in arguments:
            p.add_argument("--" + argument, required=True, type=Path)
        if command == "measure":
            p.add_argument("--replace-reason", help="allow a result that loses measured sections; the old file is kept under history/")
        if command == "inventory":
            p.add_argument("--measurements", type=Path, help="directory of batch results, to report measured venues")
        if command == "profile-patches":
            p.add_argument("--reference", required=True, help="file name of a reviewed frame in the capture")
    args = parser.parse_args()
    try:
        if args.command == "measure":
            result = measure_files(args.manifest, args.profile, args.review)
            output = private(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            with locked(output.parent):
                change, _ = store(output, result, replace_reason=args.replace_reason)
            print(json.dumps({"change": change, "coverage": result["coverage"]}))
            if change == "prior_result_kept":
                raise SystemExit("existing result has sections this one lacks; pass --replace-reason to replace it")
        elif args.command == "template":
            write(args.output, template(args.manifest, args.profile))
        elif args.command == "profile-patches":
            write(args.output, profile_with_patches(args.manifest, args.profile, args.reference))
        elif args.command == "inventory":
            result = inventory(args.stadiums, args.profiles, args.measurements)
            write(args.output, result)
            print(f"{result['playback_verified_venues']}/24 replay routes; "
                  f"{result['camera_profile_venues']}/24 venues with a camera profile; "
                  f"{result['reference_profile_venues']}/24 with landmark reference; "
                  f"{result['six_boat_measured_venues']}/24 with a six-boat measurement")
        else:
            print(json.dumps(run_batch(args.index, args.output)["status_counts"]))
    except Busy:
        raise SystemExit("another exhibition batch is running for this output directory; nothing was changed")


if __name__ == "__main__":
    main()
