"""Offline Heiwajima 1-mark experiment. Never imported by production updates.

CSRT needs a human-selected boat box. Its success flag is NOT a quality score.
Only local, lawfully obtained frames are accepted; there is no remote downloader.
The output is research evidence, not publication-ready measurements.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def crossing(a, b, gate):
    """Interpolate a directed crossing of a bounded, fixed image segment."""
    axis = gate["axis"]
    other = "y" if axis == "x" else "x"
    start, end = a[axis], b[axis]
    value, direction = gate["value"], gate["direction"]
    if not (start < value <= end if direction == 1 else start > value >= end):
        return None
    fraction = (value - start) / (end - start)
    position = a[other] + fraction * (b[other] - a[other])
    if not gate["segment"][0] <= position <= gate["segment"][1]:
        return None
    return a["time"] + fraction * (b["time"] - a["time"])


def evaluate_track(points, gates, *, max_gap=0.2, excluded_regions=()):
    """Fail closed on missing, discontinuous, obstructed or ambiguous tracks.

    Even a clean track remains a candidate requiring manual hull-centre review,
    camera/clock calibration and an independent race before public use.
    """
    reasons = []
    if len(points) < 2:
        return {"status": "rejected", "reasons": ["too_few_points"], "events": {}}
    if any(not p.get("ok") or any(
        not isinstance(p.get(k), (int, float)) or not math.isfinite(p[k])
        for k in ("time", "x", "y")
    ) for p in points):
        return {"status": "rejected", "reasons": ["invalid_tracking_point"], "events": {}}
    if any(not 0 < b["time"] - a["time"] <= max_gap for a, b in zip(points, points[1:])):
        reasons.append("timestamp_gap_or_reversal")
    def overlaps(p, region):
        x1, y1, x2, y2 = region
        if "bbox" in p:
            x, y, w, h = p["bbox"]
            return x < x2 and x + w > x1 and y < y2 and y + h > y1
        return x1 <= p["x"] <= x2 and y1 <= p["y"] <= y2
    if any(overlaps(p, region) for p in points for region in excluded_regions):
        reasons.append("player_overlay_or_obstruction")
    events = {}
    for name, gate in gates.items():
        hits = [t for a, b in zip(points, points[1:])
                if (t := crossing(a, b, gate)) is not None]
        if len(hits) == 1:
            events[name] = hits[0]
        else:
            reasons.append("missing_or_repeated_gate_" + name)
    # Ignore stopping after the exit: it cannot affect a completed interval.
    # A stationary UI control BEFORE the exit still invalidates the track.
    exit_time = events.get("C", float("inf"))
    for i, p in enumerate(points):
        if p["time"] > exit_time:
            break
        window = []
        for q in points[i:]:
            if q["time"] - p["time"] > 0.6 or q["time"] > exit_time:
                break
            window.append(q)
        if window and window[-1]["time"] - p["time"] >= 0.5:
            if max(math.hypot(q["x"] - p["x"], q["y"] - p["y"]) for q in window) < 3:
                reasons.append("stationary_track")
                break
    if len(events) == 3 and not events["A"] < events["B"] < events["C"]:
        reasons.append("invalid_gate_order")
    result = {"status": "rejected" if reasons else "needs_manual_review",
              "reasons": reasons, "events": events}
    # Suppress apparent times for failed tracks rather than publish plausible lies.
    if not reasons:
        result["candidate_entry_video_seconds"] = round(events["B"] - events["A"], 1)
        result["candidate_exit_video_seconds"] = round(events["C"] - events["B"], 1)
    return result


def assess(tracks, config):
    if config.get("venue") != "heiwajima" or config.get("turn") != "1-mark":
        raise ValueError("This pilot only supports Heiwajima 1-mark")
    boats = [row["boat"] for row in tracks]
    if sorted(boats) != list(range(1, 7)):
        raise ValueError("Exactly six distinct boat identities are required")
    results = [{"boat": row["boat"], **evaluate_track(
        row["points"], config["gates"], excluded_regions=config.get("excluded_regions", []))}
        for row in tracks]
    return {"schema": 1, "method": "human-seeded-CSRT-image-gates-v1",
            "venue": config["venue"], "date": config["date"], "race": config["race"],
            "source": config["source"], "gates": config["gates"],
            "image_size": config["image_size"], "results": results,
            "publication_ready": False, "prediction_used": False,
            "automatic_boat_identification": False, "camera_calibrated": False,
            "video_clock_calibrated": False,
            "reference_point": "CSRT bounding-box centre; hull-centre agreement unverified",
            "scope": "ended-race offline experiment; not predeadline evidence"}


def track_local_frames(directory, config):
    import cv2  # Optional research dependency; not part of production requirements.

    directory = Path(directory).resolve()
    frames = json.loads((directory / "frames.json").read_text(encoding="utf-8"))
    def load(row):
        path = (directory / row["file"]).resolve()
        if path.parent != directory:
            raise ValueError("Frame must be directly inside the supplied directory")
        image = cv2.imread(str(path))
        if image is None or [image.shape[1], image.shape[0]] != config["image_size"]:
            raise ValueError("Missing frame or changed camera dimensions")
        if not (math.isfinite(row["before"]) and math.isfinite(row["after"])):
            raise ValueError("Nonfinite capture time")
        if not 0 <= row["after"] - row["before"] <= 0.15:
            raise ValueError("Capture clock interval too wide or reversed")
        return image
    tracks = []
    for seed in config["seeds"]:
        start, end = seed["start"], seed["end"]
        if not 0 <= start < end <= len(frames):
            raise ValueError("Invalid frame range")
        tracker = cv2.TrackerCSRT_create()
        bbox = tuple(seed["bbox"])
        tracker.init(load(frames[start]), bbox)
        points = []
        for index in range(start, end):
            row = frames[index]
            if index == start:
                ok, box = True, bbox
            else:
                ok, box = tracker.update(load(row))
            x, y, width, height = box
            points.append({"frame": index, "time": (row["before"] + row["after"]) / 2,
                           "ok": bool(ok), "x": x + width / 2, "y": y + height / 2,
                           "bbox": list(box)})
        tracks.append({"boat": seed["boat"], "points": points})
    return tracks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--frames", type=Path)
    source.add_argument("--tracks", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    tracks = (track_local_frames(args.frames, config) if args.frames else
              json.loads(args.tracks.read_text(encoding="utf-8")))
    args.output.mkdir(parents=True, exist_ok=True)
    report = assess(tracks, config)
    (args.output / "tracks.json").write_text(json.dumps(tracks, indent=2), encoding="utf-8")
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"publication_ready": False, "results": [
        {"boat": r["boat"], "status": r["status"], "reasons": r["reasons"]}
        for r in report["results"]]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
