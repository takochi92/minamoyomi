import hashlib
import json
import random

from PIL import Image

from scraper.exhibition_segments import SEGMENTS, measure, usable_frames
from scraper.turn_measurement import digest
import pytest

from tools.exhibition_pipeline import exclusive
from tools.measure_exhibition import (
    Busy, inventory, measure_files, profile_with_patches, run_batch, store, template,
)


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
        "fit_video_seconds": .8, "fit_minus_bracket_seconds": 0.0, "fit_residual_pixels": 0.0,
    }
    assert result["camera_layout_check"] == "human_review_only"
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


def prepared(tmp_path, boats=None, seed=19, patches=False):
    manifest, profile, obs = setup_capture(tmp_path)
    if seed != 19:
        image = Image.frombytes("L", (96, 96), random.Random(seed).randbytes(96 * 96))
        for row in manifest["frames"]:
            image.save(tmp_path / row["file"])
            row["sha256"] = hashlib.sha256((tmp_path / row["file"]).read_bytes()).hexdigest()
    manifest_path = write_json(tmp_path / "manifest.json", manifest)
    profile_path = write_json(tmp_path / "profile.json", profile)
    if patches:
        write_json(profile_path, profile_with_patches(manifest_path, profile_path, "f_000.png"))
    review = template(manifest_path, profile_path)
    review.update(window=[199, 203], camera_reference="f_000.png", camera_layout_reviewed=True,
                  boats=boats or {"1": obs})
    write_json(tmp_path / "review.json", review)
    queue = write_json(tmp_path / "queue.json", {"jobs": [
        {"date": "20261112", "venue": "04", "race": 12, "manifest": "manifest.json",
         "profile": "profile.json", "review": "review.json"}]})
    return obs, review, queue


def run(tmp_path):
    return measure_files(tmp_path / "manifest.json", tmp_path / "profile.json", tmp_path / "review.json")


def test_profile_reference_patches_reject_another_camera_view(tmp_path):
    one, other = tmp_path / "a", tmp_path / "b"
    one.mkdir(), other.mkdir()
    prepared(one, patches=True)
    result = run(one)
    assert result["camera_layout_check"] == "profile_reference_patches"
    assert result["coverage"] == dict.fromkeys(SEGMENTS, 1)
    prepared(other, seed=77)                                   # another view, human flag still true
    profile = json.loads((one / "profile.json").read_text())
    write_json(other / "profile.json", profile)
    review = template(other / "manifest.json", other / "profile.json")
    review.update(window=[199, 203], camera_reference="f_000.png", camera_layout_reviewed=True,
                  boats=json.loads((other / "review.json").read_text())["boats"])
    write_json(other / "review.json", review)
    with pytest.raises(ValueError, match="camera_view_differs_from_profile"):
        run(other)


def test_same_track_under_two_boats_is_not_measured(tmp_path):
    obs, _, _ = prepared(tmp_path)
    prepared(tmp_path, boats={"1": obs, "2": obs, "3": [{**o, "bow": [o["bow"][0], 44]} for o in obs]})
    result = run(tmp_path)
    assert result["coverage"] == dict.fromkeys(SEGMENTS, 1)                     # only boat 3
    for boat in (0, 1):
        assert result["boats"][boat]["missing_crossings"]["A"] == ["bow_track_shared_with_another_boat"]
        assert result["boats"][boat]["segments"]["turn_total"]["status"] == "bow_track_shared_with_another_boat"


def test_sparse_or_jumping_track_is_not_measured(tmp_path):
    obs, _, _ = prepared(tmp_path)
    sparse = []
    for i in range(6):                                          # only the two frames around each gate
        n = next(k for k, o in enumerate(obs) if o["bow"][0] >= 15 + 10 * i) - 1
        sparse += [o for o in obs[n:n + 2] if o not in sparse]
    prepared(tmp_path, boats={"1": sparse})
    result = run(tmp_path)
    assert not result["boats"][0]["missing_crossings"]                          # every gate is still found
    assert result["boats"][0]["segments"]["turn_total"]["status"] == "bow_track_not_continuous"
    assert result["coverage"]["back_stretch"] == 0
    jump = [dict(o) for o in obs]
    for o in jump[12:]:
        o["bow"] = [o["bow"][0], 59]                            # switches to another boat between gates
    prepared(tmp_path, boats={"1": jump})
    result = run(tmp_path)
    statuses = {k: v["status"] for k, v in result["boats"][0]["segments"].items()}
    assert statuses["turn_entry"] == "reference" and statuses["back_stretch"] == "reference"
    assert "bow_jump_too_large" in statuses.values()


def test_fit_exposes_noisy_bow_annotation(tmp_path):
    obs, _, _ = prepared(tmp_path)
    noisy = [dict(o) for o in obs]
    for n in (10, 12, 14, 16, 18, 20):                          # alternate the bow forward and back
        noisy[n]["bow"] = [noisy[n]["bow"][0] + 1.2, 50]
        noisy[n + 1]["bow"] = [noisy[n + 1]["bow"][0] - 1.2, 50]
    prepared(tmp_path, boats={"1": noisy})
    section = run(tmp_path)["boats"][0]["segments"]["back_stretch"]
    assert section["status"] == "reference" and section["fit_residual_pixels"] > 0.8


def test_rerun_keeps_history_and_needs_a_reason_to_drop_sections(tmp_path):
    obs, review, queue = prepared(tmp_path)
    out = tmp_path / "out"
    assert run_batch(queue, out)["races"][0]["change"] == "new"
    path = out / "20261112-04-12.json"
    first = path.read_bytes()
    assert run_batch(queue, out)["races"][0]["change"] == "unchanged"
    moved = [{"file": o["file"], "bow": [o["bow"][0] + 1.2, o["bow"][1]]} for o in obs]
    write_json(tmp_path / "review.json", {**review, "boats": {"1": moved}})
    row = run_batch(queue, out)["races"][0]
    assert row["change"] == "updated" and row["previous_coverage"]["back_stretch"] == 1
    archived = list((out / "history").glob("20261112-04-12.*.json"))
    assert len(archived) == 1 and archived[0].read_bytes() == first
    assert json.loads(path.read_text())["replaces"]["archived_as"] == f"history/{archived[0].name}"
    write_json(tmp_path / "review.json", {**review, "boats": {"1": obs[:10]}})   # withdraws the later gates
    assert run_batch(queue, out)["races"][0]["status"] == "prior_result_kept"
    jobs = json.loads(queue.read_text())["jobs"]
    jobs[0]["replace_reason"] = "later gates were read on the wrong boat"
    write_json(queue, {"jobs": jobs})
    row = run_batch(queue, out)["races"][0]
    assert row["change"] == "replaced_with_reason"
    stored = json.loads(path.read_text())
    assert stored["coverage"]["back_stretch"] == 0 and stored["replaces"]["lost_sections"] > 0
    assert len(list((out / "history").glob("*.json"))) == 2


def test_single_measure_uses_the_same_guard(tmp_path):
    obs, review, _ = prepared(tmp_path)
    path = tmp_path / "out" / "r.json"
    path.parent.mkdir()
    assert store(path, run(tmp_path))[0] == "new"
    write_json(tmp_path / "review.json", {**review, "boats": {}})
    assert store(path, run(tmp_path))[0] == "prior_result_kept"
    assert json.loads(path.read_text())["coverage"]["back_stretch"] == 1


def test_concurrent_batch_reports_busy_and_bad_path_does_not_stop_the_batch(tmp_path):
    _, _, queue = prepared(tmp_path)
    out = tmp_path / "out"
    run_batch(queue, out)
    with exclusive(out / ".exhibition-batch.lock"):               # another batch is running
        with pytest.raises(Busy):
            run_batch(queue, out)
    (tmp_path / "dir.json").mkdir()
    jobs = json.loads(queue.read_text())["jobs"] + [
        {"date": "20261112", "venue": "01", "race": 1, "manifest": "dir.json", "profile": "profile.json", "review": "review.json"}]
    write_json(queue, {"jobs": jobs})
    summary = run_batch(queue, tmp_path / "out2")
    assert summary["status_counts"] == {"input_unreadable": 1, "reference": 1}
    assert (tmp_path / "out2" / "20261112-04-12.json").exists()


def test_inventory_separates_reference_profile_and_measured_venues(tmp_path):
    _, _, queue = prepared(tmp_path, patches=True)
    out = tmp_path / "out"
    run_batch(queue, out)
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    write_json(profiles / "04.json", json.loads((tmp_path / "profile.json").read_text()))
    stadiums = write_json(tmp_path / "stadiums.json", {"stadiums": {"04": {"evidence": "pr-tool-homesv"}}})
    venue = inventory(stadiums, profiles)["venues"][3]
    assert venue["state"] == "profile_with_reference" and venue["measured_races"] == 0
    result = inventory(stadiums, profiles, out)
    assert result["venues"][3]["state"] == "partly_measured"                     # one boat only
    assert result["six_boat_measured_venues"] == 0 and result["reference_profile_venues"] == 1
