"""Measure first-mark sections from manually confirmed before/after replay frames."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scraper.exhibition_segments import (
    MAX_GAP_SECONDS, calibration_image, camera_check, frame_loader, profile_geometry, race_identity, usable_frames,
)
from scraper.turn_measurement import digest
from tools.measure_exhibition import manifest_at, private, read, write


SECTIONS = {"entry": ("A", "B"), "rotation": ("B", "C"), "exit": ("C", "D"), "turn_total": ("A", "D")}


def measure_brackets(manifest, profile, calibration, notes):
    path, raw, sha = manifest_at(manifest)
    day, venue, race = race_identity(raw)
    size, gates, anchors = profile_geometry(profile)
    if profile["venue"] != venue or profile["lap"] != 1 or set(gates) != set("ABCD"):
        raise ValueError("first_mark_profile_mismatch")
    if (notes.get("manifest_sha256") != sha or notes.get("profile_sha256") != digest(profile)
            or notes.get("first_lap_caption_reviewed") is not True
            or notes.get("boat_numbers_reviewed") is not True):
        raise ValueError("review_binding_or_lap_missing")
    frames = usable_frames(raw)
    load = frame_loader(path.parent, size, frames, coordinate_space=profile.get("coordinate_space", "screenshot"))
    check = camera_check(load, calibration_image(profile, size, private(calibration)), anchors)
    timeline = sorted((row["time"], name) for name, row in frames.items())
    reference = notes.get("first_lap_caption_frame")
    if reference not in frames or not check(reference):
        raise ValueError("first_lap_caption_frame_missing")
    claims = set()
    boats = []
    for boat in range(1, 7):
        events, missing = {}, {}
        track = notes["boats"].get(str(boat), {})
        for name in gates:
            pair = track.get(name)
            if pair is None:
                missing[name] = "unreadable_or_unreviewed"
                continue
            if not isinstance(pair, list) or len(pair) != 2 or any(f not in frames for f in pair):
                missing[name] = "unusable_crossing_frames"
                continue
            start, end = (frames[f]["time"] for f in pair)
            if not frames[reference]["time"] <= start < end or end - start > .251:
                missing[name] = "invalid_crossing_frame_range"
                continue
            if not all(check(f) for f in pair):
                missing[name] = "crossing_camera_mismatch"
                continue
            claim = name, tuple(pair)
            if claim in claims:
                raise ValueError("duplicate_gate_claim")
            claims.add(claim)
            events[name] = {"frames": pair, "bracket": [start, end]}
        previous = None
        for name in "ABCD":
            if name in events:
                if previous and events[previous]["bracket"][1] >= events[name]["bracket"][0]:
                    raise ValueError(f"overlapping_or_reversed_gates_boat_{boat}")
                previous = name
        sections = {}
        for name, (first, last) in SECTIONS.items():
            if first not in events or last not in events:
                sections[name] = {"status": "crossing_missing"}
                continue
            if name == "turn_total" and missing:
                sections[name] = {"status": "intermediate_gate_missing"}
                continue
            a, b = events[first]["bracket"], events[last]["bracket"]
            span = [(t, f) for t, f in timeline if a[0] <= t <= b[1]]
            if any(t2 - t1 > MAX_GAP_SECONDS for (t1, _), (t2, _) in zip(span, span[1:])):
                sections[name] = {"status": "frame_gap_in_section"}
                continue
            if not all(check(f) for _, f in span):
                sections[name] = {"status": "camera_mismatch_in_section"}
                continue
            lo, hi = b[0] - a[1], b[1] - a[0]
            sections[name] = {"status": "reference", "video_seconds": round((lo + hi) / 2, 3),
                              "bracket_range_video_seconds": [round(lo, 3), round(hi, 3)],
                              "checked_frame_count": len(span)}
        boats.append({"boat": boat, "crossings": events, "missing_crossings": missing, "segments": sections})
    return {"date": day, "venue": venue, "race": race, "lap": 1, "manifest_sha256": sha,
            "profile_sha256": digest(profile), "profile": profile,
            "time_basis": "browser_presented_frame_media_time",
            "measurement_method": "manual_visual_gate_brackets_midpoint",
            "independent_readers": 1, "continuous_bow_track_verified": False,
            "rating_ready": False, "usable_frames": len(frames), "boats": boats,
            "coverage": {name: sum(b["segments"][name]["status"] == "reference" for b in boats) for name in SECTIONS}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("manifest", "profile", "calibration", "notes", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    output = private(args.output)
    if output.exists():
        parser.error("requires a new output file")
    result = measure_brackets(args.manifest, read(private(args.profile)), args.calibration, read(private(args.notes)))
    write(output, result)
    print(json.dumps(result["coverage"]))


if __name__ == "__main__":
    main()
