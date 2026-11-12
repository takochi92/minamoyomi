import copy

import pytest

from tools.assess_exhibition_readiness import CANDIDATES, assess


def sample(review_hash="c", *, count=6, shift=0):
    return {"date": "20261112", "venue": "04", "race": 12, "lap": 1,
            "quality_checks": "pinned_camera_and_continuous_track_v2",
            "manifest_sha256": "a" * 64, "profile_sha256": "b" * 64,
            "review_sha256": review_hash * 64,
            "boats": [{"boat": boat, "segments": {name: {
                "status": "reference", "video_seconds": 1 + boat / 10 + shift,
                "bracket_range_video_seconds": [0.9, 2],
            } for name in CANDIDATES.values()}} for boat in range(1, count + 1)]}


def test_pair_must_have_six_boats_two_readers_and_the_same_capture():
    reference = sample()
    other = sample("d", count=5)
    mismatch = sample("e")
    mismatch["manifest_sha256"] = "f" * 64
    result = assess([("A", reference), (" a ", sample("f")), ("B", other), ("C", mismatch)],
                    min_races=1, min_dates=1)
    metric = result["metrics"]["straight"]
    assert metric["six_boat_races"] == 1
    assert metric["paired_passing_races"] == 0
    assert all(row["status"] == "fewer_than_six_common_boats" for row in metric["races"][0]["paired_checks"])


def test_disagreement_gate_reports_coverage_without_issuing_grades():
    reference = sample()
    close = sample("d", shift=.015)
    result = assess([("first", reference), ("second", close)], min_races=1, min_dates=1)
    assert result["metrics"]["straight"]["repeatability_screen_passed"]
    assert result["rating_ready"] is False
    far = sample("e", shift=.05)
    result = assess([("first", reference), ("second", far)], min_races=1, min_dates=1)
    assert result["metrics"]["straight"]["races"][0]["paired_checks"][0]["status"] == "disagreement_too_large"


def test_bad_numeric_result_and_duplicate_boat_are_rejected():
    invalid = sample()
    invalid["boats"].append(copy.deepcopy(invalid["boats"][0]))
    with pytest.raises(ValueError, match="invalid_result_boat_numbers"):
        assess([("first", invalid)])
