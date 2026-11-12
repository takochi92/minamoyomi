import hashlib
import json
import random

from PIL import Image

from scraper.exhibition_segments import SEGMENTS, measure, usable_frames
from scraper.turn_measurement import digest
from tools.measure_exhibition import inventory, run_batch, template


def setup_capture(tmp_path):
    rng = random.Random(19)
    image = Image.frombytes("L", (96, 96), rng.randbytes(96 * 96))
    profile = {
        "schema": 1, "venue": "04", "id": "test-fixed-shot", "lap": 1,
        "image_size": [96, 96], "anchors": [[25, 25], [70, 25], [50, 70]],
        "gates": {name: {"axis": "x", "value": 15 + 10 * i, "direction": 1, "segment": [40, 60]}
                  for i, name in enumerate("ABCDEF")},
    }
    manifest = {"schema": 2, "mode": "seek", "status": "ok", "date": "20261112",
                "venue": {"jo": "04"}, "race": 12, "frames": []}
    observations = []
    for n in range(23):
        name = f"f_{n:03}.png"
        path = tmp_path / name
        image.save(path)
        manifest["frames"].append({
            "file": name, "frame": {"mediaTime": 200 + n / 10},
            "measurable": True, "stable": True, "paused": True, "seeked": True,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
        observations.append({"file": name, "bow": [12 + n * 2.5, 50]})
    return manifest, profile, observations


def write_json(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_fixed_shot_times_and_safe_batch_rerun(tmp_path):
    manifest, profile, observations = setup_capture(tmp_path)
    manifest_path = write_json(tmp_path / "manifest.json", manifest)
    profile_path = write_json(tmp_path / "profile.json", profile)
    review = template(manifest_path, profile_path)
    review.update(window=[199, 203], camera_reference="f_000.png", camera_layout_reviewed=True,
                  boats={"1": observations})
    write_json(tmp_path / "review.json", review)
    queue = write_json(tmp_path / "queue.json", {"jobs": [
        {"date": "20261112", "venue": "04", "race": 12, "manifest": "manifest.json",
         "profile": "profile.json", "review": "review.json"},
        {"date": "20261112", "venue": "24", "race": 1},
    ]})
    out = tmp_path / "out"
    assert run_batch(queue, out)["status_counts"] == {"reference": 1, "input_pending": 1}
    path = out / "20261112-04-12.json"
    before = path.read_bytes()
    result = json.loads(before)
    assert result["coverage"] == dict.fromkeys(SEGMENTS, 1)
    assert result["boats"][0]["segments"]["back_stretch"] == {
        "status": "reference", "video_seconds": .8, "bracket_range_video_seconds": [.7, .9],
    }
    assert not result["rating_eligible"]
    write_json(tmp_path / "review.json", {**review, "boats": {"2": observations}})
    assert run_batch(queue, out)["status_counts"]["prior_result_kept"] == 1
    assert path.read_bytes() == before


def test_camera_cut_inside_section_and_duplicate_time(tmp_path):
    manifest, profile, observations = setup_capture(tmp_path)
    review = {"schema": 1, "manifest_sha256": "test", "profile_sha256": digest(profile),
              "camera_layout_reviewed": True,
              "camera_reference": "f_000.png", "window": [199, 203], "boats": {"1": observations}}
    path = tmp_path / "f_004.png"
    Image.new("L", (96, 96), 0).save(path)
    assert measure(manifest, profile, review, tmp_path, manifest_sha256="test")[
        "boats"][0]["segments"]["turn_entry"]["status"] == "frame_sha256_mismatch"
    manifest["frames"][4]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    result = measure(manifest, profile, review, tmp_path, manifest_sha256="test")
    assert result["boats"][0]["segments"]["turn_entry"]["status"] == "camera_landmark_changed_in_section"
    manifest["frames"][4]["frame"]["mediaTime"] = manifest["frames"][3]["frame"]["mediaTime"]
    assert {"f_003.png", "f_004.png"}.isdisjoint(usable_frames(manifest))
    result = measure(manifest, profile, review, tmp_path, manifest_sha256="test")
    assert result["boats"][0]["segments"]["turn_entry"]["status"] == "frame_gap_in_section"


def test_venue_inventory_distinguishes_replay_from_calibration(tmp_path):
    _, profile, _ = setup_capture(tmp_path)
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    write_json(profiles / "04.json", profile)
    stadiums = write_json(tmp_path / "stadiums.json", {"stadiums": {
        f"{n:02}": {"evidence": "pr-tool-homesv"} for n in range(1, 25)
    }})
    result = inventory(stadiums, profiles)
    assert result["venue_count"] == result["playback_verified_venues"] == 24
    assert result["camera_profile_venues"] == 1
    assert result["venues"][3]["state"] == "profile_available"
    assert result["venues"][-1]["state"] == "camera_profile_needed"
