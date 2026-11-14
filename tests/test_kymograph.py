import random

import numpy as np
import pytest

from scraper import kymograph as ky

H, W, BAND = 60, 450, (20, 45)
GATES = (357.0, 73.0)
SPEED = 183.0                                    # pixels per second, toward smaller x


def scene(start_times, *, seed=1, spray=0.0, cover_front=0.0, drop=0.0, frames=120, t0=268.0, boat_len=42):
    """Grey frames of dark boats moving left over noisy water, with bright spray behind them."""
    rng = random.Random(seed)
    noise = np.random.default_rng(seed)
    water = np.full((H, W), 120, dtype=np.int16)
    out, truth = [], []
    for start in start_times:
        truth.append(tuple(start + (440 - g) / SPEED for g in GATES))        # when the front passes each gate
    for i in range(frames):
        t = t0 + i / 30
        if rng.random() < drop:
            continue
        frame = water + noise.integers(-4, 5, size=(H, W))
        for start in start_times:
            front = 440 - SPEED * (t - start)
            left, right = int(round(front)), int(round(front)) + boat_len
            if right < 0 or left >= W:
                continue
            frame[28:38, max(left, 0):min(right, W)] = 45                    # hull: darker than the water
            if rng.random() < spray:
                tail = rng.randint(10, 60)
                frame[24:42, min(max(right - 6, 0), W):min(right + tail, W)] = 235   # spray trails behind
            if rng.random() < cover_front:
                frame[26:40, max(left, 0):min(left + rng.randint(8, 20), W)] = 235   # spray over the bow
        out.append((t, np.clip(frame, 0, 255).astype(np.uint8)))
    background = np.full((H, W), 120, dtype=np.uint8)
    return out, background, truth


def run(frames, background, **kwargs):
    times, image = ky.build(frames, BAND, background, **kwargs)
    return ky.measure(times, image, GATES, -1)


def test_clean_pass_is_timed_from_the_whole_streak():
    frames, background, truth = scene([268.2])
    (boat,) = run(frames, background)
    assert boat["status"] == "measured" and boat["reasons"] == []
    assert abs(boat["first"] - truth[0][0]) < .01 and abs(boat["second"] - truth[0][1]) < .01
    assert abs(boat["seconds"] - (GATES[0] - GATES[1]) / SPEED) < .004
    assert boat["coverage"] >= .95 and set(boat["by_point"]) == {"front", "middle", "back"}


def test_lost_frames_and_spray_do_not_break_the_timing():
    true_section = (GATES[0] - GATES[1]) / SPEED
    errors, missing = [], 0
    for seed in range(20):
        frames, background, _ = scene([268.2], seed=seed, spray=.7, cover_front=.15, drop=.3)
        boats = run(frames, background, spray_guard=True)
        if len(boats) != 1 or boats[0]["status"] != "measured":
            missing += 1
        else:
            errors.append(boats[0]["seconds"] - true_section)
    assert missing <= 4                                           # most runs survive a third of the frames lost
    assert max(abs(e) for e in errors) < .02 and abs(sum(errors) / len(errors)) < .006


def test_spray_changes_the_streak_and_is_reported_without_the_guard():
    frames, background, _ = scene([268.2], seed=3, spray=.9)
    (plain,) = run(frames, background)                            # spray counted as part of the boat
    (guarded,) = run(frames, background, spray_guard=True)
    assert guarded["status"] == "measured"
    assert plain["status"] == "missing" and set(plain["reasons"]) & {"boat_points_disagree", "streak_width_jump", "same_point_not_verified"}


def test_two_boats_are_separate_passes_in_order():
    frames, background, truth = scene([268.1, 270.6], frames=200)
    boats = run(frames, background)
    assert [b["status"] for b in boats] == ["measured", "measured"]
    assert boats[0]["first"] < boats[1]["first"]
    for boat, (a, b) in zip(boats, truth):
        assert abs(boat["seconds"] - (b - a)) < .004


def test_no_boat_and_changed_resolution():
    frames, background, _ = scene([])
    assert run(frames, background) == []
    small = [(frames[0][0], frames[0][1][:, :300])]
    with pytest.raises(ValueError, match="frame_resolution_changed"):
        ky.build(frames[:3] + small, BAND, background)


def test_boat_that_never_reaches_the_second_gate_is_missing():
    frames, background, _ = scene([268.2], frames=45)             # the capture ends before the second gate
    (boat,) = run(frames, background)
    assert boat["status"] == "missing" and boat["reasons"] == ["second_gate_not_fitted"]


def test_a_person_can_time_a_pass_with_a_few_clicks():
    start = 268.2
    clicks = [(start + (440 - x) / SPEED, x) for x in (390, 360, 330, 100, 75, 50)]
    got = ky.assisted(None, clicks, GATES, -1)
    assert got["status"] == "assisted" and abs(got["seconds"] - (GATES[0] - GATES[1]) / SPEED) < 1e-4
    assert ky.assisted(None, clicks[:2], GATES, -1)["status"] == "missing"


def test_image_can_be_rendered_for_review():
    frames, background, _ = scene([268.2], frames=40)
    _, image = ky.build(frames, BAND, background)
    assert ky.to_png_bytes(image)[:8] == b"\x89PNG\r\n\x1a\n"


def test_tool_builds_from_frames_and_times_the_pass(tmp_path):
    import json

    from PIL import Image

    from tools import boatcast_kymograph as tool
    frames, _, truth = scene([268.2], seed=5, spray=.5, drop=.2)
    rows = []
    for i, (t, frame) in enumerate(frames):
        Image.fromarray(frame, "L").save(tmp_path / f"f_{i:03}.png")
        rows.append({"file": f"f_{i:03}.png", "frame": {"mediaTime": t}, "measurable": True})
    rows.append({**rows[0], "file": "f_000.png"})                           # the same displayed frame twice
    (tmp_path / "manifest.json").write_text(json.dumps({"frames": rows}))
    dump = tool.build(tmp_path / "manifest.json", BAND, (20, 440))
    assert dump["image"].shape == (len(frames), 420) and dump["resolution"].tolist() == [W, H]
    result = tool.measure(dump, GATES, -1)
    (boat,) = result["image_guard"]
    assert boat["status"] == "measured" and abs(boat["seconds"] - (truth[0][1] - truth[0][0])) < .01
    Image.fromarray(frames[3][1][:, :300], "L").save(tmp_path / "f_003.png")   # one frame in another resolution
    with pytest.raises(SystemExit, match="frame_resolution_changed"):
        tool.build(tmp_path / "manifest.json", BAND)
