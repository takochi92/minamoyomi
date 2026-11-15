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
MOTION_MIN_COUNT = 8           # band samples moving at once (4 let rough water make false curves on 11/13)
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


def _layout(shot):
    """Sample layout of one shot: band, fine lateral grid, landmark strips, plate (in that order)."""
    nb = shot["nS"] * shot["nO"]
    nf = shot.get("nFineS", 0) * shot.get("nFineO", 0)
    nl = shot.get("nLand", 0)
    return nb, nf, nl, shot.get("nPlate", 0), shot.get("channels", 3)


def _raw(capture_dir, name):
    manifest = json.loads((Path(capture_dir) / "manifest.json").read_text(encoding="utf-8"))
    shot = manifest["shots"][name]
    nb, nf, nl, np_, ch = _layout(shot)
    raw = np.fromfile(Path(capture_dir) / f"{name}.bin", np.uint8)
    if raw.size != len(shot["times"]) * (nb + nf + nl + np_) * ch:
        raise ValueError("sample_size_mismatch")
    return manifest, shot, raw.reshape(len(shot["times"]), nb + nf + nl + np_, ch)


def load_shot(capture_dir, name):
    manifest, shot, rgb = _raw(capture_dir, name)
    times = np.asarray(shot["times"], float)
    nb, nf, nl, np_, ch = _layout(shot)
    band = rgb[:, :nb].astype(np.float32).mean(-1).reshape(len(times), shot["nS"], shot["nO"])
    plate = rgb[:, nb + nf + nl:].astype(np.float32)
    return manifest, shot, times, band, plate


def load_extra(capture_dir, name):
    """Fine lateral grid (frames x columns x offsets) and landmark strips (frames x samples), grey uint8."""
    manifest, shot, rgb = _raw(capture_dir, name)
    nb, nf, nl, np_, ch = _layout(shot)
    grey = rgb if ch == 1 else rgb.mean(-1, keepdims=True).astype(np.uint8)
    fine = grey[:, nb:nb + nf, 0].reshape(len(shot["times"]), shot.get("nFineS", 0), shot.get("nFineO", 0))
    land = grey[:, nb + nf:nb + nf + nl, 0]
    return shot, fine, land


def band_rgb(capture_dir, name):
    manifest, shot, rgb = _raw(capture_dir, name)
    nb = shot["nS"] * shot["nO"]
    return rgb[:, :nb].reshape(len(shot["times"]), shot["nS"], shot["nO"], rgb.shape[-1])


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
            if w.sum() > 0:
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
    ev = ev[np.isfinite(ev).all(1)] if len(ev) else ev
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
            if m.sum() <= deg + 1:
                break
            try:
                coef = np.polyfit(s[m], t[m], deg)
            except np.linalg.LinAlgError:
                m[:] = False
                break
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
        if m.sum() >= 3:
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


WAKE_LAGS = (20, 50)           # frames behind the bow: the wake lies on the water (spray has fallen back)
SPRAY_LAGS = (3, 8)            # frames behind the bow: spray thrown above the water
WAKE_MIN_CONTRAST = 15.0
WAKE_MIN_COLUMNS = 15


def _subpixel_peak(row):
    k = int(np.argmax(row))
    if 0 < k < len(row) - 1:
        a, b, c = row[k - 1], row[k], row[k + 1]
        den = a - 2 * b + c
        if den < 0:
            return k + .5 * (a - c) / den, float(b)
    return float(k), float(row[k])


def landmark_shift(shot, land):
    """Camera shake from the fixed landmarks (strips across sharp still edges): per frame vertical and
    sideways shift (px) against the shot median, plus where each edge sits (to compare camera framing
    between races)."""
    land = land.astype(np.float32)
    frames = len(land)
    pos, edges = 0, []
    for m in shot.get("landmarks") or []:
        n = (m["y"][1] - m["y"][0] + 1) if m["kind"] == "v" else (m["x"][1] - m["x"][0] + 1)
        prof = land[:, pos:pos + n]
        pos += n
        g = np.diff(prof, axis=1)
        med = np.median(g, 0)
        if len(med) < 10:
            continue
        k = int(np.argmax(np.abs(med[3:-3]))) + 3
        if abs(med[k]) < 20:
            continue
        # where the edge sits (median profile, sub-pixel), to compare framing between races
        a, b, c = np.abs(med[k - 1:k + 2])
        den = a - 2 * b + c
        at = k + (.5 * (a - c) / den if den < 0 else 0) + .5
        # per-frame shift against the median profile: gradient (Lucas-Kanade) step, iterated twice.
        # Unlike a peak fit it is not pulled toward whole pixels, whatever the sharpness of the edge.
        ref = np.median(prof, 0)
        lo, hi = max(1, k - 6), min(n - 1, k + 8)
        idx = np.arange(n, dtype=np.float32)
        shift = np.zeros(frames)
        for _ in range(3):
            moved = np.array([np.interp(idx[lo:hi] + d, idx, ref) for d in shift])
            grad = np.array([np.interp(idx[lo:hi] + d, idx, np.gradient(ref)) for d in shift])
            shift += ((prof[:, lo:hi] - moved) * grad).sum(1) / np.maximum((grad ** 2).sum(1), 1e-6)
        base = m["y"][0] if m["kind"] == "v" else m["x"][0]
        edges.append((m["kind"], m.get("x") if m["kind"] == "v" else m.get("y"), base + at, -shift))
    out = {"dy": np.zeros(frames), "dx": np.zeros(frames), "edges": []}
    for kind, key in (("v", "dy"), ("h", "dx")):
        e = [d - np.median(d) for k, _, _, d in edges if k == kind]
        if e:
            out[key] = np.median(np.array(e), 0)
    out["edges"] = [[k, at, round(float(p), 2)] for k, at, p, _ in edges]
    out["shake_sd"] = [round(float(out["dy"].std()), 3), round(float(out["dx"].std()), 3)]
    return out


def landmark_profiles(shot, land):
    """Median profile of every landmark strip over the shot (numbers only: one value per pixel of the strip)."""
    land = land.astype(np.float32)
    out, pos = [], 0
    for m in shot.get("landmarks") or []:
        n = (m["y"][1] - m["y"][0] + 1) if m["kind"] == "v" else (m["x"][1] - m["x"][0] + 1)
        out.append(np.median(land[:, pos:pos + n], 0))
        pos += n
    return out


def register(profiles, reference, max_shift=30):
    """How far this race's camera framing moved against the reference race (px; + = scene moved down /
    right), from the vertical strips across the far bank: normalised cross-correlation of the strip
    gradients over whole-pixel shifts, refined to sub-pixel, median over strips."""
    shifts = []
    for prof, ref in zip(profiles, reference):
        a, b = np.diff(np.asarray(prof, float)), np.diff(np.asarray(ref, float))
        best = []
        for d in range(-max_shift, max_shift + 1):
            x, y = (a[d:], b[:len(b) - d]) if d >= 0 else (a[:d], b[-d:])
            if len(x) < 20:
                best.append(-1)
                continue
            x, y = x - x.mean(), y - y.mean()
            best.append(float((x * y).sum() / (np.sqrt((x * x).sum() * (y * y).sum()) + 1e-9)))
        best = np.array(best)
        k = int(np.argmax(best))
        if best[k] < .5:
            continue
        frac = 0.0
        if 0 < k < len(best) - 1:
            u, v, w = best[k - 1:k + 2]
            den = u - 2 * v + w
            frac = .5 * (u - w) / den if den < 0 else 0.0
        shifts.append(k - max_shift + frac)
    if len(shifts) < 3:
        return None, len(shifts)
    return round(float(np.median(shifts)), 2), len(shifts)


def wake_line(fine, coef, n_band_s, step, fine_every, dy=None, lags=WAKE_LAGS, spray_lags=SPRAY_LAGS, span=None):
    """Where across the path the boat runs, at water level: the centre of its wake 20-50 frames after the
    bow passed each column (spray thrown above the water has fallen back by then), sub-pixel, for every
    fine column; then a straight line through the columns. Returns the offset at mid-path (px, + = away
    from the camera), its slope, the scatter, and how far the spray sat above the wake."""
    frames, n_cols, n_off = fine.shape
    half = (n_off - 1) / 2
    kern = np.array([1, 2, 3, 2, 1], np.float32) / 9
    s_px, off, spray = [], [], []
    for j in range(n_cols):
        sb = j * fine_every / step
        lo, hi = span if span is not None else (0, n_band_s - 1)
        if sb < lo or sb > hi:
            continue
        f0 = float(np.polyval(coef, sb))
        if f0 < 45 or f0 + lags[1] >= frames:
            continue
        col = fine[:, j].astype(np.float32)
        bg = col[int(f0) - 40:int(f0) - 12].mean(0)
        w = np.convolve(col[int(round(f0 + lags[0])):int(round(f0 + lags[1]))].mean(0) - bg, kern, "same")
        p, v = _subpixel_peak(w)
        if v < WAKE_MIN_CONTRAST:
            continue
        q, _ = _subpixel_peak(np.convolve(col[int(round(f0 + spray_lags[0])):int(round(f0 + spray_lags[1]))].mean(0) - bg, kern, "same"))
        shift = float(dy[int(round(f0 + sum(lags) / 2))]) if dy is not None else 0.0
        s_px.append(j * fine_every)
        off.append(p - half + shift)      # the band offset runs upward (away); a frame shifted down by dy
        spray.append(q - p)
    if len(s_px) < WAKE_MIN_COLUMNS:
        return None
    s_px, off, spray = map(np.asarray, (s_px, off, spray))
    mid = (n_band_s - 1) * step / 2
    keep = np.ones(len(s_px), bool)
    for _ in range(4):
        A = np.c_[np.ones(keep.sum()), s_px[keep] - mid]
        c, *_ = np.linalg.lstsq(A, off[keep], rcond=None)
        r = off - (c[0] + c[1] * (s_px - mid))
        keep = np.abs(r) < 3 * (np.median(np.abs(r[keep])) * 1.48 + .2)
    return {"line_px": round(float(c[0]), 3), "line_slope": round(float(c[1]), 5),
            "line_scatter": round(float(r[keep].std()), 3), "line_columns": int(keep.sum()),
            "spray_px": round(float(np.median(spray[keep])), 2)}


def measure_shot(capture_dir, name, cfg):
    """One fixed-camera shot -> one record per curve (in the order the boats came)."""
    manifest, shot, times, band, plate = load_shot(capture_dir, name)
    if cfg.get("frontHalf") and shot["nO"] * cfg["ostep"] > 2 * cfg["frontHalf"] + cfg["ostep"]:
        # the band is captured wide (for far lines); the bow is read inside frontHalf, away from the bank
        k = int((shot["nO"] - 1) / 2 - cfg["frontHalf"] / cfg["ostep"])
        band = band[:, :, k:shot["nO"] - k]
        shot = {**shot, "nO": band.shape[2]}
    if cfg.get("feature", "front") == "motion":
        count, lateral = motion_map(band)
        ev = ridges(count)
    else:
        jump, lateral = jump_map(band)
        ev = onsets(jump, cfg.get("threshold", JUMP_THRESHOLD))
    found = all_passes(ev, shot["nS"])
    gate_a, gate_b = (g / cfg["step"] for g in cfg["gates"]["main"])
    rgb = band_rgb(capture_dir, name) if cfg.get("colours") else None
    fine = land = shake = None
    if shot.get("nFineS"):
        _, fine, land = load_extra(capture_dir, name)
        shake = landmark_shift(shot, land) if shot.get("nLand") else None
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
        if fine is not None:
            # the bright front sits on the spray, above the water: use the wake on the water instead
            rec["line_front_px"] = rec.pop("line_px", None)
            wl = wake_line(fine, coef, shot["nS"], cfg["step"], (cfg.get("fine") or {}).get("every", 8),
                           shake["dy"] if shake else None, span=(int(ks.min()), int(ks.max())))
            if wl:
                rec.update(wl)
            else:
                rec["reasons"].append("no_wake_line")
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
    if shake:
        info["shake_sd"] = shake["shake_sd"]
        info["landmarks"] = shake["edges"]
        ref = (cfg.get("landmarkRef") or {}).get("profiles")
        if ref:
            # the camera is re-aimed between races: how far the scene moved against the reference race
            prof = landmark_profiles(shot, land)
            pairs = [(p, r) for p, r in zip(prof, ref) if r is not None]
            dy, used = register([p for p, _ in pairs], [r for _, r in pairs])
            info["framing_dy"], info["framing_strips"] = dy, used
            for rec in out:
                if dy is not None and rec.get("line_px") is not None:
                    # + = away from the camera; a scene moved up (dy < 0) lifts every boat's offset
                    rec["line_ref_px"] = round(rec["line_px"] + dy, 3)
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
    # the same colour on several passes: a boat cannot pass twice, so none of them anchors
    seen = {}
    for i, r in enumerate(records):
        if r["colour"] in boats:
            seen.setdefault(r["colour"], []).append(i)
    for colour, idx in seen.items():
        if len(idx) > 1:
            for i in idx:
                records[i]["colour"] = None
                records[i]["reasons"].append("colour_seen_twice")
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
        idx = [i for i in range(len(records)) if (a is None or i > a) and (b is None or i < b)]
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


LINE_FIT_MIN_BOATS = 4


def line_correct(records, slope):
    """Side-on camera: a boat nearer the camera crosses the image faster. Bring every time to the
    common line with the venue's slope (seconds per pixel of offset, a number), or with
    slope "per_race": fit log(time) on the line inside this race's boats and keep only what the
    line does not explain (the line effect, real or not, is removed exactly; needs 4 boats)."""
    if slope == "per_race":
        use = [r for r in records if "seconds" in r and r.get("line_px") is not None
               and "boat" in r and not r["reasons"]]
        if len(use) < LINE_FIT_MIN_BOATS:
            for r in use:
                r["reasons"].append("line_fit_short")
            return records
        x = np.array([r["line_px"] for r in use])
        y = np.log([r["seconds"] for r in use])
        c = float(np.polyfit(x, y, 1)[0])
        for r in use:
            r["seconds_raw"] = r["seconds"]
            r["seconds"] = round(float(np.exp(np.log(r["seconds"]) - c * (r["line_px"] - x.mean()))), 4)
            r["line_fit"] = round(c, 6)
        return records
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
