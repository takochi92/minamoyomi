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


def wake_scene(seed, *, accel=0.0, drop=.2, v0=SPEED):
    """A dark boat moving left, and wake that stays where the boat has been: it covers the later half."""
    rng = random.Random(seed)
    noise = np.random.default_rng(seed)
    frames, start = [], 268.0
    for i in range(80):
        t = start + i / 30
        if rng.random() < drop:
            continue
        dt = t - start
        front = 430 - (v0 * dt + .5 * accel * dt * dt)
        frame = np.full((H, W), 120, dtype=np.int16) + noise.integers(-4, 5, size=(H, W))
        for x in range(int(front) + 50, 430, 9):               # dark troughs left behind, fixed in place
            if x < W and (x * 7 + seed) % 3:
                frame[26:40, x:x + 4] = 70 + (x * 13 + i * 5) % 30
        left = int(round(front))
        if -42 < left < W:
            frame[28:38, max(left, 0):min(left + 42, W)] = 45
            frame[30:36, max(left + 8, 0):min(left + 20, W)] = 20     # structure inside the boat
        frames.append((t, np.clip(frame, 0, 255).astype(np.uint8)))
    return frames, np.full((H, W), 120, dtype=np.uint8)


def test_alignment_measures_speed_where_wake_breaks_the_edge():
    speeds = list(range(120, 261, 2))
    errors = []
    for seed in range(8):
        frames, background = wake_scene(seed)
        times, image = ky.build(frames, BAND, background, spray_guard=True)
        got = ky.measure_speed(times, image, (370.0, 270.0), -1, speeds)
        assert got["status"] == "candidate", got["reasons"]
        errors.append(got["seconds"] - 100 / SPEED)
        assert abs(got["speed"] - SPEED) <= 1.5 and got["contrast"] >= 4
    assert max(abs(e) for e in errors) < .005


def test_alignment_follows_a_boat_that_speeds_up():
    frames, background = wake_scene(2, accel=40.0, v0=165.0)
    times, image = ky.build(frames, BAND, background, spray_guard=True)
    got = ky.measure_speed(times, image, (370.0, 270.0), -1, list(range(120, 261, 2)), accelerations=(0.0, 20.0, 40.0, 60.0))
    assert got["status"] == "candidate" and got["acceleration"] in (20.0, 40.0, 60.0)
    t = lambda x: (-165 + (165 ** 2 + 2 * 40 * (430 - x)) ** .5) / 40
    assert abs(got["seconds"] - (t(270) - t(370))) < .015


def test_alignment_refuses_water_without_a_boat():
    noise = np.random.default_rng(1)
    frames = [(268 + i / 30, np.clip(120 + noise.integers(-6, 7, size=(H, W)), 0, 255).astype(np.uint8)) for i in range(60)]
    times, image = ky.build(frames, BAND, np.full((H, W), 120, dtype=np.uint8), spray_guard=True)
    got = ky.measure_speed(times, image, (370.0, 270.0), -1, list(range(120, 261, 2)))
    assert got["status"] == "missing"


def test_tool_speed_command_uses_frame_coordinates(tmp_path):
    import json

    from PIL import Image

    from tools import boatcast_kymograph as tool
    frames, _ = wake_scene(4)
    rows = []
    for i, (t, frame) in enumerate(frames):
        Image.fromarray(frame, "L").save(tmp_path / f"f_{i:03}.png")
        rows.append({"file": f"f_{i:03}.png", "mediaTime": t})
    (tmp_path / "manifest.json").write_text(json.dumps({"frames": rows}))
    dump = tool.build(tmp_path / "manifest.json", BAND, (30, 440))
    got = tool.speed(dump, (370.0, 270.0), -1, (120, 260))["image_guard"]
    assert got["status"] == "candidate" and abs(got["seconds"] - 100 / SPEED) < .005 and abs(got["speed"] - SPEED) <= 1.5
