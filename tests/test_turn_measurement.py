import copy
from datetime import datetime

import pytest

from scraper.turn_measurement import METHOD, assess_record, digest, evidence_digest, hull_centre, render_panel, seal_record


def record():
    anchors = {"mark": [50, 50], "pole": [10, 20], "bank": [85, 10]}
    gates = {"A": {"axis": "x", "value": 30, "direction": 1, "segment": [60, 90]},
             "B": {"axis": "y", "value": 50, "direction": -1, "segment": [60, 90]},
             "C": {"axis": "x", "value": 30, "direction": -1, "segment": [10, 40]}}
    boats, labels = [], {}
    for boat in range(1, 7):
        events = {}
        for gate, pts, coords in [("A", 10, [(29, 70), (31, 70)]),
                                  ("B", 30, [(70, 51), (70, 49)]),
                                  ("C", 50, [(31, 25), (29, 25)])]:
            frames = []
            for i, (x, y) in enumerate(coords):
                ident = gate + str(i)
                frames.append({"id": ident, "pts": pts+i, "anchors": copy.deepcopy(anchors), "obstructed": False})
                labels[f"{boat}:{ident}"] = {"bow": [x-5, y], "stern": [x+5, y]}
            events[gate] = frames
        boats.append({"boat": boat, "events": events})
    evidence = {"source": {"sha256": "a"*64, "clock": "decoded_pts", "time_base": [1, 30],
                           "origin_verified": True, "editing_speed_verified": True},
                "image_size": [100, 100], "camera_reference": anchors, "gates": gates, "boats": boats}
    result = {"schema": 2, "method": METHOD, "venue": "04", "turn": "1-mark", "race_id": "20261026-04-1",
            "captured_at": "2026-10-26T10:00:00+09:00", "deadline": "2026-10-26T10:10:00+09:00",
            "sealed_at": "2026-10-26T10:05:00+09:00", "evidence": evidence,
            "reviews": [{"reviewer": who, "evidence_digest": digest(evidence), "trajectory_checked": True,
                         "labels": copy.deepcopy(labels), "reviewed_at": "2026-10-26T10:04:00+09:00"}
                        for who in ("reviewer-1", "reviewer-2")]}
    refresh(result)
    return result


def refresh(r):
    for review in r["reviews"]: review["evidence_digest"] = evidence_digest(r)


def test_uses_hull_landmarks_not_rider_or_tracker_rectangle():
    assert hull_centre({"bow": [10, 20], "stern": [30, 40], "bbox": [0, 0, 99, 99]}, [100, 100]) == (20, 30)
    with pytest.raises(ValueError): hull_centre({"bow": [10, 20], "stern": [10, 20]}, [100, 100])


def test_clean_evidence_recomputes_times_and_keeps_release_off():
    r = record(); r["entry_seconds"] = 999
    out = assess_record(r)
    assert all(row["status"] == "checked_reference" for row in out["rows"])
    assert out["rows"][0]["entry_seconds"] == .7
    assert not out["publication_ready"] and not out["prediction_used"]
    assert render_panel(out) == ""
    assert "0.7" in render_panel(out, preview=True)
    assert assess_record(r, release_enabled=True)["publication_ready"]


@pytest.mark.parametrize("defect", ["camera", "clock", "occlusion", "gap", "order", "missing", "drift", "same_reviewer", "stale"])
def test_bad_evidence_never_leaks_candidate_seconds(defect):
    r = record(); f = r["evidence"]["boats"][0]["events"]["A"][0]
    if defect == "camera": f["anchors"]["mark"][0] += 8
    if defect == "clock": r["evidence"]["source"]["clock"] = "browser_currentTime"
    if defect == "occlusion": f["obstructed"] = True
    if defect == "gap": r["evidence"]["boats"][0]["events"]["A"][1]["pts"] += 8
    if defect == "order": f["pts"] = 99
    if defect == "missing": del r["reviews"][1]["labels"]["1:A0"]
    if defect == "drift": r["reviews"][1]["labels"]["1:A0"]["bow"][1] += 15
    if defect == "same_reviewer": r["reviews"][1]["reviewer"] = "reviewer-1"
    if defect != "stale": refresh(r)
    else: f["pts"] += 1
    result = assess_record(r, release_enabled=True)
    assert not result["publication_ready"]
    assert "entry_seconds" not in result["rows"][0]
    assert "要再測定" in render_panel(result, preview=True)


def test_fully_collinear_markers_do_not_prove_fixed_camera():
    r = record(); refs = {"a": [10, 10], "b": [20, 10], "c": [30, 10]}
    r["evidence"]["camera_reference"] = refs
    for boat in r["evidence"]["boats"]:
        for pair in boat["events"].values():
            for frame in pair: frame["anchors"] = refs
    refresh(r)
    assert "camera_anchors_collinear" in str(assess_record(r)["rows"][0]["reasons"])


def test_bad_or_missing_independent_review_and_nan_cannot_pass():
    r = record(); r["reviews"] = r["reviews"][:1]
    assert not assess_record(r, release_enabled=True)["publication_ready"]
    with pytest.raises(ValueError): digest({"x": float("nan")})


@pytest.mark.parametrize("field,value", [("captured_at", "2026-10-26T10:11:00+09:00"),
                                          ("sealed_at", "2026-10-26T10:12:00+09:00"),
                                          ("sealed_at", "2026-10-26T10:05:00")])
def test_legacy_or_postdeadline_data_cannot_be_promoted(field, value):
    r = record(); r[field] = value
    assert not assess_record(r, release_enabled=True)["publication_ready"]


def test_review_after_seal_is_not_predeadline_evidence():
    r = record(); r["reviews"][0]["reviewed_at"] = "2026-10-26T10:11:00+09:00"
    assert not assess_record(r, release_enabled=True)["publication_ready"]


def test_reviews_cannot_be_reused_for_another_race_or_deadline():
    for key, value in [("race_id", "20261026-04-2"), ("deadline", "2026-10-26T10:20:00+09:00")]:
        r = record(); r[key] = value
        assert not assess_record(r, release_enabled=True)["publication_ready"]


def test_precise_clock_does_not_prove_original_source_or_unedited_speed():
    for key in ('origin_verified', 'editing_speed_verified'):
        r = record(); r['evidence']['source'][key] = False; refresh(r)
        assert not assess_record(r, release_enabled=True)['publication_ready']


def test_immutable_writer_and_no_late_backfill(tmp_path):
    path = tmp_path / "measurement.json"; r = record(); now = datetime.fromisoformat(r["sealed_at"])
    saved = seal_record(r, path, now=now)
    assert not saved["report"]["publication_ready"]
    before = path.read_bytes()
    with pytest.raises(FileExistsError): seal_record(r, path, now=now)
    with pytest.raises(ValueError): seal_record(r, path, now=datetime.fromisoformat(r["deadline"]))
    assert before == path.read_bytes()


def test_names_are_escaped_and_status_has_no_rank_or_power_claims():
    panel = render_panel(assess_record(record()), {1: '<script>bad</script>'}, preview=True)
    assert '<script>' not in panel and '&lt;script&gt;' in panel
    assert panel.count('<tr>') == 7
