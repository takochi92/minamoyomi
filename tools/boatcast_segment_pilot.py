"""Measure color tracks from a private BOATCAST seek capture.

A camera profile is calibrated separately. This command writes diagnostic
candidates only. A pilot capture never creates an ingestable metric by itself.
"""
from __future__ import annotations

import argparse
import base64
from collections import Counter
import hashlib
import json
from pathlib import Path
from statistics import mean, stdev
import re
from time import monotonic

import cv2
import numpy as np

from scraper.independent_metrics import clean_row, finite, robust_crossing
from scraper.motor_generation import DATA, FILENAME
from tools.independent_metrics import fleet_starts


# OpenCV hue is 0..179. White is left unmeasured until an identity cue is validated.
HUES = {3: ((0, 12), (168, 179)), 4: ((91, 129),),
        5: ((19, 41),), 6: ((42, 88),)}
FRAME_NAME = re.compile(r"f_[a-zA-Z0-9_-]+\.png\Z")
FRAME_STEP = 1 / 30
RADIUS = 10


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def capture_frames(manifest):
    if manifest.get("schema") != 2 or manifest.get("mode") != "seek" or manifest.get("status") not in ("ok", "partial"):
        raise ValueError("a completed schema-2 seek capture is required")
    anomalies = {name for a in manifest.get("measurement", {}).get("anomalies", [])
                 for name in a.get("files", [])}
    frames, seen, names = [], set(), set()
    for row in sorted(manifest["frames"], key=lambda r: r["requestedSec"]):
        file = row.get("file")
        if not isinstance(file, str) or not FRAME_NAME.fullmatch(file) or file in names:
            raise ValueError("invalid or repeated screenshot filename")
        names.add(file)
        t = (row.get("frame") or {}).get("mediaTime")
        if (not finite(t) or t < 0 or t in seen or file in anomalies or row.get("duplicateOf")
                or not all(row.get(k) is True for k in ("measurable", "stable", "paused", "seeked"))):
            continue
        seen.add(t)
        frames.append((float(t), file, row["sha256"]))
    return sorted(frames)


def image(root, file, sha, size):
    path = root / file
    if path.resolve() != path:
        raise ValueError("screenshot must be a regular file in the capture directory")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != sha:
        raise ValueError("screenshot digest mismatch")
    frame = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None or frame.shape[:2] != tuple(reversed(size)):
        raise ValueError("unexpected screenshot dimensions")
    return frame


def patch_gray(frame):
    return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


def patch_reference(frame, anchors):
    gray = patch_gray(frame)
    return [base64.b64encode(gray[y-RADIUS:y+RADIUS+1, x-RADIUS:x+RADIUS+1].tobytes()).decode()
            for x, y in anchors]


def camera_matches(frame, anchors, patches):
    gray = patch_gray(frame)
    for (x, y), patch in zip(anchors, patches, strict=True):
        search = gray[y-RADIUS-4:y+RADIUS+5, x-RADIUS-4:x+RADIUS+5].astype(np.int16)
        if search.shape != (29, 29):
            return False
        windows = np.lib.stride_tricks.sliding_window_view(search, (21, 21))
        errors = np.abs(windows - patch).mean(axis=(-2, -1))
        dy, dx = np.unravel_index(np.argmin(errors), errors.shape)
        if errors[dy, dx] > 14 or (dy - 4)**2 + (dx - 4)**2 > 4:
            return False
    return True


def pixels_for_boat(hsv, motion, boat):
    h, s, v = cv2.split(hsv)
    if boat == 2:
        return motion & (v <= 65) & (s <= 100)
    selected = np.zeros(h.shape, dtype=bool)
    for lower, upper in HUES[boat]:
        selected |= (h >= lower) & (h <= upper)
    return motion & selected & (s >= 90) & (v >= 75)


def components(hsv, motion, boat, offset, axis, direction):
    mask = pixels_for_boat(hsv, motion, boat)
    mask = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))
    n, labels, stats, centers = cv2.connectedComponentsWithStats(mask)
    found = []
    for label in range(1, n):
        x, y, w, h, area = stats[label]
        if not (7 <= area <= 350 and 3 <= w <= 70 and 2 <= h <= 40):
            continue
        yy, xx = np.where(labels[y:y+h, x:x+w] == label)
        coords = (xx, yy)
        origins = (x, y)
        edge = np.percentile(coords[axis], 90 if direction > 0 else 10) + origins[axis] + offset[axis]
        found.append((float(edge), float(centers[label, 1 - axis] + offset[1 - axis])))
    return found


def tracks(detections, direction):
    groups = []
    for time, candidates in detections:
        active = [g for g in groups if 0 < time - g[-1][0] <= 2.2 * FRAME_STEP]
        links = {}
        for i, (x, y) in enumerate(candidates):
            matches = [g for g in active if abs(g[-1][2] - y) <= 13
                       and -4 <= (x - g[-1][1]) * direction <= 35]
            links[i] = matches
        for i, (x, y) in enumerate(candidates):
            matches = links[i]
            if not matches:
                groups.append([(time, x, y)])
            elif len(matches) == 1 and sum(matches[0] in m for m in links.values()) == 1:
                matches[0].append((time, x, y))
    return groups


def crossings(track, position, direction):
    hits = []
    for i, (before, after) in enumerate(zip(track, track[1:])):
        if (before[1] - position) * direction < 0 <= (after[1] - position) * direction:
            nearby = track[max(0, i-4):i+6]
            if any(b[0] - a[0] > 1.6 * FRAME_STEP for a, b in zip(nearby, nearby[1:])):
                continue
            fitted = robust_crossing([(t, x) for t, x, _ in nearby], position, direction)
            if fitted and before[0] - FRAME_STEP <= fitted["seconds"] <= after[0] + FRAME_STEP:
                hits.append(fitted)
    return hits


def measure(manifest_path, profile, card, *, fleet_data=None):
    started = monotonic()
    manifest = read(manifest_path)
    venue = manifest["venue"]["jo"]
    identity = manifest["date"], venue, manifest["race"]
    if (identity != (card.get("date"), card.get("jcd"), card.get("rno"))
            or venue != profile["venue"] or manifest.get("raceType") != "exhibition"):
        raise ValueError("capture, profile and official card do not identify the same race")
    fleet_data = DATA if fleet_data is None else fleet_data
    ledger = read(fleet_data / FILENAME) if (fleet_data / FILENAME).is_file() else {}
    starts = fleet_starts(max(identity[0], ledger.get("date", identity[0])), fleet_data)
    if venue not in starts or identity[0] < starts[venue]:
        raise ValueError("motor generation not confirmed for this race")
    boats = (card.get("racelist") or {}).get("boats") or []
    entries = {b["frame"]: b for b in boats}
    before = {b["frame"]: b for b in (card.get("before") or {}).get("boats", [])}
    if set(before) != set(range(1, 7)):
        raise ValueError("official exhibition entries and part changes are required")
    if (set(entries) != set(range(1, 7)) or len(boats) != 6
            or len({b.get("motor_no") for b in boats}) != 6):
        raise ValueError("six identified official boats are required")
    root = manifest_path.parent.resolve()
    frames = capture_frames(manifest)
    anchors = profile["anchors"]
    patches = [np.frombuffer(base64.b64decode(raw, validate=True), dtype=np.uint8).reshape(21, 21).astype(np.int16)
               for raw in profile["anchor_patches"]]
    if len(anchors) != 3 or len(patches) != 3 or any(p.std() < 10 for p in patches):
        raise ValueError("three fixed textured landmarks are required")

    x1, y1, x2, y2 = profile["roi"]
    gates = profile["gates"]
    if len(gates) != 2:
        raise ValueError("exactly two ordered gates are required")
    metric = profile.get("metric", "straight")
    axis = {"x": 0, "y": 1}[profile.get("axis", "x")]
    direction = 1 if gates[1] > gates[0] else -1
    bounds = ((x1, x2), (y1, y2))
    if (not 0 <= x1 < x2 <= profile["image_size"][0] or not 0 <= y1 < y2 <= profile["image_size"][1]
            or not bounds[axis][0] < min(gates) < max(gates) < bounds[axis][1]):
        raise ValueError("invalid measurement gate or search area")
    accepted, rejected = [], []
    for t, file, sha in frames:
        frame = image(root, file, sha, profile["image_size"])
        if camera_matches(frame, anchors, patches):
            accepted.append((t, frame[y1:y2, x1:x2].copy()))
        else:
            rejected.append(t)

    diagnostics = {"date": identity[0], "venue": venue, "race": identity[2],
                   "requested": len(manifest["frames"]), "usable": len(frames),
                   "camera_rejected_times": rejected, "boats": {}, "candidates": [],
                   "capture_frame_reasons": dict(Counter(reason for row in manifest["frames"]
                       for reason in row.get("notMeasurableReasons", []))),
                   "capture_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                   "profile": profile["id"], "metric": metric,
                   "profile_sha256": hashlib.sha256(json.dumps(profile, sort_keys=True).encode()).hexdigest(),
                   "quality_approved": False,
                   "fleet_start": starts[venue]}
    if len(accepted) < 12:
        diagnostics["boats"] = {str(boat): {"missing": "insufficient_fixed_camera_frames"}
                                for boat in range(1, 7)}
    if len(accepted) >= 12:
        refs = [crop for _, crop in accepted[::max(1, len(accepted)//35)]]
        background = np.median(np.stack(refs), axis=0).astype(np.uint8)
        detections = {boat: [] for boat in range(2, 7)}
        for t, crop in accepted:
            hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
            diff = cv2.absdiff(crop, background).max(axis=2) >= 28
            for boat, points in detections.items():
                points.append((t, components(hsv, diff, boat, (x1, y1), axis, direction)))

        diagnostics["boats"]["1"] = {"missing": "white_identity_unvalidated"}
        for boat, points in detections.items():
            found = []
            gate_hits = Counter()
            groups = tracks(points, direction)
            for track in groups:
                if len(track) < 6:
                    continue
                first, last = (crossings(track, gate, direction) for gate in gates)
                gate_hits["start"] += len(first)
                gate_hits["end"] += len(last)
                if len(first) == len(last) == 1 and first[0]["seconds"] < last[0]["seconds"]:
                    found.append((first[0], last[0]))
            diagnostics["boats"][str(boat)] = {"segments_found": len(found),
                "longest_track": max(map(len, groups), default=0),
                "fitted_gate_hits": dict(gate_hits),
                "frames_without_candidate": [round(t, 6) for t, options in points if not options],
                "ambiguous_frames": [round(t, 6) for t, options in points if len(options) > 1]}
            if len(found) != 1:
                diagnostics["boats"][str(boat)]["missing"] = "no_unique_continuous_gate_track"
                continue
            a, b = found[0]
            entry = entries[boat]
            diagnostics["boats"][str(boat)]["crossings"] = [a, b]
            diagnostics["candidates"].append(clean_row({
                "date": identity[0], "venue": venue, "race": identity[2], "boat": boat,
                "motor": entry["motor_no"], "rider": str(entry["toban"]), "metric": metric,
                "seconds": round(b["seconds"] - a["seconds"], 4), "source": "video",
                "profile": profile["id"], "parts": before[boat].get("parts") or [],
            }))
    diagnostics["analysis_seconds"] = round(monotonic() - started, 3)
    return diagnostics


def rank_correlation(left, right):
    def ranks(values):
        return [sum(v < x for v in values) + (values.count(x) - 1) / 2 for x in values]

    a, b = np.asarray(ranks(left)), np.asarray(ranks(right))
    if a.std() == 0 or b.std() == 0:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def quality_report(races):
    """Score a declared batch; each failed or skipped race still counts toward D.

    Each batch entry contains one race's capture reports, an optional manual
    full-frame reference, and optional same-section official times. The manual
    and official time maps are keyed by boat number.
    """
    keys, repeats, manual, correlations = set(), [], [], []
    covered = 0
    profiles = set()
    for row in races:
        first = row["first"]
        key = first["date"], first["venue"], first["race"]
        if key in keys:
            raise ValueError("duplicate race in quality batch")
        keys.add(key)
        profiles.add((first["metric"], first["profile_sha256"]))
        a = {str(v["boat"]): v["seconds"] for v in first["candidates"]}
        covered += len(a) >= 5 and row.get("full_race") is True
        if row.get("second"):
            second = row["second"]
            if (key != (second["date"], second["venue"], second["race"])
                    or first["profile_sha256"] != second["profile_sha256"]
                    or first["capture_sha256"] == second["capture_sha256"]):
                raise ValueError("repeat must be a separate capture of the same race and profile")
            b = {str(v["boat"]): v["seconds"] for v in second["candidates"]}
            repeats.extend(a[k] - b[k] for k in a.keys() & b.keys())
        if row.get("manual_full_frames") is True:
            b = row.get("manual", {})
            manual.extend(a[k] - b[k] for k in a.keys() & b.keys())
        if row.get("official_same_section") is True and row.get("full_race") is True:
            b = row.get("official", {})
            common = sorted(a.keys() & b.keys())
            if len(common) >= 5:
                rho = rank_correlation([a[k] for k in common], [b[k] for k in common])
                if rho is not None:
                    correlations.append(rho)
    if len(profiles) > 1:
        raise ValueError("use one metric and calibrated profile per quality batch")
    a_sd = stdev(repeats) if len(repeats) >= 2 else None
    b_sd = stdev(manual) if len(manual) >= 2 else None
    rho = mean(correlations) if correlations else None
    fraction = covered / len(keys) if keys else None
    return {
        "A": {"pairs": len(repeats), "sd_seconds": a_sd, "mean_error": mean(repeats) if repeats else None,
              "pass": a_sd is not None and a_sd <= .01},
        "B": {"pairs": len(manual), "sd_seconds": b_sd, "mean_error": mean(manual) if manual else None,
              "pass": len(manual) >= 30 and b_sd <= .02},
        "C": {"races": len(correlations), "mean_race_spearman": rho,
              "pass": len(correlations) >= 20 and rho >= .6},
        "D": {"races": len(keys), "with_five_boats": covered, "fraction": fraction,
              "pass": fraction is not None and fraction >= .7},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--quality-batch", type=Path, help="Private JSON array of validation races")
    parser.add_argument("--card", type=Path)
    parser.add_argument("--fleet-data", type=Path, help="Directory with the existing motor-periods.json ledger")
    parser.add_argument("--reference", help="Create a private profile from a manually reviewed landmark frame")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.name == "rows.json" or args.output.exists() or "site" in args.output.resolve().parts:
        parser.error("use a new private diagnostic output file")
    if args.quality_batch:
        result = quality_report(read(args.quality_batch))
        args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result))
        return
    if not args.manifest or not args.profile:
        parser.error("--manifest and --profile are required for capture analysis")
    if args.reference:
        profile = read(args.profile)
        path = args.manifest
        frame = next((f for f in capture_frames(read(path)) if f[1] == args.reference), None)
        if frame is None:
            parser.error("reference must be a measurable frame in the manifest")
        ref = image(path.parent.resolve(), frame[1], frame[2], profile["image_size"])
        profile["anchor_patches"] = patch_reference(ref, profile["anchors"])
        args.output.write_text(json.dumps(profile, indent=2), encoding="utf-8")
        return
    if not args.card:
        parser.error("--card is required for measurement")
    result = measure(args.manifest, read(args.profile), read(args.card), fleet_data=args.fleet_data)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("requested", "usable", "analysis_seconds")}))
    print("candidate boats", len(result["candidates"]), "camera rejected", len(result["camera_rejected_times"]))


if __name__ == "__main__":
    main()
