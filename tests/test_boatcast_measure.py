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
