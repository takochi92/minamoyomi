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
    found = curves(ev, shot["nS"])
    gate_a, gate_b = (g / cfg["step"] for g in cfg["gates"]["main"])
    out = []
    for i, (s, t) in enumerate(found):
        rec = {"order": i + 1, "points": int(len(s)), "reasons": []}
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
            rec["line_px"] = round(float(np.median(off)), 1)
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


def line_check(records, max_offset):
    lines = [r["line_px"] for r in records if "line_px" in r and not r["reasons"]]
    if len(lines) < 2:
        return records
    centre = float(np.median(lines))
    for r in records:
        if "line_px" in r and abs(r["line_px"] - centre) > max_offset:
            r["reasons"].append("different_line")
    return records
