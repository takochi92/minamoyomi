"""Research timing of a fixed camera shot from BOATCAST schema-2 captures."""
from __future__ import annotations

from collections import defaultdict
from functools import lru_cache
import hashlib
import math
from pathlib import Path
import re

from PIL import Image, ImageChops, ImageStat

from .exhibition_views import valid_date
from .turn_measurement import crossing, digest


VENUES = frozenset(f"{n:02}" for n in range(1, 25))
SEGMENTS = {
    "turn_entry": ("A", "B"),
    "turn_exit": ("B", "C"),
    "turn_total": ("A", "C"),
    "exit_recovery": ("C", "D"),
    "back_early": ("D", "E"),
    "back_late": ("E", "F"),
    "back_stretch": ("D", "F"),
}
MAX_GAP_SECONDS = 0.15
IMAGE_FILE = re.compile(r"f_[a-zA-Z0-9_-]+\.png\Z")
SHA256 = re.compile(r"[a-f0-9]{64}\Z")


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def point(value, size):
    return (isinstance(value, (list, tuple)) and len(value) == 2
            and all(finite(n) and 0 <= n < limit for n, limit in zip(value, size)))


def race_identity(manifest):
    day, race = manifest.get("date"), manifest.get("race")
    venue = (manifest.get("venue") or {}).get("jo")
    if not valid_date(day) or venue not in VENUES or type(race) is not int or not 1 <= race <= 12:
        raise ValueError("invalid_race_identity")
    return day, venue, race


def profile_geometry(profile):
    if (profile.get("schema") != 1 or profile.get("venue") not in VENUES
            or profile.get("lap") not in (1, 2) or not isinstance(profile.get("id"), str)
            or not profile["id"].strip()):
        raise ValueError("invalid_profile")
    size = profile.get("image_size")
    if not isinstance(size, list) or len(size) != 2 or any(type(n) is not int or not 64 <= n <= 4096 for n in size):
        raise ValueError("invalid_profile_image_size")
    gates = profile.get("gates") or {}
    if not {"A", "B", "C"} <= gates.keys() or not set(gates) <= set("ABCDEF"):
        raise ValueError("invalid_profile_gates")
    for gate in gates.values():
        axis, value, span = gate.get("axis"), gate.get("value"), gate.get("segment")
        if axis not in ("x", "y") or type(gate.get("direction")) is not int or gate["direction"] not in (-1, 1):
            raise ValueError("invalid_gate_axis_or_direction")
        idx = axis == "y"
        if (not finite(value) or not 0 < value < size[idx] or not isinstance(span, list)
                or len(span) != 2 or not all(finite(x) for x in span)
                or not 0 <= span[0] < span[1] < size[not idx]):
            raise ValueError("invalid_gate_extent")
    anchors = profile.get("anchors") or []
    if len(anchors) != 3 or any(not point(p, size) or any(type(n) is not int for n in p) for p in anchors):
        raise ValueError("three_fixed_landmarks_required")
    a, b, c = anchors
    if abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])) < 400:
        raise ValueError("fixed_landmarks_too_close_or_collinear")
    if any(not 18 <= n < limit - 18 for p in anchors for n, limit in zip(p, size)):
        raise ValueError("fixed_landmark_too_close_to_edge")
    return tuple(size), gates, anchors


def usable_frames(manifest):
    if (manifest.get("schema") != 2 or manifest.get("status") not in ("ok", "partial")
            or manifest.get("mode") != "seek"):
        raise ValueError("seek_capture_manifest_schema_2_required")
    rejected = {
        f for a in (manifest.get("measurement") or {}).get("anomalies", [])
        for f in a.get("files", [])
    }
    frames = {}
    seen = set()
    for row in manifest.get("frames") or []:
        name = row.get("file")
        if not isinstance(name, str) or not IMAGE_FILE.fullmatch(name) or name in seen:
            raise ValueError("invalid_or_duplicate_capture_filename")
        seen.add(name)
        t = (row.get("frame") or {}).get("mediaTime")
        sha = row.get("sha256")
        if (row.get("measurable") is True and row.get("stable") is True and row.get("paused") is True
                and row.get("seeked") is True and not row.get("duplicateOf") and name not in rejected
                and finite(t) and t >= 0 and isinstance(sha, str) and SHA256.fullmatch(sha)):
            frames[name] = {"time": t, "sha256": sha}
    counts = defaultdict(int)
    for row in frames.values():
        counts[row["time"]] += 1
    return {name: row for name, row in frames.items() if counts[row["time"]] == 1}


def frame_loader(directory, size, frames, *, image_mode="L"):
    directory = Path(directory).resolve()

    @lru_cache(maxsize=12)
    def load(name):
        path = directory / name
        if name not in frames or path.resolve() != path:
            raise ValueError("frame_file_outside_capture")
        try:
            with path.open("rb") as f:
                if hashlib.file_digest(f, "sha256").hexdigest() != frames[name]["sha256"]:
                    raise ValueError("frame_sha256_mismatch")
                f.seek(0)
                with Image.open(f, formats=["PNG"]) as im:
                    if im.size != size:
                        raise ValueError("frame_dimensions_mismatch")
                    return im.convert(image_mode)
        except OSError as error:
            raise ValueError("frame_file_unreadable") from error

    return load


def camera_check(load, reference_image, anchors):
    """Match every frame against the calibration shot, not a frame from this run."""
    radius = 10
    patches = [reference_image.crop((x - radius, y - radius, x + radius + 1, y + radius + 1))
               for x, y in anchors]
    if any(ImageStat.Stat(patch).stddev[0] < 10 for patch in patches):
        raise ValueError("fixed_landmark_texture_too_low")

    @lru_cache(maxsize=400)
    def check(name):
        im = load(name)
        for (x, y), patch in zip(anchors, patches):
            scores = []
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    other = im.crop((x + dx - radius, y + dy - radius,
                                     x + dx + radius + 1, y + dy + radius + 1))
                    error = ImageStat.Stat(ImageChops.difference(patch, other)).mean[0]
                    scores.append((error, dx * dx + dy * dy))
            error, drift = min(scores)
            if error > 14 or drift > 4:
                return False
        return True

    return check


def calibration_image(profile, size, path):
    sha = profile.get("calibration_sha256")
    if not isinstance(sha, str) or not SHA256.fullmatch(sha) or path is None:
        raise ValueError("pinned_camera_calibration_required")
    path = Path(path)
    return frame_loader(path.parent, size, {path.name: {"sha256": sha}})(path.name)


def read_track(observations, size, frames, window):
    """Keep unusable observations as barriers instead of bridging missing frames."""
    rows = []
    for observation in observations:
        name = observation.get("file")
        position = observation.get("bow")
        frame = frames.get(name)
        if not frame or not point(position, size) or not window[0] <= frame["time"] <= window[1]:
            rows.append(None)
            continue
        x, y = position
        rows.append({"file": name, "time": frame["time"], "x": x, "y": y})
    times = [r["time"] for r in rows if r is not None]
    if any(a >= b for a, b in zip(times, times[1:])):
        raise ValueError("unordered_or_repeated_track_frame")
    return rows


def fit_crossing(support, a, b, gate, max_residual, max_speed, frame_order):
    if len(support) < 5 or any(row is None for row in support):
        return None
    for left, right in zip(support, support[1:]):
        elapsed = right["time"] - left["time"]
        if (elapsed > MAX_GAP_SECONDS or frame_order[right["file"]] - frame_order[left["file"]] != 1
                or math.hypot(right["x"] - left["x"], right["y"] - left["y"]) > max_speed * elapsed):
            return None
    time = [row["time"] - a["time"] for row in support]
    position = [row[gate["axis"]] for row in support]
    t_mean, p_mean = sum(time) / len(time), sum(position) / len(position)
    slope = (sum((t - t_mean) * (p - p_mean) for t, p in zip(time, position)) /
             sum((t - t_mean) ** 2 for t in time))
    if slope * gate["direction"] <= 0:
        return None
    residual = max(abs(p - (p_mean + slope * (t - t_mean))) for t, p in zip(time, position))
    when = a["time"] + t_mean + (gate["value"] - p_mean) / slope
    if residual > max_residual or not a["time"] - 1e-9 <= when <= b["time"] + 1e-9:
        return None
    when = min(max(when, a["time"]), b["time"])
    other = "y" if gate["axis"] == "x" else "x"
    fraction = (when - a["time"]) / (b["time"] - a["time"])
    at_crossing = a[other] + fraction * (b[other] - a[other])
    if not gate["segment"][0] <= at_crossing <= gate["segment"][1]:
        return None
    return when, residual


def find_crossings(track, gates, check_camera, max_residual, max_speed, frame_order):
    events, uncertain = defaultdict(list), defaultdict(set)
    for i, (a, b) in enumerate(zip(track, track[1:])):
        if a is None or b is None:
            continue
        for label, gate in gates.items():
            if crossing(a, b, gate) is None:
                continue
            if b["time"] - a["time"] > MAX_GAP_SECONDS:
                uncertain[label].add("frame_gap_too_wide")
                continue
            try:
                verified = check_camera(a["file"]) and check_camera(b["file"])
            except ValueError as error:
                uncertain[label].add(str(error))
                continue
            if not verified:
                uncertain[label].add("camera_landmark_changed")
                continue
            offset = max(0, min(i - 1, len(track) - 5))
            support = track[offset:offset + 5]
            fit = fit_crossing(support, a, b, gate, max_residual, max_speed, frame_order)
            if fit is None:
                uncertain[label].add("unstable_or_insufficient_crossing_track")
                continue
            try:
                if not all(check_camera(row["file"]) for row in support):
                    uncertain[label].add("camera_landmark_changed")
                    continue
            except ValueError as error:
                uncertain[label].add(str(error))
                continue
            when, residual = fit
            events[label].append({
                "seconds": when, "bracket": [a["time"], b["time"]],
                "frames": [a["file"], b["file"]],
                "fit_frames": [row["file"] for row in support],
                "max_fit_residual_pixels": round(residual, 3),
            })
    found, missing = {}, {}
    for label in gates:
        matches = events[label]
        if len(matches) == 1 and not uncertain[label]:
            found[label] = matches[0]
        elif matches:
            missing[label] = sorted({"ambiguous_crossing", *uncertain[label]})
        else:
            missing[label] = sorted(uncertain[label] or {"crossing_not_observed"})
    if any(a["seconds"] >= b["seconds"] for a, b in zip(found.values(), list(found.values())[1:])):
        return {}, {k: ["gate_order_invalid"] for k in gates}
    return found, missing


def section_times(events, gates, frame_sequence, check_camera, track, max_speed):
    sections = {}
    positions = {row["file"]: row for row in track if row is not None}
    for name, (start, end) in SEGMENTS.items():
        if start not in gates or end not in gates:
            sections[name] = {"status": "gate_not_configured"}
            continue
        a, b = events.get(start), events.get(end)
        if not a or not b:
            sections[name] = {"status": "crossing_missing"}
            continue
        earliest, latest = b["bracket"][0] - a["bracket"][1], b["bracket"][1] - a["bracket"][0]
        if earliest <= 0:
            sections[name] = {"status": "crossing_brackets_overlap"}
            continue
        span = [(time, name) for time, name in frame_sequence
                if a["bracket"][0] <= time <= b["bracket"][1]]
        if any(t2 - t1 > MAX_GAP_SECONDS for (t1, _), (t2, _) in zip(span, span[1:])):
            sections[name] = {"status": "frame_gap_in_section"}
            continue
        try:
            stable = all(check_camera(name) for _, name in span)
        except ValueError as error:
            sections[name] = {"status": str(error)}
            continue
        if not stable:
            sections[name] = {"status": "camera_landmark_changed_in_section"}
            continue
        if any(frame not in positions for _, frame in span):
            sections[name] = {"status": "bow_track_missing_in_section"}
            continue
        points = [positions[frame] for _, frame in span]
        if any(math.hypot(b["x"] - a["x"], b["y"] - a["y"]) > max_speed * (b["time"] - a["time"])
               for a, b in zip(points, points[1:])):
            sections[name] = {"status": "bow_track_jump_in_section"}
            continue
        sections[name] = {"status": "reference",
                          "video_seconds": round(b["seconds"] - a["seconds"], 3),
                          "bracket_range_video_seconds": [round(earliest, 3), round(latest, 3)]}
    return sections


def overlapping_tracks(tracks):
    claims = defaultdict(list)
    for boat, track in tracks.items():
        for row in track:
            if row is not None:
                claims[row["file"]].append((boat, row["x"], row["y"]))
    conflicts = defaultdict(int)
    for claims_in_frame in claims.values():
        for i, (boat, x, y) in enumerate(claims_in_frame):
            for other, x2, y2 in claims_in_frame[i + 1:]:
                if math.hypot(x - x2, y - y2) <= 3:
                    conflicts[tuple(sorted((boat, other)))] += 1
    return {boat for pair, count in conflicts.items() if count >= 2 for boat in pair}


def measure(manifest, profile, review, directory, *, manifest_sha256, calibration=None):
    day, venue, race = race_identity(manifest)
    size, gates, anchors = profile_geometry(profile)
    gates = dict(sorted(gates.items()))
    if profile["venue"] != venue:
        raise ValueError("profile_venue_mismatch")
    if (review.get("schema") != 1 or review.get("manifest_sha256") != manifest_sha256
            or review.get("profile_sha256") != digest(profile)):
        raise ValueError("annotation_binding_mismatch")
    if review.get("camera_layout_reviewed") is not True:
        raise ValueError("camera_layout_review_required")
    window = review.get("window")
    if (not isinstance(window, list) or len(window) != 2 or not all(finite(t) for t in window)
            or not 0 <= window[0] < window[1] or window[1] - window[0] > 120):
        raise ValueError("invalid_fixed_shot_window")
    frames = usable_frames(manifest)
    reference = review.get("camera_reference")
    if reference not in frames or not window[0] <= frames[reference]["time"] <= window[1]:
        raise ValueError("camera_reference_missing")
    tracks = review.get("boats") or {}
    if not isinstance(tracks, dict) or not set(tracks) <= {str(i) for i in range(1, 7)}:
        raise ValueError("invalid_boat_numbers")
    image = calibration_image(profile, size, calibration)
    max_speed = profile.get("max_bow_pixels_per_video_second")
    if not finite(max_speed) or max_speed <= 0:
        raise ValueError("bow_speed_limit_required")
    max_residual = profile.get("max_crossing_fit_residual_pixels")
    if not finite(max_residual) or max_residual <= 0:
        raise ValueError("crossing_fit_residual_limit_required")
    check_camera = camera_check(frame_loader(directory, size, frames), image, anchors)
    if not check_camera(reference):
        raise ValueError("capture_does_not_match_camera_calibration")
    frame_sequence = sorted((row["time"], name) for name, row in frames.items())
    frame_order = {name: i for i, (_, name) in enumerate(frame_sequence)}
    identity = review.get("identity") or {}
    checked, reasons = {}, {}
    for boat, observations in tracks.items():
        try:
            checked[boat] = read_track(observations, size, frames, window)
        except ValueError as error:
            reasons[boat] = str(error)
    duplicates = overlapping_tracks(checked)
    boats = []
    for boat in range(1, 7):
        key = str(boat)
        track = checked.get(key, [])
        evidence = identity.get(key) or {}
        reason = reasons.get(key)
        if key in duplicates:
            reason = "overlapping_boat_tracks"
        elif track and (type(evidence.get("boat")) is not int or evidence["boat"] != boat
                        or evidence.get("method") not in ("boat_color", "visible_number")
                        or evidence.get("file") not in {row["file"] for row in track if row is not None}):
            reason = "boat_identity_evidence_required"
        if reason:
            events, missing = {}, {k: [reason] for k in gates}
        else:
            events, missing = find_crossings(track, gates, check_camera, max_residual, max_speed, frame_order)
        boats.append({"boat": boat, "crossings": events, "missing_crossings": missing,
                      "identity": None if reason or not track else {k: evidence[k] for k in ("boat", "method", "file")},
                      "observations": [row for row in track if row is not None],
                      "segments": section_times(events, gates, frame_sequence, check_camera, track, max_speed)})
    return {
        "schema": 1, "date": day, "venue": venue, "race": race, "lap": profile["lap"],
        "profile_id": profile["id"], "manifest_sha256": manifest_sha256,
        "profile_sha256": digest(profile), "review_sha256": digest(review),
        "quality_checks": "pinned_camera_and_continuous_track_v2",
        "time_basis": "browser_presented_frame_media_time",
        "full_backstretch_verified": False, "real_time_scale_verified": False,
        "measurement_mode": "reviewed_or_imported_bow_track",
        "publication_ready": False, "rating_eligible": False,
        "boats": boats,
        "coverage": {name: sum(b["segments"][name]["status"] == "reference" for b in boats)
                     for name in SEGMENTS},
    }
