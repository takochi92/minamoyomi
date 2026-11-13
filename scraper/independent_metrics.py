"""Independent (video-measured) exhibition metrics: store, rider adjustment and venue-relative grades.

The measurement itself happens elsewhere. This module only receives numbers and turns them into
motor ratings, so every rule that protects the ratings lives here and is covered by tests:

* a row is accepted only with a complete identity (date, venue, race, boat, motor, rider, metric)
* rows are compared inside one race, never as raw seconds across races or venues
* what a rider usually does is SUBTRACTED and never added. A rating must not favour a strong rider:
  the purpose is to find a good motor under a rider the public does not fancy
* rows older than the venue's current motor fleet are never used, and a venue with an unknown or
  pending fleet start produces nothing
* ratings read the latest three finished meetings; old meetings are not accumulated forever
* a metric that cannot be rated stays absent. Nothing is filled with a guess

See research/improvements/INDEPENDENT_METRICS.md.
"""
from __future__ import annotations

import contextlib
import json
import math
import os
import re
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from statistics import median
from tempfile import NamedTemporaryFile

SCHEMA = 1
VENUES = frozenset(f"{n:02}" for n in range(1, 25))
# Column of the Premium table -> metric names a measurement may report for it.
METRICS = ("exhibition", "straight", "turn", "acceleration")
SOURCES = ("video",)
MIN_BOATS_IN_RACE = 2          # one boat alone says nothing about the others; two or more can be compared
MIN_SHARE_OF_STARTS = .4       # a motor needs this share of its starts measured, or the misses may be biased
RECENT_MEETINGS = 3
MIN_RUNS = 6
MIN_DAYS = 3
MIN_RIDERS = 2                 # one rider cannot be separated from the motor
MIN_FIELD = 12
HALF_LIFE_DAYS = 45
RIDER_SHRINK_RUNS = 8
RIDER_HALF_LIFE_DAYS = 180
MEETING_GAP_DAYS = 2           # a longer pause starts another meeting when no schedule is given
MAX_FIT_RESIDUAL_PIXELS = 6.0
MIN_FIT_POINTS = 6


def day(value):
    if not isinstance(value, str) or not re.fullmatch(r"20[0-9]{6}", value):
        raise ValueError("expected YYYYMMDD")
    return date(int(value[:4]), int(value[4:6]), int(value[6:8]))


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


# ------------------------------------------------------------------ measurement: robust crossing time
def robust_crossing(points, gate_value, direction, *, max_residual=MAX_FIT_RESIDUAL_PIXELS,
                    min_points=MIN_FIT_POINTS):
    """Time at which a tracked point passes a gate, from many frames instead of the two around it.

    `points` are (time_seconds, position_along_the_gate_axis). A robust line (median of pairwise
    slopes) finds the boat first, frames that sit far from it (spray, a mis-tracked frame) are dropped,
    and a least-squares line is fitted to the rest.
    Returns None when the fit is not trustworthy: too few frames, movement in the wrong direction,
    a gate outside the observed positions, or a residual above `max_residual` pixels.
    """
    rows = sorted((t, x) for t, x in points if finite(t) and finite(x))
    if len(rows) < min_points or len({t for t, _ in rows}) != len(rows) or direction not in (-1, 1):
        return None

    def fit(data):
        mt = sum(t for t, _ in data) / len(data)
        mx = sum(x for _, x in data) / len(data)
        var = sum((t - mt) ** 2 for t, _ in data)
        if var <= 0:
            return None
        slope = sum((t - mt) * (x - mx) for t, x in data) / var
        return slope, mt, mx, [x - (mx + slope * (t - mt)) for t, x in data]

    def theil_sen(data):
        # Median of pairwise slopes: stays on the boat when up to about a quarter of the frames sit on
        # spray, which is always on one side (behind the boat) and would drag a least-squares line.
        slopes = sorted((x2 - x1) / (t2 - t1) for i, (t1, x1) in enumerate(data) for t2, x2 in data[i + 1:])
        slope = slopes[len(slopes) // 2]
        offset = median(x - slope * t for t, x in data)
        return [x - (slope * t + offset) for t, x in data]

    kept = rows
    residuals = theil_sen(rows)
    for _ in range(3):
        spread = median(abs(r) for r in residuals)
        limit = max(3 * 1.4826 * spread, 1.0)
        trimmed = [row for row, r in zip(kept, residuals) if abs(r) <= limit]
        if len(trimmed) < min_points:
            return None
        if len(trimmed) == len(kept):
            break
        kept = trimmed
        residuals = fit(kept)[3]
    if fit(kept) is None:
        return None
    slope, mt, mx, residuals = fit(kept)
    if slope * direction <= 0:
        return None
    residual = math.sqrt(sum(r * r for r in residuals) / (len(kept) - 2))
    low, high = min(x for _, x in kept), max(x for _, x in kept)
    if residual > max_residual or not low <= gate_value <= high:
        return None
    return {"seconds": mt + (gate_value - mx) / slope, "points": len(kept),
            "rejected": len(rows) - len(kept), "residual_pixels": round(residual, 2),
            "pixels_per_second": round(abs(slope), 1)}


# ------------------------------------------------------------------ rows and store
def clean_row(row):
    """Validated copy of one measured value. Raises ValueError with a short reason."""
    if not isinstance(row, dict) or row.get("schema", SCHEMA) != SCHEMA:
        raise ValueError("unsupported_row")
    day(row.get("date"))
    venue, race, boat, motor = row.get("venue"), row.get("race"), row.get("boat"), row.get("motor")
    rider, metric, seconds = row.get("rider"), row.get("metric"), row.get("seconds")
    if venue not in VENUES or type(race) is not int or not 1 <= race <= 12:
        raise ValueError("invalid_race_identity")
    if type(boat) is not int or not 1 <= boat <= 6 or type(motor) is not int or not 1 <= motor <= 999:
        raise ValueError("invalid_boat_or_motor")
    if not isinstance(rider, str) or not re.fullmatch(r"\d{4}", rider):
        raise ValueError("invalid_rider")
    if metric not in METRICS or row.get("source") not in SOURCES:
        raise ValueError("invalid_metric_or_source")
    if not finite(seconds) or not 0 < seconds < 120:
        raise ValueError("invalid_seconds")
    profile = row.get("profile")
    if not isinstance(profile, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", profile):
        raise ValueError("invalid_profile")        # which gates/camera produced the value
    parts = row.get("parts", [])
    if not isinstance(parts, list) or any(not isinstance(p, str) or len(p) > 20 for p in parts) or len(parts) > 10:
        raise ValueError("invalid_parts")
    return {"schema": SCHEMA, "date": row["date"], "venue": venue, "race": race, "boat": boat,
            "motor": motor, "rider": rider, "metric": metric, "source": row["source"],
            "seconds": round(float(seconds), 4), "profile": profile, "parts": parts}


def row_key(row):
    return row["date"], row["venue"], row["race"], row["boat"], row["metric"], row["source"]


@contextlib.contextmanager
def _locked(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0, 2)
        if not handle.tell():
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


class Store:
    """Private, append-safe storage: <root>/<venue>/<YYYYMM>.jsonl, one measured value per line."""

    def __init__(self, root):
        self.root = Path(root).resolve()

    def _file(self, venue, month):
        return self.root / venue / f"{month}.jsonl"

    def _read(self, path):
        if not path.is_file():
            return {}
        rows = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = clean_row(json.loads(line))
                rows[row_key(row)] = row
        return rows

    def upsert(self, rows):
        """Add or correct values. Running it twice with the same input changes nothing.

        Returns counts. Invalid rows are counted and skipped; they never stop the valid ones.
        A value measured with another profile for the same boat replaces the earlier one.
        """
        groups, counts = defaultdict(dict), {"added": 0, "replaced": 0, "unchanged": 0, "invalid": 0}
        for raw in rows:
            try:
                row = clean_row(raw)
            except (ValueError, TypeError, KeyError):
                counts["invalid"] += 1
                continue
            groups[row["venue"], row["date"][:6]][row_key(row)] = row
        with _locked(self.root / ".lock"):
            for (venue, month), incoming in sorted(groups.items()):
                path = self._file(venue, month)
                current = self._read(path)
                before = dict(current)
                for key, row in incoming.items():
                    counts["unchanged" if current.get(key) == row else "replaced" if key in current else "added"] += 1
                    current[key] = row
                if current != before:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    text = "".join(json.dumps(current[k], ensure_ascii=False, separators=(",", ":")) + "\n"
                                   for k in sorted(current))
                    with NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as f:
                        f.write(text)
                    os.replace(f.name, path)
        return counts

    def rows(self, since="20000101", through="20991231", venue=None):
        out = []
        for folder in sorted(self.root.iterdir()) if self.root.is_dir() else []:
            if folder.name not in VENUES or (venue and folder.name != venue):
                continue
            for path in sorted(folder.glob("??????.jsonl")):
                if since[:6] <= path.stem <= through[:6]:
                    out += [r for r in self._read(path).values() if since <= r["date"] <= through]
        return out


# ------------------------------------------------------------------ comparison inside a race
def race_deviations(rows, *, sweeps=12, shrink=4.0):
    """Each value minus the level of its race, per metric. Negative is quicker than the field.

    Not every boat of a race is measured (spray, overlap, a lost track). Subtracting the mean of the
    boats that happen to be measured would punish a motor for being measured next to quick ones, so
    the race level and the motor level are estimated together:

        seconds = race level + motor level + noise

    by alternating between the two (a motor with few runs is pulled toward the venue average). With
    all six boats measured this is the plain race mean. A race with one measured boat is dropped.
    """
    races = defaultdict(dict)
    for row in rows:
        races[row["date"], row["venue"], row["race"], row["metric"]][row["boat"]] = row
    usable = {}
    for key, boats in races.items():
        if len(boats) >= MIN_BOATS_IN_RACE and len({r["motor"] for r in boats.values()}) == len(boats):
            usable[key] = list(boats.values())
    by_field = defaultdict(list)                 # motors are only comparable inside a venue and metric
    for key in usable:
        by_field[key[1], key[3]].append(key)
    out = []
    for keys in by_field.values():
        motor_level = defaultdict(float)
        level = {}
        for _ in range(sweeps):
            for key in keys:
                boats = usable[key]
                level[key] = sum(r["seconds"] - motor_level[r["motor"]] for r in boats) / len(boats)
            sums = defaultdict(lambda: [0, 0.0])
            for key in keys:
                for r in usable[key]:
                    total = sums[r["motor"]]
                    total[0] += 1
                    total[1] += r["seconds"] - level[key]
            motor_level = defaultdict(float, {m: total / (n + shrink) for m, (n, total) in sums.items()})
            centre = sum(motor_level.values()) / len(motor_level)
            for m in motor_level:
                motor_level[m] -= centre
        for key in keys:
            out += [{**r, "delta": r["seconds"] - level[key], "boats_measured": len(usable[key])} for r in usable[key]]
    return out


def rider_baselines(deviations, through):
    """(rider, metric) -> what the rider usually shows against the field, from dates up to `through`.

    Newer runs weigh more and a rider with few runs is pulled toward zero (treated as average).
    """
    as_of = day(through)
    totals = defaultdict(lambda: [0.0, 0.0])
    for row in deviations:
        if row["date"] > through:
            continue
        weight = .5 ** ((as_of - day(row["date"])).days / RIDER_HALF_LIFE_DAYS)
        total = totals[row["rider"], row["metric"]]
        total[0] += weight
        total[1] += weight * row["delta"]
    return {key: total / (n + RIDER_SHRINK_RUNS) for key, (n, total) in totals.items()}


# ------------------------------------------------------------------ meetings and fleets
def meetings(dates, schedule=None):
    """Group race dates into meetings. `schedule` is [(start, end)] from the official calendar."""
    dates = sorted(set(dates))
    if schedule:
        spans = sorted(set(schedule))
        groups = [[d for d in dates if start <= d <= end] for start, end in spans]
        return [g for g in groups if g]
    groups = []
    for d in dates:
        if groups and (day(d) - day(groups[-1][-1])).days <= MEETING_GAP_DAYS:
            groups[-1].append(d)
        else:
            groups.append([d])
    return groups


def parts_changes(rows):
    """motor -> sorted dates on which the racecard reported replaced parts (for the current fleet)."""
    out = defaultdict(set)
    for row in rows:
        if row.get("parts"):
            out[row["motor"]].add(row["date"])
    return {motor: sorted(dates) for motor, dates in out.items()}


# ------------------------------------------------------------------ ratings
def grade_field(candidates, standout_gap):
    """Venue-relative grades. The best fifth is A, then B to 50%, C to 80% and D."""
    if len(candidates) < MIN_FIELD:
        return {}
    scores = sorted(c["delta"] for c in candidates.values())
    middle = median(scores)
    out = {}
    for motor, c in candidates.items():
        value = c["delta"]
        percentile = (sum(x < value for x in scores) + (scores.count(value) - 1) / 2) / (len(scores) - 1)
        grade = "A" if percentile <= .20 else "B" if percentile <= .50 else "C" if percentile <= .80 else "D"
        repeated = [(m, r) for m, r, d in c.pop("replication") if d <= middle - standout_gap]
        if (percentile <= .05 and value <= middle - standout_gap and len({m for m, _ in repeated}) >= 2
                and len({r for _, r in repeated}) >= 2):
            grade = "S"                                   # needs two meetings and two riders
        out[motor] = {**c, "grade": grade, "field": len(scores), "venue_delta": round(value - middle, 4)}
    return out


def venue_ratings(rows, venue, through, fleet_start, *, schedule=None, baselines=None,
                  standout_gap=.03, all_rows=None, starts=None):
    """Rider-adjusted, venue-relative ratings of one venue's current motors.

    rows        measured values (any venues; only `venue` is rated)
    fleet_start YYYYMMDD the current motors were first used. Rows before it are another motor with
                the same number and are dropped. None (unknown or pending) returns {}.
    baselines   precomputed rider baselines; by default they are built from `all_rows` or `rows`
    starts      {motor: number of exhibition runs it had in the rated meetings} from the racecards.
                With it, a motor measured on less than MIN_SHARE_OF_STARTS of its runs is not rated
    Returns {metric: {motor(str): rating}}.
    """
    if not fleet_start or fleet_start > through or venue not in VENUES:
        return {}
    devs_all = race_deviations([r for r in (all_rows if all_rows is not None else rows) if r["date"] <= through])
    if baselines is None:
        baselines = rider_baselines(devs_all, through)
    devs = [r for r in race_deviations([r for r in rows if r["venue"] == venue and fleet_start <= r["date"] <= through])]
    finished = [m for m in meetings((r["date"] for r in devs), schedule)
                if not schedule or next(end for start, end in schedule if start <= m[0] <= end) <= through]
    recent = finished[-RECENT_MEETINGS:]
    meet_of = {d: m[0] for m in recent for d in m}
    changed = parts_changes([r for r in rows if r["venue"] == venue and fleet_start <= r["date"] <= through])
    as_of = day(through)
    samples = defaultdict(list)
    for row in devs:
        if row["date"] in meet_of:
            adjusted = row["delta"] - baselines.get((row["rider"], row["metric"]), 0.0)
            samples[row["metric"], row["motor"]].append((row["date"], meet_of[row["date"]], row["rider"], adjusted))
    output = {}
    for metric in METRICS:
        candidates = {}
        for (key, motor), runs in samples.items():
            riders, days = {r for _, _, r, _ in runs}, {d for d, *_ in runs}
            if key != metric or len(runs) < MIN_RUNS or len(days) < MIN_DAYS or len(riders) < MIN_RIDERS:
                continue
            share = len(runs) / starts[motor] if starts and starts.get(motor) else None
            if share is not None and share < MIN_SHARE_OF_STARTS:
                continue
            weights = [.5 ** ((as_of - day(d)).days / HALF_LIFE_DAYS) for d, *_ in runs]
            by_pair = defaultdict(list)
            for _, meet, rider, value in runs:
                by_pair[meet, rider].append(value)
            last_change = max((d for d in changed.get(motor, []) if d <= through), default=None)
            candidates[str(motor)] = {
                "delta": round(sum(w * v for w, (*_, v) in zip(weights, runs)) / sum(weights), 4),
                "runs": len(runs), "riders": len(riders), "meetings": len({m for _, m, _, _ in runs}),
                "through": max(days), "source": "video", "rider_adjusted": True,
                "share_of_starts": round(share, 2) if share is not None else None,
                # Shown with the grade. Whether a change should reset the rating is not validated yet.
                "parts_changed": last_change,
                "runs_since_parts_change": sum(d > last_change for d, *_ in runs) if last_change else None,
                "replication": [(m, r, sum(v) / len(v)) for (m, r), v in by_pair.items() if len(v) >= 2],
            }
        graded = grade_field(candidates, standout_gap)
        if graded:
            output[metric] = graded
    return output


def fill_columns(official, independent):
    """Official numbers first; an independent rating fills a column only where the official one is absent.

    Both arguments are {motor: {metric: rating}}. Every filled cell says where it came from.
    """
    out = {}
    for motor in sorted(set(official) | set(independent)):
        cells = {}
        for metric in METRICS:
            if metric in official.get(motor, {}):
                cells[metric] = {"source": "official", **official[motor][metric]}
            elif metric in independent.get(motor, {}):
                cells[metric] = independent[motor][metric]
        if cells:
            out[motor] = cells
    return out


def by_motor(ratings):
    out = defaultdict(dict)
    for metric, motors in ratings.items():
        for motor, rating in motors.items():
            out[motor][metric] = rating
    return dict(out)


# ------------------------------------------------------------------ validation
def carry_over(deviations, fleet_starts, baselines=None, *, min_previous=6, min_next=3):
    """Does a motor's number from earlier riders predict the next rider's? Returns {metric: (n, r)}.

    Use it before publishing any new metric: a metric whose r is near zero describes the rider or
    the day, not the motor, and must not be shown as a motor rating.
    """
    series = defaultdict(list)
    for row in sorted(deviations, key=lambda r: (r["date"], r["race"])):
        if row["date"] >= fleet_starts.get(row["venue"], "99999999"):
            base = (baselines or {}).get((row["rider"], row["metric"]), 0.0)
            series[row["metric"], row["venue"], row["motor"]].append((row["date"], row["rider"], row["delta"] - base))
    pairs = defaultdict(list)
    for (metric, _, _), runs in series.items():
        stints = []
        for d, rider, value in runs:
            if stints and stints[-1][0] == rider and (day(d) - day(stints[-1][1])).days <= MEETING_GAP_DAYS:
                stints[-1][1] = d
                stints[-1][2].append(value)
            else:
                stints.append([rider, d, [value]])
        for i, (rider, _, values) in enumerate(stints):
            earlier = [v for r, _, vs in stints[:i] if r != rider for v in vs]
            if len(values) >= min_next and len(earlier) >= min_previous:
                pairs[metric].append((sum(earlier) / len(earlier), sum(values) / len(values)))
    out = {}
    for metric, xy in pairs.items():
        n = len(xy)
        mx, my = sum(x for x, _ in xy) / n, sum(y for _, y in xy) / n
        sx = math.sqrt(sum((x - mx) ** 2 for x, _ in xy))
        sy = math.sqrt(sum((y - my) ** 2 for _, y in xy))
        out[metric] = (n, round(sum((x - mx) * (y - my) for x, y in xy) / (sx * sy), 3) if sx and sy and n > 2 else None)
    return out


def previous_day(value):
    return (day(value) - timedelta(days=1)).strftime("%Y%m%d")
