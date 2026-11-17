import json

import numpy as np
import pytest

from scraper import boatcast_measure as bm
from tools import boatcast_measure as tool


def synth(tmp_path, *, speeds, lines=None, starts=None, n_s=200, n_o=21, step=4, ostep=4, fps=30.0,
          frames=900, noise=8.0, seed=1, skip=()):
    """Space-time samples like the capture writes: water noise, each boat a bright front with a wake behind."""
    rng = np.random.default_rng(seed)
    lines = lines or [0] * len(speeds)
    starts = starts or [40 + 140 * i for i in range(len(speeds))]
    times = np.arange(frames) / fps + 100.0
    keep = np.array([i not in skip for i in range(frames)])
    band = 110 + noise * rng.standard_normal((frames, n_s, n_o))
    s_px = np.arange(n_s) * step
    for v, line, f0 in zip(speeds, lines, starts):
        arrive = f0 + s_px / v * fps                     # frame at which the bow reaches each column
        o = int(round(line / ostep)) + n_o // 2
        for f in range(frames):
            age = f - arrive                             # frames since the bow passed
            lit = (age >= 0) & (age < 80)
            band[f, lit, max(0, o - 1):o + 2] = (235 - age[lit] * 1.4)[:, None]
    band = np.clip(band, 0, 255).astype(np.uint8)[keep]
    rgb = np.repeat(band.reshape(keep.sum(), -1, 1), 3, axis=2)
    d = tmp_path / "cap"
    d.mkdir(exist_ok=True)
    rgb.tofile(d / "shot.bin")
    (d / "manifest.json").write_text(json.dumps({"status": "ok", "shots": {"shot": {
        "nS": n_s, "nO": n_o, "nPlate": 0, "times": times[keep].tolist(), "skipped": int((~keep).sum()),
        "sizes": ["1920x1080"]}}}))
    cfg = {"step": step, "ostep": ostep, "gates": {"main": [40, 760]}}
    return d, cfg


def test_section_time_of_every_boat_is_recovered(tmp_path):
    speeds = [400, 410, 395, 420, 405, 415]
    d, cfg = synth(tmp_path, speeds=speeds)
    records, info = bm.measure_shot(d, "shot", cfg)
    assert info["curves"] == 6
    for r, v in zip(records, speeds):
        assert not r["reasons"]
        assert r["seconds"] == pytest.approx(720 / v, abs=.004)


def test_skipped_frames_use_real_frame_times(tmp_path):
    d, cfg = synth(tmp_path, speeds=[400, 420], skip=set(range(150, 900, 100)))
    records, _ = bm.measure_shot(d, "shot", cfg)
    assert [r["seconds"] for r in records] == pytest.approx([1.8, 720 / 420], abs=.006)


def test_curve_count_must_match_the_race_card():
    recs = [{"order": i, "reasons": []} for i in range(1, 6)]
    bm.assign_boats(recs, [1, 2, 3, 4, 5, 6])
    assert all("curve_count_5_of_6" in r["reasons"] for r in recs)
    assert not any("boat" in r for r in recs)


def test_boats_on_another_line_are_left_out(tmp_path):
    d, cfg = synth(tmp_path, speeds=[400, 400, 400, 400], lines=[0, 0, 40, 0])
    records, _ = bm.measure_shot(d, "shot", cfg)
    bm.line_check(records, 10)
    assert ["different_line" in r["reasons"] for r in records] == [False, False, True, False]


def test_a_boat_that_does_not_reach_the_far_gate_is_unmeasured(tmp_path):
    d, cfg = synth(tmp_path, speeds=[400, 400], starts=[60, 860])   # 2nd boat runs out of frames
    records, _ = bm.measure_shot(d, "shot", cfg)
    assert not records[0]["reasons"]
    assert len(records) == 1 or records[1]["reasons"]


def test_plate_colour():
    ring = np.tile(np.array([30, 120, 220], np.float32), (5, 16, 1))
    assert bm.plate_boat(ring)[0] == 4


def test_rows_pass_store_validation_and_read_back(tmp_path, monkeypatch):
    rows = [{"schema": 1, "date": "20261114", "venue": "04", "race": 3, "boat": b, "motor": 10 + b, "rider": "40%02d" % b,
             "metric": "acceleration", "source": "video", "seconds": 1.1, "profile": "04-turn1-v1", "parts": []}
            for b in (1, 2)]
    path = tool.write("20261114", "04", rows, [{"capture": "ok"}], {"established": None}, tmp_path)
    s = tool.self_check(path, rows, [{"capture": "ok"}], [3])
    assert s["pass"] and s["rows"] == 2
    s = tool.self_check(path, rows[:1], [{"capture": "ok"}], [3])
    assert not s["pass"]


def synth_turn(tmp_path, speeds, *, n_s=150, n_o=31, step=4, ostep=4, fps=30.0, frames=1000, seed=3):
    """Turn-like samples: every boat leaves a bright wake that stays (and shimmers) in the band, so
    later boats run through earlier wakes. The boat itself is a small block that moves."""
    rng = np.random.default_rng(seed)
    band = 100 + 6 * rng.standard_normal((frames, n_s, n_o))
    wake = np.zeros((n_s, n_o))
    starts = [50 + 150 * i for i in range(len(speeds))]
    s_px = np.arange(n_s) * step
    for f in range(frames):
        for v, f0, lane in zip(speeds, starts, range(len(speeds))):
            pos = (f - f0) / fps * v                      # bow position along the path (px)
            if 0 <= pos < s_px[-1]:
                cols = (s_px <= pos) & (s_px > pos - 24)  # hull about 24 px long
                o = 8 + 3 * (lane % 4)
                wake[(s_px <= pos - 24) & (s_px > pos - 60), o - 4:o + 5] = 240
                band[f, cols, o - 4:o + 5] = 40
        band[f] = np.where(band[f] == 40, 40, np.maximum(band[f], wake + 4 * rng.standard_normal(wake.shape) * (wake > 0)))
    band = np.clip(band, 0, 255).astype(np.uint8)
    rgb = np.repeat(band.reshape(frames, -1, 1), 3, axis=2)
    d = tmp_path / "turn"
    d.mkdir()
    rgb.tofile(d / "turn1.bin")
    (d / "manifest.json").write_text(json.dumps({"status": "ok", "shots": {"turn1": {
        "nS": n_s, "nO": n_o, "nPlate": 0, "times": (np.arange(frames) / fps).tolist(), "skipped": 0,
        "sizes": ["1920x1080"]}}}))
    return d, {"step": step, "ostep": ostep, "gates": {"main": [80, 520]}, "feature": "motion"}


def test_motion_feature_measures_boats_running_through_old_wakes(tmp_path):
    speeds = [300, 320, 290, 310]
    d, cfg = synth_turn(tmp_path, speeds)
    records, info = bm.measure_shot(d, "turn1", cfg)
    assert info["curves"] == 4
    for r, v in zip(records, speeds):
        assert not r["reasons"]
        assert r["seconds"] == pytest.approx(440 / v, abs=.01)


COLOURS = {"3": [325, 15], "4": [195, 235], "5": [40, 75], "6": [90, 180]}


def passes(hues):
    return [{"order": i + 1, "points": 100, "reasons": [], "hue": h} for i, h in enumerate(hues)]


def test_colour_anchors_fill_white_and_black_in_order():
    recs = bm.assign_by_colour(passes([None, None, 344, 213, 55, None]), [1, 2, 3, 4, 5, 6], COLOURS)
    assert [r.get("boat") for r in recs] == [1, 2, 3, 4, 5, 6]


def test_extra_pass_before_the_first_boat_is_not_a_boat():
    recs = passes([None, None, None, 344, 213, 55, None])
    recs[0]["reasons"].append("short_curve")
    bm.assign_by_colour(recs, [1, 2, 3, 4, 5, 6], COLOURS)
    assert [r.get("boat") for r in recs] == [None, 1, 2, 3, 4, 5, 6]


def test_a_missing_boat_leaves_its_neighbours_unassigned_instead_of_guessing():
    # boat 2 never showed up: only one uncoloured pass before red, but boats 1 and 2 are needed
    recs = bm.assign_by_colour(passes([None, 344, 213, 55, None]), [1, 2, 3, 4, 5, 6], COLOURS)
    assert recs[0].get("boat") is None and "identity_unclear" in recs[0]["reasons"]
    assert [r.get("boat") for r in recs[1:]] == [3, 4, 5, 6]


def test_green_that_looks_blue_after_yellow_is_six():
    recs = bm.assign_by_colour(passes([None, None, 344, 213, 55, 217]), [1, 2, 3, 4, 5, 6], COLOURS)
    assert recs[5]["boat"] == 6


def test_colours_out_of_order_stop_everything():
    recs = bm.assign_by_colour(passes([55, None, 344]), [1, 2, 3, 4, 5, 6], COLOURS)
    assert not any("boat" in r for r in recs)


def test_line_correction_brings_times_to_the_common_line():
    recs = [{"seconds": 3.0, "line_px": -40.0}, {"seconds": 3.5, "line_px": 0.0}]
    bm.line_correct(recs, .0125)
    assert [r["seconds"] for r in recs] == [3.5, 3.5]
    assert recs[0]["seconds_raw"] == 3.0


def test_per_race_line_fit_keeps_only_what_the_line_does_not_explain():
    recs = [{"seconds": 3.0 * (1 + .003 * x), "line_px": x, "boat": b, "reasons": []}
            for b, x in enumerate([-20.0, -5.0, 0.0, 10.0, 15.0], 1)]
    recs[2]["seconds"] *= 1.01          # boat 3 is 1 % slower than its line says
    bm.line_correct(recs, "per_race")
    t = [r["seconds"] for r in recs]
    assert max(t) == t[2] and max(t[:2] + t[3:]) - min(t[:2] + t[3:]) < .015 < t[2] - max(t[:2] + t[3:])
    few = [{"seconds": 3.0, "line_px": 0.0, "boat": 1, "reasons": []}]
    bm.line_correct(few, "per_race")
    assert few[0]["reasons"] == ["line_fit_short"] and few[0]["seconds"] == 3.0


def test_a_colour_seen_on_several_passes_anchors_nothing():
    recs = bm.assign_by_colour(passes([None, None, 344, 213, 218, 55, 216]), [1, 2, 3, 4, 5, 6], COLOURS)
    boats = [r.get("boat") for r in recs if r.get("boat")]
    assert len(boats) == len(set(boats))


def test_wake_line_reads_the_water_not_the_spray():
    """A boat whose spray stands 4 px above its wake: the line is the wake's centre, sub-pixel,
    and the slope across the frame is kept (lines converge toward the far end)."""
    rng = np.random.default_rng(5)
    frames, n_cols, n_off, every, step = 400, 60, 61, 8, 3
    half = (n_off - 1) // 2
    fine = (100 + 5 * rng.standard_normal((frames, n_cols, n_off))).astype(np.float32)
    coef = np.array([0.0, 2.5 / 3 * 1.0, 20.0])      # bow reaches band column sb at frame 20 + sb * 0.833
    true = lambda s_px: -7.3 + 0.004 * (s_px - (200 - 1) * step / 2)
    off = np.arange(n_off) - half
    for j in range(n_cols):
        f0 = np.polyval(coef, j * every / step)
        for f in range(frames):
            age = f - f0
            if 2 <= age < 10:
                fine[f, j] += 120 * np.exp(-((off - true(j * every) - 4) ** 2) / 8)   # spray, higher up
            elif age >= 10:
                fine[f, j] += 90 * np.exp(-((off - true(j * every)) ** 2) / 6) * np.exp(-age / 200)
    wl = bm.wake_line(np.clip(fine, 0, 255).astype(np.uint8), coef, 200, step, every)
    assert wl["line_px"] == pytest.approx(-7.3, abs=.15)
    assert wl["line_slope"] == pytest.approx(.004, abs=.001)
    assert wl["spray_px"] == pytest.approx(4, abs=.6)


def test_landmark_shift_follows_the_camera():
    frames = 50
    dy = .3 * np.sin(np.arange(frames) / 5)
    ys = np.arange(370, 481)
    strips = []
    for x in (100, 300, 500):
        edge = 420 + x / 100
        strips.append(np.array([200 - 150 / (1 + np.exp(-(ys - edge - d) * 2)) for d in dy]))
    land = np.concatenate(strips, 1).clip(0, 255).astype(np.uint8)
    shot = {"landmarks": [{"kind": "v", "x": x, "y": [370, 480]} for x in (100, 300, 500)]}
    out = bm.landmark_shift(shot, land)
    assert np.abs(out["dy"] - (dy - np.median(dy))).max() < .08
    assert [e[2] for e in out["edges"]] == pytest.approx([421, 423, 425], abs=.6)


def test_assign_by_reference_lines_up_a_shot_with_missing_boats():
    from scraper import boatcast_measure as bm
    reference = [{"boat": b, "t_a": 210 + 3.5 * b} for b in range(1, 7)]
    # boats 1 and 3 were not seen; the other camera is 30.2 s earlier
    records = [{"t_a": 210 + 3.5 * b - 30.2, "reasons": []} for b in (2, 4, 5, 6)]
    bm.assign_by_reference(records, reference, (29, 31))
    assert [r.get("boat") for r in records] == [2, 4, 5, 6]
    # too few to line up: nothing is guessed
    few = [{"t_a": 100.0, "reasons": []}, {"t_a": 140.0, "reasons": []}]
    bm.assign_by_reference(few, reference, (29, 31))
    assert all("boat" not in r and "no_reference_match" in r["reasons"] for r in few)


def test_drop_non_boats_removes_a_scene_cut_trace_only_when_the_profile_asks():
    from tools.boatcast_measure import drop_non_boats
    recs = [{"order": i + 1, "seconds": 4.3, "reasons": [], "cover": .9} for i in range(6)]
    recs.append({"order": 7, "seconds": 0.01, "reasons": [], "cover": .5})
    assert len(drop_non_boats([dict(r) for r in recs], {})) == 7
    kept = drop_non_boats([dict(r) for r in recs], {"minSeconds": 1.5})
    assert [r["order"] for r in kept] == [1, 2, 3, 4, 5, 6]
    assert all(r["seconds"] > 1 for r in kept)


def test_tone_squeezes_highlights_keeps_order_and_white():
    import numpy as np
    from scraper.boatcast_measure import tone
    x = np.array([0.0, 0.3, 0.6, 0.8, 0.95, 1.0])
    y = tone(x)
    assert np.all(np.diff(y) > 0)                 # order kept
    assert y[-1] == 1.0 and y[0] == 0.0           # blown-out white stays white: nothing is recovered from it
    assert (y[4] - y[3]) < (x[4] - x[3])          # the bright end is squeezed
