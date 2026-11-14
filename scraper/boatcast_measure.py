"""Section times from BOATCAST exhibition replays (fixed cameras), as numbers only.

The capture (tools/boatcast/measure-capture.mjs) reads, on every frame of a fixed-camera shot, the
pixels along a measuring path (a centre line plus a perpendicular band). Here those numbers become
a space-time image: position along the path x time. Every boat is one curve in it: the moment the
newest bright wake reaches each point of the path. The front of a boat is the first sudden brightening,
so the curve is its bow. Spray and old wakes sit behind or stay put; they do not move the front.

For each boat a smooth curve t(s) is fitted to hundreds of path points (one per column), and the
section time is t(B) - t(A) between two fixed points of the path. No frame is tracked by itself.
A boat is left unmeasured when its curve is short, noisy, does not cover both gates, or (straight)
runs on another line than the others, since time across the image depends on the distance to the camera.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

FPS_MAX_GAP = .05
JUMP_LAGS = (4, 12)           # frames: a point brightens compared with 4..12 frames before
JUMP_THRESHOLD = 80.0         # grey levels (0..255)
MOTION_THRESHOLD = 40.0       # grey levels changed within 2 frames
MOTION_MIN_COUNT = 4          # band samples moving at once
MAX_RESIDUAL_FRAMES = 1.6     # spread of the curve around its fit
MIN_COVER = .5                # share of path columns between the gates that carry the curve
PLATE_COLOURS = {1: (235, 235, 235), 2: (25, 25, 25), 3: (225, 40, 60), 4: (30, 120, 220),
                 5: (240, 210, 30), 6: (40, 170, 70)}


def path_geometry(poly, step, half, ostep):
    poly = np.asarray(poly, float)
    seg = np.diff(poly, axis=0)
    length = np.hypot(*seg.T)
    total = float(length.sum())
    n_s = len(np.arange(0, total, step))
    n_o = len(np.arange(-half, half + 1e-9, ostep))
    return n_s, n_o, total


def load_shot(capture_dir, name):
    manifest = json.loads((Path(capture_dir) / "manifest.json").read_text(encoding="utf-8"))
    shot = manifest["shots"][name]
    times = np.asarray(shot["times"], float)
    n = shot["nS"] * shot["nO"] + shot["nPlate"]
    raw = np.fromfile(Path(capture_dir) / f"{name}.bin", np.uint8)
    if raw.size != len(times) * n * 3:
        raise ValueError("sample_size_mismatch")
    rgb = raw.reshape(len(times), n, 3)
    band = rgb[:, :shot["nS"] * shot["nO"]].astype(np.float32).mean(-1).reshape(len(times), shot["nS"], shot["nO"])
    plate = rgb[:, shot["nS"] * shot["nO"]:].astype(np.float32)
    return manifest, shot, times, band, plate


def band_rgb(capture_dir, name):
    manifest = json.loads((Path(capture_dir) / "manifest.json").read_text(encoding="utf-8"))
    shot = manifest["shots"][name]
    n = shot["nS"] * shot["nO"] + shot["nPlate"]
    rgb = np.fromfile(Path(capture_dir) / f"{name}.bin", np.uint8).reshape(len(shot["times"]), n, 3)
    return rgb[:, :shot["nS"] * shot["nO"]].reshape(len(shot["times"]), shot["nS"], shot["nO"], 3)


def pass_hue(rgb, band, s, t, *, min_pixels=20):
    """Median hue (degrees) of the saturated pixels that move with this boat: the rider's colour.
    None when too few coloured pixels (white and black riders, or spray hiding the colour)."""
    T = len(band)
    fs = np.clip(np.round(t).astype(int), 2, T - 1)
    si = s.astype(int)
    moving = np.abs(band[fs, si] - band[fs - 2, si]) > MOTION_THRESHOLD
    px = rgb[fs, si][moving].astype(np.float32) / 255
    if not len(px):
        return None, 0
    mx, mn = px.max(1), px.min(1)
    col = px[((mx - mn) / (mx + 1e-6) > .45) & (mx > .3)]
    if len(col) < min_pixels:
        return None, int(len(col))
    r, g, b = col.T
    mx, mn = col.max(1), col.min(1)
    d = mx - mn + 1e-9
    h = np.where(mx == r, ((g - b) / d) % 6, np.where(mx == g, (b - r) / d + 2, (r - g) / d + 4)) * 60
    # circular median around the mean direction
    ang = np.deg2rad(h)
    centre = np.arctan2(np.sin(ang).mean(), np.cos(ang).mean())
    rel = (np.rad2deg(ang - centre) + 180) % 360 - 180
    return round(float((np.rad2deg(centre) + np.median(rel)) % 360), 1), int(len(col))


def jump_map(band, lags=JUMP_LAGS):
    """Front feature: brightest point across the band per path column, minus its brightest value a few
    frames earlier. Works where boats pass one at a time on a clean line (side-on straight)."""
    bright = band.max(2)
    prev = np.full_like(bright, -1e9)
    for k in range(lags[0], lags[1] + 1):
        prev[k:] = np.maximum(prev[k:], bright[:-k])
    jump = bright - prev
    jump[:lags[1]] = 0
    return jump, band.argmax(2)


def motion_map(band, lag=2, threshold=MOTION_THRESHOLD):
    """Motion feature: how many samples across the band changed strongly within `lag` frames.
    The moving boat (and the spray it throws) changes fast; old wakes drift slowly and drop out.
    Used in turns, where the wakes of every boat overlap and a "first brightening" is ambiguous."""
    diff = np.zeros(band.shape, np.float32)
    diff[lag:] = np.abs(band[lag:] - band[:-lag])
    moving = diff > threshold
    count = moving.sum(2).astype(np.float32)
    # where across the band the motion sits (mean offset index of moving samples)
    idx = np.arange(band.shape[2], dtype=np.float32)
    lateral = np.where(count > 0, (moving * idx).sum(2) / np.maximum(count, 1), (band.shape[2] - 1) / 2)
    return count, lateral


def ridges(count, min_count=MOTION_MIN_COUNT, half=4):
    """(column, sub-frame) at local maxima in time of the motion count: the centre of mass of the
    moving boat within +-half frames. A flat top counts once, at its middle."""
    sm = count.copy()
    sm[1:-1] = (count[:-2] + 2 * count[1:-1] + count[2:]) / 4
    peak = np.zeros(count.shape, bool)
    peak[1:-1] = (sm[1:-1] >= sm[:-2]) & (sm[1:-1] >= sm[2:]) & (sm[1:-1] >= min_count)
    T = len(count)
    out = []
    for si in range(count.shape[1]):
        f = np.nonzero(peak[:, si])[0]
        if not len(f):
            continue
        groups = np.split(f, np.nonzero(np.diff(f) > 1)[0] + 1)
        for g in groups:
            fi = int(round(g.mean()))
            lo, hi = max(0, fi - half), min(T, fi + half + 1)
            w = count[lo:hi, si]
            out.append((si, float((np.arange(lo, hi) * w).sum() / w.sum())))
    return np.array(out) if out else np.zeros((0, 2))


def onsets(jump, threshold=JUMP_THRESHOLD):
    """(column, sub-frame) where the jump first rises over the threshold."""
    above = jump > threshold
    f, s = np.nonzero(above[1:] & ~above[:-1])
    f = f + 1
    y0, y1 = jump[f - 1, s], jump[f, s]
    return np.column_stack([s, f - 1 + (threshold - y0) / (y1 - y0)])


def _fit(s, t, deg, rounds=5, k=3.0):
    keep = np.ones(len(s), bool)
    coef, spread = None, None
    for _ in range(rounds):
        if keep.sum() <= deg + 2:
            return None, keep, math.inf
        coef = np.polyfit(s[keep], t[keep], deg)
        r = t - np.polyval(coef, s)
        spread = 1.4826 * float(np.median(np.abs(r[keep]))) + 1e-6
        new = np.abs(r) < max(k * spread, .5)
        if (new == keep).all():
            break
        keep = new
    return coef, keep, spread


def curves(ev, n_s, *, seed=(.4, .6), tol=3.0, min_gap=30):
    """Group onsets into one curve per boat: bunch them in the seed columns, then grow along the path."""
    if not len(ev):
        return []
    s, t = ev[:, 0], ev[:, 1]
    lo, hi = int(seed[0] * n_s), int(seed[1] * n_s)
    sel = (s >= lo) & (s <= hi)
    ts = np.sort(t[sel])
    groups, cur = [], []
    for v in ts:
        if cur and v - cur[-1] > min_gap:
            groups.append(cur)
            cur = []
        cur.append(v)
    if cur:
        groups.append(cur)
    out = []
    for g in groups:
        if len(g) < .3 * (hi - lo):
            continue
        m = sel & (t >= min(g) - 1) & (t <= max(g) + 1)
        for it in range(10):
            deg = 1 if it < 2 or m.sum() < 40 else 2
            coef = np.polyfit(s[m], t[m], deg)
            pred = np.polyval(coef, s)
            near = np.nonzero(np.abs(t - pred) < tol)[0]
            best = {}
            for i in near:
                j = best.get(s[i])
                if j is None or abs(t[i] - pred[i]) < abs(t[j] - pred[j]):
                    best[s[i]] = i
            m2 = np.zeros(len(s), bool)
            m2[list(best.values())] = True
            if (m2 == m).all():
                break
            m = m2
        out.append((s[m], t[m]))
    # the same boat must not be found twice
    out.sort(key=lambda c: np.median(c[1]))
    uniq = []
    for c in out:
        if uniq and abs(np.median(c[1]) - np.median(uniq[-1][1])) < min_gap / 2:
            continue
        uniq.append(c)
    return uniq


def all_passes(ev, n_s, *, min_gap=30):
    """Every boat that shows up, including one only partly inside the shot (it passed before the shot
    began, or the shot ended first). Seeds in three parts of the path; the same boat found twice is
    kept once (the longer curve). Partial boats keep the order right; they are not measured."""
    found = []
    for seed in ((.4, .6), (.08, .28), (.72, .92)):
        for s, t in curves(ev, n_s, seed=seed, min_gap=min_gap):
            if len(s) < 12:
                continue
            found.append((s, t))
    # time of each pass projected to the middle of the path, to compare passes found from different seeds
    def mid_time(c):
        s, t = c
        coef = np.polyfit(s, t, 1)
        return float(np.polyval(coef, n_s / 2))
    found.sort(key=lambda c: -len(c[0]))
    kept = []
    for c in found:
        m = mid_time(c)
        if all(abs(m - mid_time(k)) > min_gap / 2 for k in kept):
            kept.append(c)
    kept.sort(key=mid_time)
    return kept


def frame_time(times, f):
    return float(np.interp(f, np.arange(len(times)), times))


def plate_boat(plate_rgb):
    """Boat number from the colour of the number disc on the name plate (median of the ring points)."""
    c = np.median(plate_rgb.reshape(-1, 3), 0)
    best = min(PLATE_COLOURS, key=lambda b: float(np.sum((c - PLATE_COLOURS[b]) ** 2)))
    return best, float(np.sqrt(np.sum((c - PLATE_COLOURS[best]) ** 2)))


def measure_shot(capture_dir, name, cfg):
    """One fixed-camera shot -> one record per curve (in the order the boats came)."""
    manifest, shot, times, band, plate = load_shot(capture_dir, name)
    if cfg.get("feature", "front") == "motion":
        count, lateral = motion_map(band)
        ev = ridges(count)
    else:
        jump, lateral = jump_map(band)
        ev = onsets(jump, cfg.get("threshold", JUMP_THRESHOLD))
    found = all_passes(ev, shot["nS"])
    gate_a, gate_b = (g / cfg["step"] for g in cfg["gates"]["main"])
    rgb = band_rgb(capture_dir, name) if cfg.get("colours") else None
    out = []
    for i, (s, t) in enumerate(found):
        rec = {"order": i + 1, "points": int(len(s)), "reasons": []}
        if rgb is not None:
            rec["hue"], rec["hue_pixels"] = pass_hue(rgb, band, s, t)
        coef, keep, spread = _fit(s.astype(float), t, 2)
        if coef is None:
            rec["reasons"].append("fit_failed")
            out.append(rec)
            continue
        ks = s[keep]
        cover = ((ks >= gate_a) & (ks <= gate_b)).sum() / max(1, gate_b - gate_a)
        fa, fb = np.polyval(coef, gate_a), np.polyval(coef, gate_b)
        rec.update({
            "residual_frames": round(spread, 3), "cover": round(float(cover), 3),
            "t_a": round(frame_time(times, fa), 4), "t_b": round(frame_time(times, fb), 4),
            "seconds": round(frame_time(times, fb) - frame_time(times, fa), 4),
            "span": [int(ks.min()), int(ks.max())],
        })
        # speed along the path at both gates (path pixels per second), from the slope of the fit
        dt = np.polyder(coef)
        fps = 1 / float(np.median(np.diff(times))) if len(times) > 1 else 30.0
        for key, g in (("v_a", gate_a), ("v_b", gate_b)):
            slope = float(np.polyval(dt, g))
            rec[key] = round(cfg["step"] * fps / slope, 1) if slope > 0 else None
        # lateral line: where across the band the bright front sits, near the middle of the path
        mid = (ks > .3 * shot["nS"]) & (ks < .7 * shot["nS"])
        frames = np.clip(np.round(t[keep][mid]).astype(int) + 2, 0, len(times) - 1)
        if len(frames):
            off = (lateral[frames, ks[mid].astype(int)] - (shot["nO"] - 1) / 2) * cfg["ostep"]
            o = np.sort(off)
            k = len(o) // 4
            rec["line_px"] = round(float(o[k:len(o) - k].mean() if len(o) >= 4 else np.median(o)), 2)
        if plate.size:
            fm = int(round((fa + fb) / 2))
            w = slice(max(0, fm - 15), min(len(times), fm + 15))
            rec["plate"], rec["plate_distance"] = plate_boat(plate[w])
        if spread > MAX_RESIDUAL_FRAMES:
            rec["reasons"].append("noisy_curve")
        if ks.min() > gate_a + 3 or ks.max() < gate_b - 3:
            rec["reasons"].append("gates_not_covered")
        if cover < MIN_COVER:
            rec["reasons"].append("short_curve")
        if not fb > fa:
            rec["reasons"].append("wrong_direction")
        out.append(rec)
    info = {"frames": len(times), "skipped": shot.get("skipped"), "sizes": shot.get("sizes"),
            "window": shot.get("window"), "curves": len(found)}
    return out, info


def assign_boats(records, boats, *, use_plate=False):
    """Boat numbers for curves. Exhibition laps go in boat order, so the k-th curve is the k-th boat
    when every boat was found. With name plates, each curve must also show its own plate colour."""
    n = len(records)
    if n != len(boats):
        for r in records:
            r["reasons"].append("curve_count_%d_of_%d" % (n, len(boats)))
        return records
    for r, b in zip(records, boats):
        r["boat"] = b
        if use_plate and "plate" in r and r["plate"] != b:
            r["reasons"].append("plate_mismatch")
    return records


def colour_of(hue, colours):
    if hue is None:
        return None
    for boat, (lo, hi) in colours.items():
        if (lo <= hue <= hi) if lo <= hi else (hue >= lo or hue <= hi):
            return int(boat)
    return None


def assign_by_colour(records, boats, colours):
    """Boat numbers from rider colours. Coloured passes are anchors (a colour seen twice in a row is one
    boat seen twice: the longer curve stays). Between two anchors the uncoloured passes take the boats in
    between, in order, but only when their number fits exactly; complete curves count before fragments.
    Anything that does not fit stays unassigned (never guessed)."""
    for r in records:
        # only complete curves anchor: a fragment at the shot's edge may be another object on the water
        r["colour"] = colour_of(r.get("hue"), colours) if not r["reasons"] else None
    # boat 6 (green) can look blue: a "4" after the "5" is 6
    seen5 = False
    for r in records:
        if r["colour"] == 5:
            seen5 = True
        elif r["colour"] == 4 and seen5:
            r["colour"] = 6
    # drop repeated anchors (same colour twice in a row): keep the one with more points
    anchors = [i for i, r in enumerate(records) if r["colour"] in boats]
    for a, b in zip(anchors, anchors[1:]):
        if records[a]["colour"] == records[b]["colour"]:
            weaker = a if records[a]["points"] < records[b]["points"] else b
            records[weaker]["colour"] = None
            records[weaker]["reasons"].append("duplicate_pass")
    anchors = [i for i, r in enumerate(records) if r["colour"] in boats]
    if [records[i]["colour"] for i in anchors] != sorted(records[i]["colour"] for i in anchors):
        for r in records:
            r["reasons"].append("colour_order_conflict")
        return records
    if not anchors:
        for r in records:
            r["reasons"].append("no_colour_anchor")
        return records
    for i in anchors:
        records[i]["boat"] = records[i]["colour"]
    lo_boat = [b for b in boats if b < records[anchors[0]]["colour"]]
    bounds = [(None, anchors[0], lo_boat)]
    for a, b in zip(anchors, anchors[1:]):
        bounds.append((a, b, [x for x in boats if records[a]["colour"] < x < records[b]["colour"]]))
    bounds.append((anchors[-1], None, [x for x in boats if x > records[anchors[-1]]["colour"]]))
    for a, b, need in bounds:
        idx = [i for i in range(len(records)) if (a is None or i > a) and (b is None or i < b)
               and "duplicate_pass" not in records[i]["reasons"]]
        if not need:
            for i in idx:
                records[i]["reasons"].append("extra_pass")
            continue
        complete = [i for i in idx if not records[i]["reasons"]]
        if a is None:            # before the first anchor: the boats just before it (earlier passes are extras)
            pick = complete[-len(need):] if len(complete) >= len(need) else None
        elif b is None:          # after the last anchor: the boats just after it
            pick = complete[:len(need)] if len(complete) >= len(need) else None
        else:
            pick = complete if len(complete) == len(need) else None
        if pick is None or len(pick) != len(need):
            for i in idx:
                records[i]["reasons"].append("identity_unclear")
            continue
        for i, boat in zip(pick, need):
            records[i]["boat"] = boat
        for i in idx:
            if i not in pick:
                records[i]["reasons"].append("extra_pass")
    return records


def line_correct(records, slope):
    """Side-on camera: a boat nearer the camera crosses the image faster. Bring every time to the
    common line (offset 0) with the venue's slope (seconds per pixel of offset), estimated inside races."""
    for r in records:
        if "seconds" in r and r.get("line_px") is not None:
            r["seconds_raw"] = r["seconds"]
            r["seconds"] = round(r["seconds"] - slope * r["line_px"], 4)
    return records


def line_check(records, max_offset):
    lines = [r["line_px"] for r in records if "line_px" in r and not r["reasons"]]
    if len(lines) < 2:
        return records
    centre = float(np.median(lines))
    for r in records:
        if "line_px" in r and abs(r["line_px"] - centre) > max_offset:
            r["reasons"].append("different_line")
    return records
