import hashlib

import pytest

from scraper.turn_measurement import digest
from tools.measure_first_mark_brackets import measure_brackets
from test_exhibition_segments import setup_capture, write_json


def test_first_mark_brackets_preserve_missing_sections_and_reject_duplicate_claims(tmp_path):
    capture, profile, _ = setup_capture(tmp_path)
    profile["gates"] = {name: profile["gates"][name] for name in "ABCD"}
    path = write_json(tmp_path / "manifest.json", capture)
    notes = {"manifest_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
             "profile_sha256": digest(profile), "first_lap_caption_reviewed": True,
             "boat_numbers_reviewed": True, "first_lap_caption_frame": "f_000.png",
             "boats": {"1": {"A": ["f_001.png", "f_002.png"], "B": ["f_005.png", "f_006.png"],
                             "C": ["f_009.png", "f_010.png"], "D": ["f_013.png", "f_014.png"]}}}
    calibration = tmp_path / "calibration.png"
    result = measure_brackets(path, profile, calibration, notes)
    assert result["coverage"] == dict.fromkeys(("entry", "rotation", "exit", "turn_total"), 1)
    assert result["boats"][0]["segments"]["rotation"]["bracket_range_video_seconds"] == [.3, .5]
    assert not result["rating_ready"]
    notes["boats"]["2"] = {"A": notes["boats"]["1"]["A"]}
    with pytest.raises(ValueError, match="duplicate_gate_claim"):
        measure_brackets(path, profile, calibration, notes)
    del notes["boats"]["2"]
    del notes["boats"]["1"]["B"]
    partial = measure_brackets(path, profile, calibration, notes)
    assert partial["boats"][0]["segments"]["turn_total"]["status"] == "intermediate_gate_missing"
    assert partial["coverage"]["exit"] == 1
