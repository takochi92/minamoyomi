"""Versioned evidence contract for Heiwajima exhibition video measurements.

Independent of forecasting and settlement. The default release switch is OFF.
The schema supports decoded video PTS, fixed-image gates and two hull landmarks,
not tracker rectangles. Browser-clock legacy samples remain research-only.
"""
from __future__ import annotations

import hashlib
import html
import json
import math
import re
from datetime import datetime, timezone

METHOD = "heiwajima-hull-gates-v1"
# Provisional engineering limits; empirical timing accuracy is NOT established.
MAX_PAIR_GAP = .12
MAX_ANCHOR_DRIFT_PX = 2
MAX_REVIEW_DISAGREEMENT_PX = 3


def crossing(a, b, gate):
    axis = gate["axis"]
    other = "y" if axis == "x" else "x"
    start, end = a[axis], b[axis]
    value = gate["value"]
    if not (start < value <= end if gate["direction"] == 1 else start > value >= end):
        return None
    fraction = (value - start) / (end - start)
    position = a[other] + fraction * (b[other] - a[other])
    if not gate["segment"][0] <= position <= gate["segment"][1]:
        return None
    return a["time"] + fraction * (b["time"] - a["time"])


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def evidence_digest(record):
    """Bind reviews to race identity and timing as well as images and gates."""
    keys = ("schema", "method", "venue", "turn", "race_id", "captured_at", "deadline", "evidence")
    return digest({key: record.get(key) for key in keys})


def _xy(value, size):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError("landmark_missing")
    x, y = value
    if any(isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) for n in value):
        raise ValueError("landmark_invalid")
    if not 0 <= x < size[0] or not 0 <= y < size[1]:
        raise ValueError("landmark_outside_image")
    return x, y


def hull_centre(annotation, size):
    bow, stern = _xy(annotation.get("bow"), size), _xy(annotation.get("stern"), size)
    if math.dist(bow, stern) < 8:
        raise ValueError("hull_landmarks_too_close")
    return tuple((a + b) / 2 for a, b in zip(bow, stern))


def _time(frame, source):
    pts = frame.get("pts")
    base = source.get("time_base", [])
    if (source.get("clock") != "decoded_pts" or type(pts) is not int or pts < 0
            or len(base) != 2 or any(type(v) is not int or v <= 0 for v in base)):
        raise ValueError("decoded_frame_clock_required")
    return pts * base[0] / base[1]


def _camera(frame, references, size):
    # Fixed camera only in v1. No invented correction during a pan or zoom.
    if len(references) < 3 or set(references) != set(frame.get("anchors", {})):
        raise ValueError("camera_anchors_missing")
    refs = [_xy(v, size) for v in references.values()]
    # All markers on a single boom cannot reveal all image changes.
    area = max(abs((b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]))
               for a in refs for b in refs for c in refs)
    if area < 100:
        raise ValueError("camera_anchors_collinear")
    if any(math.dist(_xy(frame["anchors"][key], size), _xy(ref, size)) > MAX_ANCHOR_DRIFT_PX
           for key, ref in references.items()):
        raise ValueError("camera_moved")


def _aware(text):
    value = datetime.fromisoformat(text)
    if value.utcoffset() is None:
        raise ValueError("timezone_required")
    return value


def assess_record(record, *, release_enabled=False):
    """Recompute from evidence, never trust stored seconds or status strings.

    release_enabled is a deployment decision outside the submitted record, and
    must remain false until independent-race accuracy and ingest are validated.
    """
    if record.get("schema") != 2 or record.get("method") != METHOD:
        raise ValueError("unsupported_measurement_schema")
    if record.get("venue") != "04" or record.get("turn") != "1-mark":
        raise ValueError("heiwajima_first_mark_only")
    evidence = record["evidence"]
    if not re.fullmatch(r"\d{8}-04-(?:[1-9]|1[0-2])", str(record.get("race_id", ""))):
        raise ValueError("invalid_race_identity")
    fingerprint = evidence_digest(record)
    size, source = evidence["image_size"], evidence["source"]
    if len(size) != 2 or any(type(v) is not int or v <= 0 for v in size):
        raise ValueError("invalid_image_size")
    gates = evidence["gates"]
    if set(gates) != set("ABC"):
        raise ValueError("three_fixed_gates_required")
    for gate in gates.values():
        if gate.get("axis") not in ("x", "y") or gate.get("direction") not in (-1, 1):
            raise ValueError("invalid_gate")
        axis = 0 if gate["axis"] == "x" else 1
        if not (0 <= gate["value"] < size[axis] and
                0 <= gate["segment"][0] < gate["segment"][1] < size[1-axis]):
            raise ValueError("gate_outside_image")
    reviews = record.get("reviews", [])
    good_reviews = [r for r in reviews if r.get("evidence_digest") == fingerprint
                    and r.get("trajectory_checked") is True and r.get("reviewer")]
    # Reviewer strings identify work sessions, not an authentication mechanism.
    reviewers = {r["reviewer"] for r in good_reviews}
    shared = []
    if len(good_reviews) != 2 or len(reviewers) != 2:
        shared.append("two_matching_independent_reviews_required")
    if source.get("clock") != "decoded_pts":
        shared.append("decoded_frame_clock_required")
    if not re.fullmatch(r"[0-9a-f]{64}", str(source.get("sha256", ""))):
        shared.append("source_fingerprint_missing")
    try:
        captured, sealed, deadline = map(_aware, (record["captured_at"], record["sealed_at"], record["deadline"]))
        predeadline = captured <= sealed < deadline and all(
            captured <= _aware(r["reviewed_at"]) <= sealed for r in good_reviews)
    except (KeyError, ValueError, TypeError):
        predeadline = False
    rows = []
    boats = evidence.get("boats", [])
    if sorted(b.get("boat", 0) for b in boats) != list(range(1, 7)):
        raise ValueError("six_distinct_boats_required")
    for boat in sorted(boats, key=lambda b: b["boat"]):
        reasons = list(shared)
        events = {}
        for name in "ABC":
            try:
                pair = boat["events"][name]
                if len(pair) != 2:
                    raise ValueError("two_bracketing_frames_required")
                samples = []
                for frame in pair:
                    _camera(frame, evidence.get("camera_reference", {}), size)
                    if frame.get("obstructed") is not False:
                        raise ValueError("hull_obstructed_or_unchecked")
                    ident = str(boat["boat"]) + ":" + str(frame["id"])
                    labels = [r.get("labels", {}).get(ident) for r in good_reviews]
                    if len(labels) != 2 or any(not label for label in labels):
                        raise ValueError("hull_review_missing")
                    # Compare endpoints individually: matching midpoints alone
                    # would allow two wrong but symmetrical annotations.
                    for endpoint in ("bow", "stern"):
                        if math.dist(_xy(labels[0].get(endpoint), size),
                                     _xy(labels[1].get(endpoint), size)) > MAX_REVIEW_DISAGREEMENT_PX:
                            raise ValueError("reviewers_disagree")
                    centres = [hull_centre(label, size) for label in labels]
                    x, y = ((centres[0][i] + centres[1][i]) / 2 for i in (0, 1))
                    samples.append({"time": _time(frame, source), "x": x, "y": y})
                gap = samples[1]["time"] - samples[0]["time"]
                if not 0 < gap <= MAX_PAIR_GAP:
                    raise ValueError("frame_gap_or_time_reversal")
                event_time = crossing(samples[0], samples[1], gates[name])
                if event_time is None:
                    raise ValueError("gate_not_bracketed")
                events[name] = {"time": event_time, "before": samples[0]["time"],
                                "after": samples[1]["time"]}
            except (KeyError, TypeError, IndexError, ValueError) as exc:
                reasons.append(name + ":" + (str(exc) if isinstance(exc, ValueError) else "evidence_missing"))
        if len(events) == 3 and not events["A"]["after"] < events["B"]["before"] < events["B"]["after"] < events["C"]["before"]:
            reasons.append("overlapping_or_reversed_intervals")
        if len(events) == 3:
            gaps = {key: event["after"] - event["before"] for key, event in events.items()}
            if max((gaps["A"] + gaps["B"]) / 2, (gaps["B"] + gaps["C"]) / 2) > .1:
                reasons.append("sampling_interval_too_wide")
        row = {"boat": boat["boat"], "status": "remeasure" if reasons else "checked_reference",
               "reasons": list(dict.fromkeys(reasons)), "events": events}
        if not reasons:
            row["entry_seconds"] = round(events["B"]["time"] - events["A"]["time"], 1)
            row["exit_seconds"] = round(events["C"]["time"] - events["B"]["time"], 1)
        rows.append(row)
    return {"schema": 2, "method": METHOD, "race_id": record.get("race_id"),
            "evidence_digest": fingerprint, "rows": rows,
            "publication_ready": bool(release_enabled and predeadline and source.get('origin_verified') is True
                                      and source.get('editing_speed_verified') is True and all(not r["reasons"] for r in rows)),
            "predeadline": predeadline, "time_label": "映像内の区間秒数",
            "prediction_used": False, "release_enabled": release_enabled}


def seal_record(record, path, *, now=None):
    """Trusted writer: no overwrite, no postdeadline backfill, no stale reviews.

    Scheduling/authentication of reviewers is a separate operational concern.
    The deployment switch remains off even after a successful seal.
    """
    now = now or datetime.now(timezone.utc)
    candidate = {**record, "sealed_at": now.isoformat()}
    report = assess_record(candidate)
    if not report["predeadline"] or any(row["reasons"] for row in report["rows"]):
        raise ValueError("cannot_seal_unchecked_or_late_record")
    payload = {"record": candidate, "record_digest": digest(candidate), "report": report}
    # 'x' protects a previously fixed record, including across processes.
    with open(path, "x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, allow_nan=False)
    return payload


def render_panel(report, names=None, *, preview=False):
    """Compact six-row component. No failed times, rankings or inferred power."""
    if not preview and not report.get("publication_ready"):
        return ""
    names = names or {}
    rows = []
    for row in report["rows"]:
        valid = row["status"] == "checked_reference"
        a, b = (f'{row["entry_seconds"]:.1f}', f'{row["exit_seconds"]:.1f}') if valid else ("—", "—")
        label = "確認済み" if valid else "要再測定"
        reason = "; ".join(row.get("reasons", []))
        number = row["boat"]
        rows.append(f'<tr><th scope="row"><span class="tm-boat tm-b{number}">{number}</span>'
                    f'<span>{html.escape(str(names.get(number, "")))}</span></th><td>{a}</td><td>{b}</td><td title="{html.escape(reason, quote=True)}">{label}</td></tr>')
    return ('<section class="tm-panel" aria-label="１マーク区間計測"><div class="tm-heading">'
            '<h2>１マーク区間計測</h2><span>確認用</span></div>'
            '<p>全艇共通の線で、入りと出口を比較</p>'
            '<table><thead><tr><th>艇・選手</th><th>入り<span>秒</span></th><th>出口<span>秒</span></th><th>確認</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>'
            '<details><summary>測り方と注意点</summary><p>艇首と艇尾の中点で、進入線→マーク横線、マーク横線→出口線を計測。'
            '映像内の秒数で、実距離・出足順位ではありません。測れない艇は数値を出しません。</p></details></section>')
