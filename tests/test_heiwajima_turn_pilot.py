import copy
import math

import pytest

from tools.heiwajima_turn_pilot import assess, crossing, evaluate_track


GATES = {
    "A": {"axis": "x", "value": 2, "direction": 1, "segment": [4, 6]},
    "B": {"axis": "y", "value": 3, "direction": -1, "segment": [4, 6]},
    "C": {"axis": "x", "value": 2, "direction": -1, "segment": [0, 2]},
}


def points():
    return [{"time": i / 10, "x": x, "y": y, "ok": True}
            for i, (x, y) in enumerate([(1, 5), (3, 5), (5, 4), (5, 2), (3, 1), (1, 1)])]


def test_fixed_directed_segment_interpolation():
    p = points()
    assert crossing(p[0], p[1], GATES["A"]) == pytest.approx(.05)
    assert crossing(p[1], p[0], GATES["A"]) is None
    assert crossing({**p[0], "y": 9}, {**p[1], "y": 9}, GATES["A"]) is None


def test_good_track_still_requires_review():
    r = evaluate_track(points(), GATES)
    assert r["status"] == "needs_manual_review"
    assert r["events"] == pytest.approx({"A": .05, "B": .25, "C": .45})
    assert r["candidate_entry_video_seconds"] == .2
    assert r["candidate_exit_video_seconds"] == .2


@pytest.mark.parametrize("change", ["failure", "nonfinite", "gap", "reverse", "missing_gate"])
def test_bad_track_has_no_measurement(change):
    p = points()
    if change == "failure": p[2]["ok"] = False
    if change == "nonfinite": p[2]["x"] = math.nan
    if change == "gap": p[-1]["time"] = 2
    if change == "reverse": p[-1]["time"] = .1
    if change == "missing_gate": p = p[:-2]
    r = evaluate_track(p, GATES)
    assert r["status"] == "rejected"
    assert "candidate_entry_video_seconds" not in r


def test_success_flag_cannot_override_player_overlay():
    r = evaluate_track(points(), GATES, excluded_regions=[(4, 3, 6, 5)])
    assert "player_overlay_or_obstruction" in r["reasons"]
    assert "candidate_exit_video_seconds" not in r


def test_stationary_ui_lock_is_rejected_even_when_tracker_says_ok():
    p = points()[:3] + [{"time": .3 + i / 10, "x": 5, "y": 4, "ok": True} for i in range(8)]
    assert "stationary_track" in evaluate_track(p, GATES)["reasons"]


def test_stop_after_completed_exit_does_not_invalidate_measured_interval():
    p = points() + [{"time": .6 + i / 10, "x": 1, "y": 1, "ok": True} for i in range(8)]
    assert evaluate_track(p, GATES)["status"] == "needs_manual_review"


def test_repeated_crossing_is_not_silently_cherry_picked():
    p = points() + [{"time": .6, "x": 1, "y": 5, "ok": True},
                    {"time": .7, "x": 3, "y": 5, "ok": True}]
    assert "missing_or_repeated_gate_A" in evaluate_track(p, GATES)["reasons"]


def test_no_publication_no_prediction_and_no_identity_inference():
    config = {"venue": "heiwajima", "turn": "1-mark", "gates": GATES,
              "date": "2026-10-26", "race": 1, "source": "official replay", "image_size": [1280, 720]}
    tracks = [{"boat": i, "points": points()} for i in range(1, 7)]
    original = copy.deepcopy(tracks)
    r = assess(tracks, config)
    assert not r["publication_ready"] and not r["prediction_used"]
    assert not r["automatic_boat_identification"]
    assert tracks == original
    tracks[-1]["boat"] = 1
    with pytest.raises(ValueError, match="six distinct"):
        assess(tracks, config)
    with pytest.raises(ValueError, match="only supports"):
        assess(original, {**config, "venue": "tamagawa"})
