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
MAX_STEP_FRACTION = 0.08       # 0.1秒あたりの艇首の移動上限（画像の長辺に対する割合）。これを超える動きは別の艇への乗り移りとみなす
SHARED_TRACK_PIXELS = 2.0      # 2艇の艇首がこの距離以内で重なるコマが2つ以上あれば、同じ軌跡の使い回しとみなす
FIT_HALF_WINDOW_SECONDS = 0.25 # 通過時刻の当てはめに使う、基準線の前後の時間幅
PATCH_RADIUS = 10
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


def anchor_patches(profile, anchors):
    """Reference patches stored in the profile (base64 of raw 8-bit grey). None when the profile has none."""
    import base64
    raw = profile.get("anchor_patches")
    if raw is None:
        return None
    side = 2 * PATCH_RADIUS + 1
    if not isinstance(raw, list) or len(raw) != len(anchors):
        raise ValueError("invalid_profile_anchor_patches")
    patches = []
    for item in raw:
        try:
            data = base64.b64decode(item, validate=True)
        except (TypeError, ValueError) as error:
            raise ValueError("invalid_profile_anchor_patches") from error
        if len(data) != side * side:
            raise ValueError("invalid_profile_anchor_patches")
        patches.append(Image.frombytes("L", (side, side), data))
    return patches


def make_anchor_patches(image, anchors):
    import base64
    r = PATCH_RADIUS
    return [base64.b64encode(image.convert("L").crop((x - r, y - r, x + r + 1, y + r + 1)).tobytes()).decode()
            for x, y in anchors]


def camera_check(load, reference, anchors, stored=None):
    """Check small textured patches on three fixed landmarks.

    With `stored` patches (from the profile) every frame is compared with the view the profile was
    calibrated on. Without them only consistency inside this capture is checked, which cannot detect
    a capture taken with another zoom or camera position.
    """
    radius = PATCH_RADIUS
    ref = load(reference)
    patches = stored or [ref.crop((x - radius, y - radius, x + radius + 1, y + radius + 1)) for x, y in anchors]
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

    if stored and not check(reference):
        raise ValueError("camera_view_differs_from_profile")
    return check


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


def find_crossings(track, gates, check_camera):
    events, uncertain = defaultdict(list), defaultdict(set)
    for a, b in zip(track, track[1:]):
        if a is None or b is None:
            continue
        for label, gate in gates.items():
            when = crossing(a, b, gate)
            if when is None:
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
            events[label].append({
                "seconds": when, "bracket": [a["time"], b["time"]],
                "frames": [a["file"], b["file"]],
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


def fitted_crossing(track, gate, event):
    """Least-squares crossing time from the observations around the gate (not only the bracketing pair)."""
    axis = gate["axis"]
    middle = sum(event["bracket"]) / 2
    rows = [r for r in track if r is not None and abs(r["time"] - middle) <= FIT_HALF_WINDOW_SECONDS]
    if len(rows) < 4:
        return None
    mt = sum(r["time"] for r in rows) / len(rows)
    mv = sum(r[axis] for r in rows) / len(rows)
    var = sum((r["time"] - mt) ** 2 for r in rows)
    slope = sum((r["time"] - mt) * (r[axis] - mv) for r in rows) / var
    if slope * gate["direction"] <= 0:
        return None
    residual = math.sqrt(sum((r[axis] - (mv + slope * (r["time"] - mt))) ** 2 for r in rows) / (len(rows) - 2))
    return {"seconds": mt + (gate["value"] - mv) / slope, "points": len(rows),
            "residual_pixels": round(residual, 2), "pixels_per_second": round(abs(slope), 1)}


def track_break(track, start, end, max_step):
    """Reason the bow track is not continuous between two times, or None."""
    inside = [i for i, r in enumerate(track) if r is not None and start <= r["time"] <= end]
    if not inside:
        return "bow_track_not_continuous"
    if any(r is None for r in track[inside[0]:inside[-1] + 1]):
        return "bow_track_has_unusable_observation"
    rows = [track[i] for i in inside]
    for a, b in zip(rows, rows[1:]):
        gap = b["time"] - a["time"]
        if gap > MAX_GAP_SECONDS:
            return "bow_track_not_continuous"
        if math.dist((a["x"], a["y"]), (b["x"], b["y"])) > max_step * max(gap, 1 / 60) / 0.1:
            return "bow_jump_too_large"
    return None


def section_times(events, gates, frame_sequence, check_camera, track=(), max_step=math.inf, blocked=None):
    sections = {}
    for name, (start, end) in SEGMENTS.items():
        if start not in gates or end not in gates:
            sections[name] = {"status": "gate_not_configured"}
            continue
        if blocked:
            sections[name] = {"status": blocked}
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
        broken = track_break(track, a["bracket"][0], b["bracket"][1], max_step)
        if broken:
            sections[name] = {"status": broken}
            continue
        try:
            stable = all(check_camera(name) for _, name in span)
        except ValueError as error:
            sections[name] = {"status": str(error)}
            continue
        if not stable:
            sections[name] = {"status": "camera_landmark_changed_in_section"}
            continue
        sections[name] = {"status": "reference",
                          "video_seconds": round(b["seconds"] - a["seconds"], 3),
                          "bracket_range_video_seconds": [round(earliest, 3), round(latest, 3)]}
        fa, fb = fitted_crossing(track, gates[start], a), fitted_crossing(track, gates[end], b)
        if fa and fb:
            sections[name].update(
                fit_video_seconds=round(fb["seconds"] - fa["seconds"], 3),
                fit_minus_bracket_seconds=round(fb["seconds"] - fa["seconds"] - (b["seconds"] - a["seconds"]), 3),
                fit_residual_pixels=max(fa["residual_pixels"], fb["residual_pixels"]))
    return sections


def shared_tracks(tracks):
    """Boat numbers whose bow annotations coincide on two or more frames (copied or mixed-up tracks)."""
    points = {}
    for boat, rows in tracks.items():
        points[boat] = {r["file"]: (r["x"], r["y"]) for r in rows if r is not None}
    shared = set()
    boats = sorted(points)
    for i, one in enumerate(boats):
        for other in boats[i + 1:]:
            same = sum(1 for f, p in points[one].items()
                       if f in points[other] and math.dist(p, points[other][f]) <= SHARED_TRACK_PIXELS)
            if same >= 2:
                shared |= {one, other}
    return shared


def measure(manifest, profile, review, directory, *, manifest_sha256):
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
    stored = anchor_patches(profile, anchors)
    check_camera = camera_check(frame_loader(directory, size, frames), reference, anchors, stored)
    frame_sequence = sorted((row["time"], name) for name, row in frames.items())
    max_step = profile.get("max_bow_step_px", MAX_STEP_FRACTION * max(size))
    if not finite(max_step) or max_step <= 0:
        raise ValueError("invalid_profile_max_bow_step")
    parsed, errors = {}, {}
    for boat in range(1, 7):
        try:
            parsed[boat] = read_track(tracks.get(str(boat), []), size, frames, window)
        except ValueError as error:
            parsed[boat], errors[boat] = [], str(error)
    shared = shared_tracks(parsed)
    boats = []
    for boat in range(1, 7):
        blocked = errors.get(boat) or ("bow_track_shared_with_another_boat" if boat in shared else None)
        if blocked:
            events, missing = {}, {k: [blocked] for k in gates}
        else:
            events, missing = find_crossings(parsed[boat], gates, check_camera)
        boats.append({"boat": boat, "crossings": events, "missing_crossings": missing,
                      "segments": section_times(events, gates, frame_sequence, check_camera,
                                                parsed[boat], max_step, blocked)})
    return {
        "schema": 1, "date": day, "venue": venue, "race": race, "lap": profile["lap"],
        "profile_id": profile["id"], "manifest_sha256": manifest_sha256,
        "profile_sha256": digest(profile), "review_sha256": digest(review),
        "time_basis": "browser_presented_frame_media_time",
        "full_backstretch_verified": False, "real_time_scale_verified": False,
        "measurement_mode": "reviewed_or_imported_bow_track",
        "camera_layout_check": "profile_reference_patches" if stored else "human_review_only",
        "publication_ready": False, "rating_eligible": False,
        "boats": boats,
        "coverage": {name: sum(b["segments"][name]["status"] == "reference" for b in boats)
                     for name in SEGMENTS},
    }
