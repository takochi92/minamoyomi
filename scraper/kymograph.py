"""Timing a boat from a space-time image instead of following one feature frame by frame.

For a fixed camera and a boat that moves along one image axis, every frame is reduced to one row:
how much each column differs from the empty water, inside the band of rows the boat travels in.
Stacking the rows gives an image with position across and time down, in which the boat is a slanted
streak. Its front edge is read at each time and a robust line through those points gives the time
the front passes a gate. Nothing has to be matched between neighbouring frames, so a frame lost to
spray only removes one point, and no colour is used.

The same physical part of the boat must pass both gates. That is checked instead of assumed: the
front, the middle and the back of the streak must give the same section time, and the streak's
width must change smoothly. A run that fails a check is reported as missing with a reason.
"""
from __future__ import annotations

import math
from statistics import median

import numpy as np

from .independent_metrics import robust_crossing

EDGE_FRACTION = .35            # the edge is where the row first reaches this share of its own peak
MIN_PEAK = 12.0                # rows with a weaker peak hold no boat (grey levels of difference)
MIN_RUN = 3                    # columns in a row that must stay above the threshold to count as the boat
FIT_HALF_WIDTH = 75.0          # pixels on each side of a gate used for the line
MAX_POINT_DISAGREEMENT = .02   # seconds: front, middle and back must agree on the section time
MAX_WIDTH_JUMP = .45           # relative change of the streak's width between usable neighbours


def build(frames, band, background, *, spray_guard=False):
    """Space-time image from grey frames.

    frames      list of (media_time, HxW uint8 array) of one resolution
    band        (top, bottom) rows the boats travel in
    background  HxW array of the empty water (for example the median of many frames)
    spray_guard keep only pixels darker than the water: spray is brighter than the water it covers,
                the hull and the rider's suit are usually darker
    Returns (times, image) with one row per frame.
    """
    top, bottom = band
    base = background[top:bottom].astype(np.int16)
    times, rows = [], []
    for t, frame in sorted(frames, key=lambda f: f[0]):
        if frame.shape != background.shape:
            raise ValueError("frame_resolution_changed")      # a stream that fell back to another quality
        diff = frame[top:bottom].astype(np.int16) - base
        diff = np.clip(-diff, 0, None) if spray_guard else np.abs(diff)
        times.append(float(t))
        rows.append(diff.max(axis=0).astype(np.float32))
    return np.array(times), np.vstack(rows)


def edges(image, direction, *, fraction=EDGE_FRACTION, min_peak=MIN_PEAK, min_run=MIN_RUN):
    """Front, middle and back of each streak in every row (a list), or None where the row holds no boat.

    direction is -1 for a boat moving toward smaller x (left) and 1 toward larger x.
    """
    out = []
    for row in image:
        peak = float(row.max())
        if peak < min_peak:
            out.append(None)
            continue
        above = row >= fraction * peak
        runs, start = [], None
        for x, on in enumerate(above):
            if on and start is None:
                start = x
            elif not on and start is not None:
                runs.append((start, x - 1))
                start = None
        if start is not None:
            runs.append((start, len(above) - 1))
        runs = [r for r in runs if r[1] - r[0] + 1 >= min_run]
        if not runs:
            out.append(None)
            continue
        weight = lambda r: float(row[r[0]:r[1] + 1].sum())
        heaviest = max(weight(r) for r in runs)
        found = []
        for left, right in runs:
            if weight((left, right)) < .25 * heaviest:
                continue                                   # small runs are spray or reflections
            front, back = (left, right) if direction < 0 else (right, left)
            found.append({"front": float(front), "back": float(back), "middle": (left + right) / 2,
                          "width": float(right - left + 1), "peak": peak, "runs": len(runs)})
        out.append(found)
    return out


def passes(times, rows, direction, *, max_gap=.25, max_step=45.0, min_frames=6, min_travel=50.0):
    """Assign the streaks of every row to boats.

    Two boats can be in the band at once (one leaving, the next arriving), so a row may hold more than
    one streak. A streak continues the boat whose front it extends in the direction of travel; one that
    fits no boat starts another. Short or stationary groups (spray, reflections) are dropped.
    """
    groups = []
    for t, found in zip(times, rows):
        taken = set()
        for run in sorted(found or [], key=lambda r: -r["width"]):
            best = None
            for i, group in enumerate(groups):
                last_t, last = group[-1]
                step = (run["front"] - last["front"]) * direction
                if i in taken or not 0 < t - last_t <= max_gap or not -6 <= step <= max_step * max(1.0, (t - last_t) * 30):
                    continue
                if best is None or abs(step) < best[1]:
                    best = (i, abs(step))
            if best is None:
                groups.append([(float(t), run)])
                taken.add(len(groups) - 1)
            else:
                groups[best[0]].append((float(t), run))
                taken.add(best[0])
    kept = [g for g in groups if len(g) >= min_frames
            and abs(g[-1][1]["front"] - g[0][1]["front"]) >= min_travel]
    return sorted(kept, key=lambda g: g[0][0])


def gate_time(points, gate, direction, *, half_width=FIT_HALF_WIDTH):
    near = [(t, x) for t, x in points if abs(x - gate) <= half_width]
    return robust_crossing(near, gate, direction)


def measure_pass(group, gates, direction, *, frame_step=1 / 30):
    """Section time of one boat between two gates, with the reasons it may not be trusted.

    group   [(time, edge-row)] of one boat from `passes`
    gates   (first, second) positions along the axis, in the order the boat meets them
    """
    result = {"status": "missing", "reasons": [], "frames": len(group)}
    fits = {}
    for point in ("front", "middle", "back"):
        pts = [(t, row[point]) for t, row in group]
        a, b = gate_time(pts, gates[0], direction), gate_time(pts, gates[1], direction)
        fits[point] = (a, b)
    front = fits["front"]
    if front[0] is None:
        result["reasons"].append("first_gate_not_fitted")
    if front[1] is None:
        result["reasons"].append("second_gate_not_fitted")
    if result["reasons"]:
        return result
    start, end = front[0]["seconds"], front[1]["seconds"]
    inside = [(t, row) for t, row in group if start - 1e-9 <= t <= end + 1e-9]
    expected = max(1, round((end - start) / frame_step))
    result.update(first=round(start, 4), second=round(end, 4), seconds=round(end - start, 4),
                  coverage=round(min(1.0, len(inside) / expected), 2),
                  residual_pixels=max(front[0]["residual_pixels"], front[1]["residual_pixels"]),
                  rejected=front[0]["rejected"] + front[1]["rejected"])
    sections = {k: round(b["seconds"] - a["seconds"], 4) for k, (a, b) in fits.items() if a and b}
    result["by_point"] = sections
    if len(sections) < 2:
        result["reasons"].append("same_point_not_verified")
    elif max(sections.values()) - min(sections.values()) > MAX_POINT_DISAGREEMENT:
        result["reasons"].append("boat_points_disagree")        # spray reshaped the streak, or the boat turned
    widths = [row["width"] for _, row in inside]
    if len(widths) >= 6:
        smooth = [median(widths[max(0, i - 2):i + 3]) for i in range(len(widths))]
        if any(abs(a - b) / max(a, b) > MAX_WIDTH_JUMP for a, b in zip(smooth, smooth[1:])):
            result["reasons"].append("streak_width_jump")       # another boat merged in, or the track moved
    if result["coverage"] < .5:
        result["reasons"].append("too_few_frames_between_gates")
    if not result["reasons"]:
        result["status"] = "measured"
    return result


def measure(times, image, gates, direction, **kwargs):
    """All boats in a space-time image, in the order they pass."""
    rows = edges(image, direction, **{k: v for k, v in kwargs.items() if k in ("fraction", "min_peak", "min_run")})
    return [measure_pass(group, gates, direction) for group in passes(times, rows, direction)]


def assisted(times, clicks, gates, direction):
    """Section time from a few points a person clicked on the streak's front edge in the image.

    clicks  [(time, position)] along one boat's front edge, at least three near each gate.
    For building verification data and for venues the automatic edge cannot read yet.
    """
    a, b = (robust_crossing([(t, x) for t, x in clicks if abs(x - g) <= FIT_HALF_WIDTH], g, direction,
                            min_points=3) for g in gates)
    if a is None or b is None:
        return {"status": "missing", "reasons": ["clicks_do_not_fit_a_line"]}
    return {"status": "assisted", "first": round(a["seconds"], 4), "second": round(b["seconds"], 4),
            "seconds": round(b["seconds"] - a["seconds"], 4), "clicks": len(clicks),
            "residual_pixels": max(a["residual_pixels"], b["residual_pixels"]), "reasons": []}


# ------------------------------------------------------------------ velocity alignment
def align(times, image, speeds, direction, *, accelerations=(0.0,), window=None, columns=None):
    """Speed of the boat from the whole streak, without reading an edge.

    Wake and patterns on the water stay roughly where they are, while the boat moves at a steady speed.
    Each row is shifted back by the distance a boat at a trial speed would have moved, and the rows are
    averaged. At the right speed the boat lines up into one sharp profile and everything that does not
    move with it is smeared out. The trial that gives the sharpest profile is the boat's motion:

        position(t) = position(reference time) + direction * (speed * dt + acceleration * dt^2 / 2)

    speeds        trial speeds in pixels per second (positive numbers)
    accelerations trial accelerations in pixels per second squared
    window        (start, end) media time of one boat's pass; columns (left, right) to use
    Returns None when no trial stands out. `contrast` compares the best trial with the median trial;
    `split_speed_gap` is the difference between the speeds found from odd and even rows alone.
    """
    times = np.asarray(times, dtype=float)
    keep = np.ones(len(times), bool) if window is None else (times >= window[0]) & (times <= window[1])
    left, right = columns or (0, image.shape[1])
    rows, when = image[keep][:, left:right].astype(np.float32), times[keep]
    if len(when) < 8 or rows.shape[1] < 20:
        return None
    reference = float(when[len(when) // 2])
    grid = np.arange(rows.shape[1], dtype=np.float32)

    def stack(subset, speed, acceleration):
        total = np.zeros(rows.shape[1], dtype=np.float32)
        count = np.zeros(rows.shape[1], dtype=np.float32)
        for row, t in zip(rows[subset], when[subset]):
            dt = t - reference
            shift = direction * (speed * dt + .5 * acceleration * dt * dt)
            source = grid + shift                              # where this column sits in the row at time t
            inside = (source >= 0) & (source <= rows.shape[1] - 1)
            total[inside] += np.interp(source[inside], grid, row)
            count[inside] += 1
        valid = count >= max(4, .5 * subset.sum() if subset.dtype == bool else 4)
        profile = np.where(valid, total / np.maximum(count, 1), 0.0)
        # Sharpness: a boat that lines up has steep sides; smeared wake is flat
        return profile, float((np.diff(profile) ** 2).sum() / max(1, valid.sum()))

    def best(subset):
        scores = [(stack(subset, v, a)[1], v, a) for a in accelerations for v in speeds]
        return max(scores), scores

    everything = np.ones(len(when), bool)
    (score, speed, acceleration), scores = best(everything)
    floor = float(np.median([s for s, *_ in scores]))
    if floor <= 0 or score <= 0:
        return None
    coarse = speed
    fine = max(((stack(everything, v, acceleration)[1], float(v)) for v in np.arange(speed - 2, speed + 2.01, .25)))
    score, speed = max((score, float(speed)), fine)            # refine between the trial speeds
    odd = np.arange(len(when)) % 2 == 1
    gap = abs(best(odd)[0][1] - best(~odd)[0][1])
    profile, _ = stack(everything, speed, acceleration)
    peak = float(profile.max())
    above = np.where(profile >= EDGE_FRACTION * peak)[0]
    if peak <= 0 or len(above) == 0:
        return None
    centre = float((profile[above] * above).sum() / profile[above].sum()) + left
    return {"speed": float(speed), "acceleration": float(acceleration), "reference": reference,
            "position": centre, "contrast": round(score / floor, 2), "split_speed_gap": float(gap),
            "rows": int(len(when)), "at_search_limit": coarse in (speeds[0], speeds[-1])}


def section_from_alignment(fit, gates, direction):
    """Time the aligned boat needs between two positions, from the fitted motion."""
    def when(position):
        distance = (position - fit["position"]) * direction
        a, v = fit["acceleration"], fit["speed"]
        if abs(a) < 1e-9:
            return fit["reference"] + distance / v
        root = v * v + 2 * a * distance
        return None if root < 0 else fit["reference"] + (-v + math.sqrt(root)) / a
    first, second = when(gates[0]), when(gates[1])
    if first is None or second is None or second <= first:
        return None
    return {"first": round(first, 4), "second": round(second, 4), "seconds": round(second - first, 4)}


MIN_CONTRAST = 4.0             # sharpness of the best trial against the median trial
MAX_SPLIT_SPEED_GAP = 6.0      # pixels per second between odd-row and even-row estimates


def measure_speed(times, image, gates, direction, speeds, **kwargs):
    """Section time from the aligned streak, or the reasons it is not trusted."""
    fit = align(times, image, speeds, direction, **kwargs)
    if fit is None:
        return {"status": "missing", "reasons": ["no_moving_streak"]}
    reasons = []
    if fit["contrast"] < MIN_CONTRAST:
        reasons.append("streak_not_distinct")
    if fit["split_speed_gap"] > MAX_SPLIT_SPEED_GAP:
        reasons.append("speed_not_repeatable")
    if fit["at_search_limit"]:
        reasons.append("speed_at_search_limit")
    section = section_from_alignment(fit, gates, direction)
    if section is None:
        reasons.append("gates_not_reached_by_fit")
    return {"status": "missing" if reasons else "measured", "reasons": reasons, **fit, **(section or {})}


def to_png_bytes(image, *, scale=255.0):
    """The space-time image as a PNG a person can click on (private work area only)."""
    import io

    from PIL import Image
    peak = float(image.max()) or 1.0
    data = np.clip(image / peak * scale, 0, 255).astype(np.uint8)
    buffer = io.BytesIO()
    Image.fromarray(data, "L").save(buffer, format="PNG")
    return buffer.getvalue()


def is_finite(value):
    return isinstance(value, (int, float)) and math.isfinite(value)
