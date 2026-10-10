"""Prospective research candidates where the inside boat wins with a course-3 specialist.

This is a fixed, separate observation protocol. It never changes the adopted
ticket or promotes old records into verified pre-deadline results.
"""
from __future__ import annotations

import math

from .odds import COMBOS

PROTOCOL = "in_survivor_value_v1"
PARAMS = {"min_in_probability": .60, "min_in_starts": 20, "min_in_escape": .65,
          "min_third_starts": 20, "min_third_win": .15, "min_probability": .005,
          "min_odds": 100., "min_expected_return": 1.10, "max_tickets": 2}


def qualifies(ev):
    return bool(ev and (ev.get("in_model_win") or 0) >= PARAMS["min_in_probability"]
                and (ev.get("in_starts") or 0) >= PARAMS["min_in_starts"]
                and (ev.get("in_escape") or 0) >= PARAMS["min_in_escape"]
                and (ev.get("third_starts") or 0) >= PARAMS["min_third_starts"]
                and (ev.get("third_win") or 0) >= PARAMS["min_third_win"])


def select(ev, probs, odds):
    if not qualifies(ev) or len(probs) != 120 or len(odds) != 120:
        return []
    if not all(isinstance(v, (float, int)) and not isinstance(v, bool) and math.isfinite(v) and v > 0 for v in odds):
        return []
    if not all(isinstance(v, (float, int)) and not isinstance(v, bool) and math.isfinite(v) and 0 <= v <= 1 for v in probs):
        return []
    if abs(sum(probs) - 1) > .002:
        return []
    candidates = []
    f1, f3 = str(ev["in_frame"]), str(ev["third_frame"])
    for combo, prob, price in zip(COMBOS, probs, odds):
        first, second, third_place = combo.split("-")
        if first != f1 or f3 not in (second, third_place):
            continue
        expected = prob * price
        if prob >= PARAMS["min_probability"] and price >= PARAMS["min_odds"] and expected >= PARAMS["min_expected_return"]:
            candidates.append({"combo": combo, "amount": 100, "probability": prob,
                               "odds": price, "expected_return": round(expected, 6)})
    return sorted(candidates, key=lambda x: (-x["expected_return"], x["combo"]))[:PARAMS["max_tickets"]]


def decision(race):
    p = race.get("prediction") or {}
    out = {"protocol": PROTOCOL, "simulation": True, "params": dict(PARAMS),
           "model_version": p.get("version"), "model_revision": p.get("model_revision"), "tickets": []}
    if p.get("stage") != "直前" or not p.get("model_revision"):
        return out
    by_course = {b.get("course"): b for b in p.get("boats", [])}
    inside, third = by_course.get(1), by_course.get(3)
    if not inside or not third:
        return out
    profiles = (p.get("course_stats") or {}).get("boats") or {}
    ip = profiles.get(str(inside["frame"])) or profiles.get(inside["frame"]) or {}
    tp = profiles.get(str(third["frame"])) or profiles.get(third["frame"]) or {}
    motor = (p.get("evidence") or {}).get(str(third["frame"])) or {}
    out["evidence"] = {"in_frame": inside["frame"], "in_starts": ip.get("starts"),
                       "in_escape": ip.get("win"), "in_model_win": inside.get("p_win"),
                       "third_frame": third["frame"], "third_starts": tp.get("starts"),
                       "third_win": tp.get("win"), "third_methods": tp.get("kimarite"),
                       "third_motor_ex_seconds": motor.get("motor_ex_seconds") if motor.get("motor_ready") else None,
                       "third_motor_as_of": motor.get("motor_as_of")}
    out["tickets"] = select(out["evidence"], p.get("p3") or [], (race.get("odds_pre") or {}).get("v") or [])
    return out
