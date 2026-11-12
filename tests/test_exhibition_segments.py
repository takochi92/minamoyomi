import hashlib
import json
import random
import sys

from PIL import Image
import pytest

from scraper.exhibition_segments import SEGMENTS, fit_crossing, frame_loader, measure, usable_frames
from scraper.turn_measurement import digest
from tools.measure_exhibition import inventory, main, output_lock, run_batch, scan_camera, template
from tools.exhibition_review_sheet import build_sheets


LAP_EVIDENCE = {"lap": 1, "file": "f_000.png", "method": "broadcast_caption"}


def setup_capture(tmp_path):
    rng = random.Random(19)
    image = Image.frombytes("L", (96, 96), rng.randbytes(96 * 96))
    calibration = tmp_path / "calibration.png"
    image.save(calibration)
    profile = {
        "schema": 1, "venue": "04", "id": "test-fixed-shot", "lap": 1,
        "image_size": [96, 96], "anchors": [[25, 25], [70, 25], [50, 70]],
        "calibration_sha256": hashlib.sha256(calibration.read_bytes()).hexdigest(),
        "max_bow_pixels_per_video_second": 60, "max_crossing_fit_residual_pixels": 3,
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
            "screenshot": {"width": 96, "height": 96},
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
        observations.append({"file": name, "bow": [12 + n * 2.5, 50]})
    return manifest, profile, observations


def write_json(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_fixed_shot_times_and_safe_batch_rerun(tmp_path, monkeypatch):
    manifest, profile, observations = setup_capture(tmp_path)
    manifest_path = write_json(tmp_path / "manifest.json", manifest)
    profile_path = write_json(tmp_path / "profile.json", profile)
    review = template(manifest_path, profile_path)
    review.update(window=[199, 203], camera_reference="f_000.png", camera_layout_reviewed=True,
                  lap_evidence=LAP_EVIDENCE,
                  boats={"1": observations},
                  identity={"1": {"boat": 1, "method": "boat_color", "file": "f_000.png"}})
    write_json(tmp_path / "review.json", review)
    queue = write_json(tmp_path / "queue.json", {"jobs": [
        {"date": "20261112", "venue": "04", "race": 12, "manifest": "manifest.json",
         "profile": "profile.json", "review": "review.json", "calibration": "calibration.png"},
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
    write_json(tmp_path / "review.json", {**review, "boats": {"2": observations},
               "identity": {"2": {"boat": 2, "method": "boat_color", "file": "f_000.png"}}})
    candidate = run_batch(queue, out)["races"][0]
    assert candidate["status"] == "candidate_saved"
    assert [1, "turn_entry"] in [list(v) for v in candidate["section_difference"]["removed"]]
    assert path.read_bytes() == before
    monkeypatch.setattr(sys, "argv", ["measure_exhibition", "measure", "--manifest", str(manifest_path),
                                    "--profile", str(profile_path), "--review", str(tmp_path / "review.json"),
                                    "--calibration", str(tmp_path / "calibration.png"), "--output", str(path)])
    main()
    assert path.read_bytes() == before
    assert len(list((out / ".exhibition-versions" / path.name).glob("*.json"))) == 2
    jobs = json.loads(queue.read_text())
    jobs["jobs"][0]["replacement_reason"] = "corrected boat label"
    jobs["jobs"][0]["replacement_version"] = "stale"
    write_json(queue, jobs)
    assert run_batch(queue, out)["races"][0]["reason"] == "replacement_must_name_exact_candidate_version"
    assert path.read_bytes() == before
    jobs["jobs"][0]["replacement_version"] = candidate["candidate_version"]
    write_json(queue, jobs)
    assert run_batch(queue, out)["races"][0]["status"] == "reference"
    assert json.loads(path.read_bytes())["revision"]["history"][0]["replacement_reason"] == "corrected boat label"
    summary = (out / "summary.json").read_bytes()
    with output_lock(out) as acquired:
        assert acquired
        assert run_batch(queue, out)["status_counts"] == {"already_running": 1}
    assert (out / "summary.json").read_bytes() == summary


def test_camera_cut_inside_section_and_duplicate_time(tmp_path):
    manifest, profile, observations = setup_capture(tmp_path)
    review = {"schema": 1, "manifest_sha256": "test", "profile_sha256": digest(profile),
              "camera_layout_reviewed": True,
              "lap_evidence": LAP_EVIDENCE,
              "camera_reference": "f_000.png", "window": [199, 203], "boats": {"1": observations},
              "identity": {"1": {"boat": 1, "method": "visible_number", "file": "f_000.png"}}}
    options = {"manifest_sha256": "test", "calibration": tmp_path / "calibration.png"}
    path = tmp_path / "f_006.png"
    Image.new("L", (96, 96), 0).save(path)
    assert measure(manifest, profile, review, tmp_path, **options)[
        "boats"][0]["segments"]["turn_total"]["status"] == "frame_sha256_mismatch"
    manifest["frames"][6]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    result = measure(manifest, profile, review, tmp_path, **options)
    assert result["boats"][0]["segments"]["turn_total"]["status"] == "camera_landmark_changed_in_section"
    manifest["frames"][6]["frame"]["mediaTime"] = manifest["frames"][5]["frame"]["mediaTime"]
    assert {"f_005.png", "f_006.png"}.isdisjoint(usable_frames(manifest))
    result = measure(manifest, profile, review, tmp_path, **options)
    assert result["boats"][0]["segments"]["turn_total"]["status"] == "frame_gap_in_section"


def test_unrelated_calibration_duplicate_and_sparse_tracks_are_rejected(tmp_path):
    manifest, profile, observations = setup_capture(tmp_path)
    evidence = {"boat": 1, "method": "visible_number", "file": "f_000.png"}
    review = {"schema": 1, "manifest_sha256": "test", "profile_sha256": digest(profile),
              "camera_layout_reviewed": True, "camera_reference": "f_000.png", "window": [199, 203],
              "lap_evidence": LAP_EVIDENCE,
              "boats": {"1": observations, "2": observations}, "identity": {"1": evidence}}
    options = {"manifest_sha256": "test", "calibration": tmp_path / "calibration.png"}
    with pytest.raises(ValueError, match="lap_caption_evidence_required"):
        measure(manifest, profile, {**review, "lap_evidence": {**LAP_EVIDENCE, "lap": 2}},
                tmp_path, **options)
    result = measure(manifest, profile, review, tmp_path, **options)
    assert all(b["missing_crossings"]["A"] == ["overlapping_boat_tracks"] for b in result["boats"][:2])
    review["boats"] = {"1": [r for i, r in enumerate(observations) if i != 6]}
    result = measure(manifest, profile, review, tmp_path, **options)
    assert result["boats"][0]["segments"]["turn_total"]["status"] == "bow_track_missing_in_section"
    review["boats"] = {"1": [{**r, "bow": [27, 80]} if i == 6 else r
                             for i, r in enumerate(observations)]}
    result = measure(manifest, profile, review, tmp_path, **options)
    assert result["boats"][0]["segments"]["turn_total"]["status"] == "bow_track_jump_in_section"
    reference = tmp_path / "f_000.png"
    Image.new("L", (96, 96), 0).save(reference)
    manifest["frames"][0]["sha256"] = hashlib.sha256(reference.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="capture_does_not_match_camera_calibration"):
        measure(manifest, profile, review, tmp_path, **options)


def test_io_error_does_not_block_other_jobs_and_sheet_can_be_repeated(tmp_path, monkeypatch):
    manifest, profile, _ = setup_capture(tmp_path)
    manifest_path = write_json(tmp_path / "manifest.json", manifest)
    output = tmp_path / "sheets"
    first = build_sheets(manifest_path, output, 200, 200.1, None, 1, 2)
    second = build_sheets(manifest_path, output, 200, 200.1, None, 1, 2)
    assert first[0] == second[0] == 2
    assert first[1] != second[1]
    assert all((directory / "sheet-001.jpg").is_file() for _, directory in (first, second))
    inputs = {key: key for key in ("manifest", "profile", "review", "calibration")}
    jobs = [{"date": "20261112", "venue": "04", "race": 11, **inputs, "manifest": "blocked"},
            {"date": "20261112", "venue": "04", "race": 12, **inputs}]

    def sample(path, *_):
        if path.name == "blocked":
            raise PermissionError("fixture")
        return {"date": "20261112", "venue": "04", "race": 12, "lap": 1,
                "coverage": dict.fromkeys(SEGMENTS, 0), "boats": []}

    monkeypatch.setattr("tools.measure_exhibition.measure_files", sample)
    queue = write_json(tmp_path / "queue.json", {"jobs": jobs})
    assert run_batch(queue, tmp_path / "out")["status_counts"] == {
        "input_io_error": 1, "no_usable_sections": 1,
    }


def test_camera_scan_reports_matching_and_tampered_frames(tmp_path):
    manifest, profile, _ = setup_capture(tmp_path)
    manifest_path = write_json(tmp_path / "manifest.json", manifest)
    profile_path = write_json(tmp_path / "profile.json", profile)
    Image.new("L", (96, 96), 0).save(tmp_path / "f_006.png")
    result = scan_camera(manifest_path, profile_path, tmp_path / "calibration.png")
    assert result["status_counts"] == {"match": 22, "frame_sha256_mismatch": 1}


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


def test_video_coordinate_space_accepts_two_viewports_and_rejects_wrong_metadata(tmp_path):
    size = (96, 96)
    video = Image.new("L", size, 50)
    video.paste(200, (24, 24, 72, 72))
    captures = {}
    for i, (viewport, offset) in enumerate([((106, 110), (5, 7)), ((124, 108), (14, 6))]):
        frame = Image.new("L", viewport)
        frame.paste(video, offset)
        name = f"f_{i:03}.png"
        path = tmp_path / name
        frame.save(path)
        x, y = offset
        captures[name] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                          "video_layout": {"viewport": list(viewport), "native": list(size),
                                           "box": [x, y, x + size[0], y + size[1]]}}
    load = frame_loader(tmp_path, size, captures, coordinate_space="video")
    assert all(load(name).tobytes() == video.tobytes() for name in captures)
    captures["f_000.png"]["video_layout"]["viewport"][0] += 1
    with pytest.raises(ValueError, match="video_layout_dimensions_mismatch"):
        frame_loader(tmp_path, size, captures, coordinate_space="video")("f_000.png")


def test_crossing_fit_preserves_wider_observation_bracket_for_small_disagreement():
    points = [
        {"file": str(i), "time": t, "x": x, "y": y}
        for i, (t, x, y) in enumerate([(250.466667, 752.5, 361), (250.5, 741.5, 357),
                                       (250.6, 733.5, 350), (250.666667, 730.5, 347),
                                       (250.7, 727.5, 345.5)])
    ]
    order = {point["file"]: i for i, point in enumerate(points)}
    gate = {"axis": "y", "value": 351, "direction": -1, "segment": [700, 935]}
    when, residual, left, right = fit_crossing(points, points[1], points[2], gate, 4, 900, order)
    assert when == pytest.approx(250.603653)
    assert (left["time"], right["time"]) == (250.5, 250.666667)
    assert residual == pytest.approx(1.237, abs=.001)
    with pytest.raises(ValueError, match="crossing_fit_residual_too_high"):
        fit_crossing(points, points[1], points[2], gate, 1, 900, order)
