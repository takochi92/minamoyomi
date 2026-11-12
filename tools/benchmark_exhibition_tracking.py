"""Benchmark the existing actor tracker on a capture with manually observed bow points."""
from __future__ import annotations

import argparse
from functools import lru_cache
import json
import math
from pathlib import Path

from scraper.exhibition_segments import frame_loader, profile_geometry, race_identity, usable_frames
from scraper.turn_measurement import digest
from tools.boat_tracking import track_actor
from tools.measure_exhibition import manifest_at, private, read, write


def labeled_frames(reference):
    """Take mediaTime only from persisted crossing records with explicit frame binding."""
    times = {}
    for boat in reference["result"]["boats"]:
        for crossing in boat["crossings"].values():
            for name, time in zip(crossing["frames"], crossing["bracket"]):
                if name in times and times[name] != time:
                    raise ValueError("conflicting_reference_media_time")
                times[name] = time
    return times


def benchmark(manifest_path, reference_path, profile_path):
    import numpy as np

    path, manifest, sha = manifest_at(manifest_path)
    race = race_identity(manifest)
    reference = read(private(reference_path))
    baseline = reference["result"]
    profile = read(private(profile_path))
    profile_size, _, _ = profile_geometry(profile)
    if baseline["profile_sha256"] != digest(profile) or profile.get("coordinate_space", "screenshot") != "screenshot":
        raise ValueError("reference_screenshot_profile_mismatch")
    if race != race_identity({"date": baseline["date"], "venue": {"jo": baseline["venue"]},
                             "race": baseline["race"]}):
        raise ValueError("reference_race_mismatch")
    frames = usable_frames(manifest)
    names = sorted(frames, key=lambda name: frames[name]["time"])
    if not names:
        raise ValueError("no_usable_capture_frames")
    size = next(row["screenshot"] for row in manifest["frames"] if row["file"] == names[0])
    width, height = size["width"], size["height"]
    if (width, height) != profile_size:
        raise ValueError("reference_screenshot_dimensions_mismatch")
    load = frame_loader(path.parent, (width, height), frames, image_mode="RGB")
    by_time = {round(frames[name]["time"], 6): i for i, name in enumerate(names)}
    times = labeled_frames(reference)

    @lru_cache(maxsize=18)
    def image(index):
        return np.asarray(load(names[index]))[:, :, ::-1].copy()

    boats = []
    for boat, observations in sorted(reference["capture"]["observations"].items(), key=lambda pair: int(pair[0])):
        labels = {by_time[round(times[row["file"]], 6)]: row["bow"] for row in observations
                  if row["file"] in times and round(times[row["file"]], 6) in by_time}
        if len(labels) < 3:
            boats.append({"boat": int(boat), "status": "insufficient_same_time_labels", "labels": len(labels)})
            continue
        first, last = min(labels), max(labels)
        labelled_holdouts = set(labels) - {first, last}
        tracked_frames, labels_seen, labels_near_box = set(), set(), set()
        runs = []
        for direction, seed in (("turn_approach", first), ("straight", last)):
            x, y = labels[seed]
            left = x - (55 if direction == "turn_approach" else 8)
            box = [max(0, left), max(0, y - 14), 63, 42]
            if box[0] + box[2] >= width or box[1] + box[3] >= height:
                continue
            diagnostic = {}
            clip = track_actor(lambda index: image(first + index), seed - first, box,
                               last - first + 1, max_steps=100, diagnostics=diagnostic)
            hits = []
            for step in clip:
                i = first + step["frame"]
                tracked_frames.add(i)
                if i not in labelled_holdouts:
                    continue
                x, y = labels[i]
                left, top, w, h = step["box"]
                distance = math.hypot(max(0, left - x, x - left - w),
                                      max(0, top - y, y - top - h))
                hits.append({"media_time": frames[names[i]]["time"],
                             "distance_outside_box_px": round(distance, 2)})
                labels_seen.add(i)
                if distance <= 8:
                    labels_near_box.add(i)
            runs.append({"seed": direction, "frame_count": len(clip),
                         "holdouts": hits, "stops": [row["stop_reason"] for row in diagnostic["directions"]]})
        boats.append({"boat": int(boat), "status": "actor_candidates_only",
                      "clip_frames": last - first + 1, "frames_with_candidate": len(tracked_frames),
                      "matched_reference_frames": len(labels), "holdout_count": len(labelled_holdouts),
                      "holdouts_with_candidate": len(labels_seen),
                      "holdouts_near_box": len(labels_near_box), "runs": runs})
    return {"date": race[0], "venue": race[1], "race": race[2], "manifest_sha256": sha,
            "usable_capture_frames": len(frames), "image_size": [width, height],
            "method": "existing_actor_optical_flow_with_two_manual_seeds",
            "reference": "legacy_human_bow_observations_with_exact_media_time",
            "bow_measurement_validated": False, "rating_ready": False, "boats": boats}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("manifest", "reference", "profile", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    output = private(args.output)
    if output.exists():
        parser.error("requires a new output file")
    result = benchmark(args.manifest, args.reference, args.profile)
    write(output, result)
    print(json.dumps({b["boat"]: [b.get("frames_with_candidate"), b.get("clip_frames")] for b in result["boats"]}))


if __name__ == "__main__":
    main()
