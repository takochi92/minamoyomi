"""Build the private venue-relative motor preview from the official research archive."""
from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import re
import time
from tempfile import NamedTemporaryFile
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .research_snapshot import ROOT, archived_records

METRICS = {"exhibition": "展示", "straight": "直線", "turn": "まわり足"}
MIN_FIELD = 12
RESULT_TRIES_LIMIT = 12   # run.py が結果の取得をあきらめる回数
MIN_RUNS = 6
HALF_LIFE = 14
TRIAL_RATINGS = ("exhibition", "straight")
# Rider-adjusted exhibition (research/improvements/RIDER_ADJUSTED_MOTOR.md). The published snapshot
# only carries it when the build is asked to, because the Premium function must accept the key first.
ADJUSTED_HALF_LIFE = 45
RIDER_SHRINK_RUNS = 8
RIDER_TERM_DECAY = .5
# Official course maps document the early straight section at these venues.
CONFIRMED_EXIT_VENUES = {"02", "04", "07", "10", "14", "22"}
# Official documents do not show where 直線 is measured here, but 直線 − 展示 sorted the next day's
# results A<B<C<D (宮島: A and D only) and A beat D in every meeting, 2026/10/12〜11/14.
# Shown as 算出・区間未確認 (source "unconfirmed_section"). Not here: 桐生・浜名湖 failed that check;
# びわこ's official text puts 直線 on the back straight, not the turn exit.
UNCONFIRMED_EXIT_VENUES = {"05", "08", "09", "15", "16", "17", "19", "20", "21", "23", "24"}
EXIT_SECTION_VENUES = CONFIRMED_EXIT_VENUES | UNCONFIRMED_EXIT_VENUES
# The replay found clear A/D separation but unstable intermediate ordering here.
# Use B for the middle band rather than presenting two distinct grades.
MIDDLE_BAND_VENUES = {"turn": {"09", "12", "15"}, "overall": {"06", "22"}, "acceleration": {"17"}}
TWO_SECTION_VENUES = {"12", "13", "18"}
# These venues publish 一周 and まわり足 but no 直線. The rest of the lap (一周 − まわり足) is the
# straight running, so it stands in for 直線 there, marked with source "lap_minus_turn".
# At the venues that publish all three, it follows the official 直線 inside a race (rank
# correlation +0.11 to +0.50 by venue, 2026/09〜11), more closely than 直線 follows 展示.
LAP_MINUS_TURN_VENUES = {"12", "13", "18"}
# Edogawa publishes only the exhibition time. Straight and turn come from the BOATCAST replay,
# measured by tools.boatcast_measure (numbers only) and labelled as our own measurement.
# Own replay measurements fill an item only where the official one is missing for that race, and only
# with 4+ boats measured. Venues here passed a 12-race check of their profile (tools/boatcast/profiles,
# research/improvements/BOATCAST_PROFILES.md). Only scores built from video carry source "video".
VIDEO_VENUES = {"02", "03", "04", "05", "08", "09", "10", "11", "12", "13", "16", "17", "18", "22", "23"}
VIDEO_METRICS = ("straight", "turn")
VIDEO_MIN_BOATS = 4
VIDEO_DIR = ROOT / "research" / "boatcast-measure"


def day(value):
    if not re.fullmatch(r"20[0-9]{6}", value):
        raise ValueError("expected YYYYMMDD")
    return date(int(value[:4]), int(value[4:6]), int(value[6:8]))


def video_keys(race, venue):
    """(item, motor, rider) whose value in this race is the own replay measurement, not an official time."""
    used = set()
    if venue in VIDEO_VENUES and (race or {}).get("video"):
        for _ in _observations(race, venue, used):
            pass
    return used


def observations(race, venue=None):
    return _observations(race, venue, None)


def _observations(race, venue=None, from_video=None):
    boats = (race.get("racelist") or {}).get("boats") or []
    entries = {b["frame"]: b for b in boats if b.get("motor_no") and b.get("toban")}
    lanes = set(range(1, 7))
    if entries.keys() != lanes or len(boats) != 6 or len({b["motor_no"] for b in entries.values()}) != 6:
        return
    before = (race.get("before") or {}).get("boats") or []
    exhibition = {b["frame"]: b.get("exhibit_time") for b in before} if len(before) == 6 else {}
    ori = race.get("oriten") or {}
    labels, rows = ori.get("items", []), ori.get("rows", {})
    deviations = {}
    for key, label in {**METRICS, "lap": "半周ラップ" if venue == "01" else "一周"}.items():
        if key == "exhibition":
            values = [exhibition.get(i) for i in range(1, 7)]
        elif label in labels:
            col = labels.index(label)
            values = [next(iter((rows.get(str(i)) or [])[col:col+1]), None) for i in range(1, 7)]
        else:
            continue
        if not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and 0 < x < 120 for x in values):
            continue
        baseline = sum(values) / len(values)
        deviations[key] = [value - baseline for value in values]
    partial = {}
    if venue in VIDEO_VENUES:
        for key in VIDEO_METRICS:
            measured = {int(b): v for b, v in ((race.get("video") or {}).get(key) or {}).items()
                        if int(b) in lanes and isinstance(v, (int, float)) and math.isfinite(v) and 0 < v < 120}
            if key not in deviations and len(measured) >= VIDEO_MIN_BOATS:
                baseline = sum(measured.values()) / len(measured)
                partial[key] = {b: v - baseline for b, v in measured.items()}
    if partial:
        # Not every boat is measured in every replay: rank the overall among the boats that are.
        full = {k: dict(enumerate(v, 1)) for k, v in deviations.items()}
        full.update(partial)
        parts = ("exhibition", "straight", "turn")
        boats = [b for b in range(1, 7) if all(b in full.get(k, {}) for k in parts)]
        if len(boats) >= VIDEO_MIN_BOATS:
            weights = {"exhibition": .25, "straight": .25, "turn": .5}
            ranks = {}
            for k in parts:
                field = [full[k][b] for b in boats]
                ranks[k] = {b: (sum(x < full[k][b] for x in field) + (field.count(full[k][b]) - 1) / 2)
                            / (len(boats) - 1) for b in boats}
            partial["overall"] = {b: sum(weights[k] * ranks[k][b] for k in parts) - .5 for b in boats}
        for key, values in partial.items():
            for b, value in values.items():
                if from_video is not None:
                    # this value is the own replay measurement, not an official time
                    from_video.add((key, str(entries[b]["motor_no"]), str(entries[b]["toban"])))
                yield key, str(entries[b]["motor_no"]), str(entries[b]["toban"]), value
    if (venue in LAP_MINUS_TURN_VENUES and "straight" not in deviations
            and {"lap", "turn"} <= deviations.keys()):
        deviations["straight"] = [lap - turn for lap, turn in zip(deviations["lap"], deviations["turn"])]
    if venue in EXIT_SECTION_VENUES and {"straight", "exhibition"} <= deviations.keys():
        deviations["acceleration"] = [early - late for early, late in
                                      zip(deviations["straight"], deviations["exhibition"])]
    weights = {"exhibition": .5, "turn": .5} if venue in TWO_SECTION_VENUES else {
        "exhibition": .25, "straight": .25, "turn": .5,
    }
    components = tuple(weights)
    if set(components) <= deviations.keys():
        # Combine ranks, since the three official intervals have different durations.
        # Exhibition and straight share half the weight because both measure speed.
        ranks = {}
        for key in components:
            field = deviations[key]
            ranks[key] = [(sum(x < v for x in field) + (field.count(v) - 1) / 2) / 5 for v in field]
        deviations["overall"] = [
            sum(weights[key] * ranks[key][i] for key in components) - .5 for i in range(6)
        ]
    for key, values in deviations.items():
        for i, value in enumerate(values, 1):
            yield key, str(entries[i]["motor_no"]), str(entries[i]["toban"]), value


def pairing_ratings(meets, venue, items=None):
    samples = defaultdict(list)
    cuts = defaultdict(list)
    video_samples = set()
    for meet in meets:
        for d, title, race in meet:
            used = video_keys(race, venue)
            for key, motor, rider, value in observations(race, venue):
                if key in ("turn", "acceleration", "overall"):
                    if (key, motor, rider) in used:
                        video_samples.add((key, meet[0][0], title, motor, rider))
                    if items is not None:
                        cut = items.deduction(key, rider, venue, motor)
                        value += cut
                        cuts[key, meet[0][0], title, motor, rider].append(cut)
                    samples[key, meet[0][0], title, motor, rider].append((d, value))

    output = {}
    for metric in ("turn", "acceleration", "overall"):
        eligible = {k: v for k, v in samples.items() if k[0] == metric and len(v) >= 3
                    and len({d for d, _ in v}) >= 2}
        # The reference field contains completed and current meeting pairings at this venue.
        values = sorted(sum(x for _, x in xs) / len(xs) for xs in eligible.values())
        if len(values) < MIN_FIELD:
            continue
        center = median(values)
        for (_, start, title, motor, rider), xs in eligible.items():
            # Older pairings are reference samples only. A meeting title can repeat.
            if start != meets[-1][0][0]:
                continue
            mean_delta = sum(x for _, x in xs) / len(xs)
            percentile = (sum(x < mean_delta for x in values) + (values.count(mean_delta) - 1) / 2) / (len(values) - 1)
            grade = "A" if percentile <= .20 else "B" if percentile <= .50 else "C" if percentile <= .80 else "D"
            if grade == "C" and venue in MIDDLE_BAND_VENUES.get(metric, ()):
                grade = "B"
            score = {"grade": grade, "runs": len(xs), "field": len(values), "meetings": 1,
                     "delta": round(mean_delta, 4), "venue_delta": round(mean_delta - center, 4),
                     "through": max(d for d, _ in xs)}
            if metric in ("acceleration", "overall"):
                score["index"] = round((center - mean_delta) * (50 if metric == "acceleration" else 100))
            if items is not None:
                c = cuts[metric, start, title, motor, rider]
                score["rider_deduction"] = round(sum(c) / len(c), 4)
            if metric == "acceleration" and venue in UNCONFIRMED_EXIT_VENUES:
                score["source"] = "unconfirmed_section"
            if (metric, start, title, motor, rider) in video_samples:
                score["source"] = "video"
            output.setdefault(motor, {}).setdefault(rider, {})[metric] = {**score, "start": start, "title": title}
    return output


def rider_baselines(term_profiles, through):
    """Each rider's usual exhibition gap to the race average, in seconds (negative is faster).

    Built from the official exhibition profiles per rating term. Newer terms weigh more and the
    value is pulled toward zero for riders with few runs. Terms that start after `through` are ignored.
    """
    terms = sorted((t for t in ((term_profiles or {}).get("terms") or {}).values()
                    if isinstance(t, dict) and str(t.get("available_from", "9")) <= through),
                   key=lambda t: t["available_from"], reverse=True)
    totals = defaultdict(lambda: [0.0, 0.0])
    for age, term in enumerate(terms):
        weight = RIDER_TERM_DECAY ** age
        for rider, row in (term.get("players") or {}).items():
            n, total = row.get("n"), row.get("dev_sum")
            if type(n) is int and n > 0 and isinstance(total, (int, float)) and math.isfinite(total):
                totals[str(rider)][0] += weight * n
                totals[str(rider)][1] += weight * total
    return {rider: total / (n + RIDER_SHRINK_RUNS) for rider, (n, total) in totals.items()}


# Member ratings take off what the rider brings (research/improvements/RIDER_ADJUSTED_MOTOR.md).
# Deduction only: a rider faster than usual makes the motor's time count slower; a slower rider
# never makes it count faster. The rider baselines are official exhibition deviations, so only
# the 展示 rating uses them.
RIDER_DEDUCTION_METRICS = ("exhibition",)


def rider_deduction(baselines, rider):
    """Seconds to add to this rider's run (0 or more)."""
    return max(0.0, -baselines.get(str(rider), 0.0))


ITEM_DEDUCTION_METRICS = ("straight", "turn", "acceleration", "overall")


class ItemBaselines:
    """Each rider's usual gap to the race average per official item, from runs on OTHER motors
    up to `through` (so the motor being rated does not lower its own score). Pulled toward 0
    with RIDER_SHRINK_RUNS runs, like the exhibition baselines."""

    def __init__(self, records, through):
        self.total = defaultdict(lambda: [0, 0.0])
        self.own = defaultdict(lambda: [0, 0.0])
        for (d, venue, _), race in records.items():
            if d > through:
                continue
            for key, motor, rider, value in observations(race, venue):
                if key in ITEM_DEDUCTION_METRICS:
                    for table, k in ((self.total, (key, rider)), (self.own, (key, rider, venue, motor))):
                        table[k][0] += 1
                        table[k][1] += value

    def deduction(self, key, rider, venue, motor):
        n, total = self.total.get((key, rider), (0, 0.0))
        m, own = self.own.get((key, rider, venue, motor), (0, 0.0))
        return max(0.0, -(total - own) / (n - m + RIDER_SHRINK_RUNS))


def profile(samples, as_of, half_life=HALF_LIFE):
    days = {s[0] for s in samples}
    if len(samples) < MIN_RUNS or len(days) < 3:
        return None
    weights = [2 ** (-(as_of - s[0]).days / half_life) for s in samples]
    avg = sum(s[3] * w for s, w in zip(samples, weights)) / sum(weights)
    # Whole meetings are the replication unit, not individual races from a single day.
    by_meet_rider = defaultdict(list)
    for _, meet, rider, delta in samples:
        by_meet_rider[meet, rider].append(delta)
    replication = [(meet, rider, sum(deltas) / len(deltas))
                   for (meet, rider), deltas in by_meet_rider.items() if len(deltas) >= 2]
    return {"runs": len(samples), "through": max(days).strftime("%Y%m%d"),
            "meetings": len({meet for meet, _ in by_meet_rider}), "delta": round(avg, 4)}, replication


def rank_field(candidates, gap):
    if len(candidates) < MIN_FIELD:
        return {}
    scores = sorted(p["delta"] for p, _ in candidates.values())
    middle = median(scores)
    ranked = {}
    for motor, (p, replication) in candidates.items():
        value = p["delta"]
        percentile = (sum(x < value for x in scores) + (scores.count(value) - 1) / 2) / (len(scores) - 1)
        grade = "A" if percentile <= .20 else "B" if percentile <= .50 else "C" if percentile <= .80 else "D"
        reproducible = [(meet, rider) for meet, rider, delta in replication if delta <= middle - gap]
        if (percentile <= .05 and value <= middle - gap and len(reproducible) >= 2
                and len({meet for meet, _ in reproducible}) >= 2
                and len({rider for _, rider in reproducible}) >= 2):
            grade = "S"
        ranked[motor] = {**p, "grade": grade, "field": len(scores), "venue_delta": round(value - middle, 4)}
    return ranked


def build(records, motor_history, through, meeting_dates=None, periods=None, rider_profiles=None,
          rider_deduction_profiles=None):
    from . import motor_generation
    active = motor_generation.boundaries(through, motor_generation.saved_starts(motor_history), periods)
    as_of = day(through)
    first = as_of - timedelta(days=45)
    grouped = defaultdict(list)
    for (d, venue, rno), race in sorted(records.items()):
        if not first <= day(d) <= as_of:
            continue
        title = (race.get("racelist") or {}).get("title", "").strip()
        if title and not (race.get("result") or {}).get("cancelled"):
            grouped[venue].append((d, title, race))

    baselines = rider_baselines(rider_profiles, through) if rider_profiles else None
    deductions = baselines if rider_deduction_profiles is None else (
        rider_baselines(rider_deduction_profiles, through) if rider_deduction_profiles else None)
    items = ItemBaselines(records, through) if deductions is not None else None
    output = {}
    for venue, races in grouped.items():
        boundary = active.get(venue, {}).get("date")
        if not boundary or boundary == through:
            continue
        meets = []
        for d, title, race in races:
            if d < boundary:
                continue
            if not meets or meets[-1][-1][1] != title or (day(d) - day(meets[-1][-1][0])).days > 3:
                meets.append([])
            meets[-1].append((d, title, race))

        # Check the observed start against the official date range, including partial archives.
        schedules = (meeting_dates or {}).get(venue, {})
        complete = [m for m in meets if not any(
            start <= m[0][0] <= end and end > through
            for start, end in schedules.get(m[0][1], {}).items()
        )]
        recent = complete[-3:]
        data = defaultdict(list)
        deducted = defaultdict(list)
        video_motors = set()
        for meeting in recent:
            meet = meeting[0][0]
            for d, _, race in meeting:
                used = video_keys(race, venue)
                for key, motor, rider, delta in observations(race, venue):
                    if (key, motor, rider) in used:
                        video_motors.add((key, motor))
                    if key in RIDER_DEDUCTION_METRICS and deductions is not None:
                        # A rider faster than usual carried the motor: take that off. Never add.
                        cut = rider_deduction(deductions, rider)
                        delta += cut
                        deducted[key, motor].append(cut)
                    elif key == "straight" and items is not None:
                        cut = items.deduction(key, rider, venue, motor)
                        delta += cut
                        deducted[key, motor].append(cut)
                    data[key, motor].append((day(d), meet, rider, delta))
        metrics = {}
        for key in TRIAL_RATINGS:
            candidates = {}
            for (metric, motor), samples in data.items():
                if metric != key:
                    continue
                result = profile(samples, as_of)
                if result:
                    candidates[motor] = result
            # Trial thresholds in seconds. The S grade also requires two separate meetings.
            metrics[key] = rank_field(candidates, .03)
            if deducted:
                for motor, score in metrics[key].items():
                    if (key, motor) not in deducted:
                        continue
                    cuts = deducted[key, motor]
                    score["rider_deduction"] = round(sum(cuts) / len(cuts), 4) if cuts else 0.0
        if venue in LAP_MINUS_TURN_VENUES:
            for score in metrics["straight"].values():
                score["source"] = "lap_minus_turn"
        for motor, score in metrics["straight"].items():
            if ("straight", motor) in video_motors:
                score["source"] = "video"
        if baselines is not None:
            # Every finished meeting in the window, minus what each rider usually does. A rider the
            # profiles do not know is treated as average. Different riders must have used the motor.
            adjusted = defaultdict(list)
            for meeting in complete:
                meet = meeting[0][0]
                for d, _, race in meeting:
                    for key, motor, rider, delta in observations(race, venue):
                        if key == "exhibition":
                            adjusted[motor].append((day(d), meet, rider, delta - baselines.get(rider, 0.0)))
            candidates = {}
            for motor, samples in adjusted.items():
                result = profile(samples, as_of, ADJUSTED_HALF_LIFE)
                if result and len({rider for _, _, rider, _ in samples}) >= 2:
                    result[0]["riders"] = len({rider for _, _, rider, _ in samples})
                    candidates[motor] = result
            metrics["adjusted"] = rank_field(candidates, .03)
        motors = {}
        for key, by_motor in metrics.items():
            for motor, value in by_motor.items():
                motors.setdefault(motor, {})[key] = value
        pairings = pairing_ratings(meets[-4:], venue, items)
        if motors or pairings:
            output[venue] = {"period": boundary, "motors": motors, "pairings": pairings}
    return {"version": 1, "through": through, "venues": output}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def write_private(out, payload):
    out.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=out.parent, suffix=".tmp", delete=False) as f:
        temporary = Path(f.name)
    try:
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(out)
    finally:
        temporary.unlink(missing_ok=True)


def publish_snapshot(payload, base, secret, opener=None, sleep=time.sleep):
    url = urlsplit(base)
    if (url.scheme != "https" or not re.fullmatch(r"[a-z0-9]+\.supabase\.co", url.netloc)
            or url.path != "/functions/v1/premium" or url.query or url.fragment):
        raise ValueError("invalid premium function URL")
    if not re.fullmatch(r"[a-f0-9]{64}", secret):
        raise ValueError("invalid premium publish key")
    opener = opener or build_opener(NoRedirect()).open
    req = Request(base, payload.encode(), {"Content-Type": "application/json", "X-Premium-Publish-Key": secret})
    for attempt in range(3):
        try:
            with opener(req, timeout=45) as resp:
                if json.load(resp).get("stored") is not True:
                    raise RuntimeError("snapshot rejected")
                return
        except HTTPError as err:
            if err.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise RuntimeError(f"premium publish failed (HTTP {err.code})") from None
        except (URLError, TimeoutError):
            if attempt == 2:
                raise RuntimeError("premium publish timed out") from None
        sleep(2 ** attempt)


def _settled(path):
    """これ以上待っても変わらないレースか。3連単が不成立（集団フライングなど）のレースや、
    直前情報が取れなかったレースは保存先に入らないが、結果は確定している。"""
    try:
        race = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    outcome = race.get("result") or {}
    return bool(outcome.get("finished") or outcome.get("cancelled") or outcome.get("order")
                or outcome.get("refunded") or race.get("result_tries", 0) >= RESULT_TRIES_LIMIT)


def check_publish_inputs(records, through, today, races_dir):
    if (today - day(through)).days not in range(1, 4):
        raise ValueError("refusing to publish a stale or future cutoff")
    expected = Counter()
    available = Counter()
    day_index = races_dir.parent / "day-index" / (through + ".json")
    scheduled = {}
    if day_index.is_file():
        index = json.loads(day_index.read_text(encoding="utf-8"))
        if index.get("date") != through:
            raise ValueError("official schedule date mismatch")
        scheduled = {v["jcd"]: not v.get("cancelled") for v in index.get("venues", [])}
        if not scheduled:
            raise ValueError("official schedule is empty")
    for path in (races_dir / through).glob("*.json"):
        if not re.fullmatch(r"(0[1-9]|1[0-9]|2[0-4])(0[1-9]|1[0-2])", path.stem):
            continue
        venue, race = path.stem[:2], int(path.stem[2:])
        if scheduled and not scheduled.get(venue):
            continue
        expected[venue] += 1
        archived = records.get((through, venue, race), {})
        outcome = archived.get("result") or {}
        if outcome.get("finished") or outcome.get("cancelled") or _settled(path):
            available[venue] += 1
    if not expected:
        raise ValueError("no scheduled race files on the requested cutoff")
    venues = {venue for venue, held in scheduled.items() if held} if scheduled else set(expected)
    # BOAT RACE uses 12 races per active venue. An incomplete local
    # racecard list is not a reliable denominator.
    incomplete = sorted(venue for venue in venues
                        if available[venue] < (12 if scheduled else expected[venue]))
    if incomplete:
        raise ValueError("incomplete official archive for " + through + ": " + ", ".join(sorted(incomplete)))


def load_inputs():
    with gzip.open(ROOT / "scraper" / "motor.json.gz", "rt", encoding="utf-8") as f:
        history = json.load(f)
    schedules = defaultdict(lambda: defaultdict(dict))
    for path in (ROOT / "site" / "data" / "meetings").glob("*.json"):
        m = json.loads(path.read_text(encoding="utf-8"))
        schedules[m["jcd"]][m["title"].strip()][m["start"]] = m["end"]
    return attach_video(archived_records(), load_video()), history, schedules


def load_video(directory=VIDEO_DIR):
    """Own replay measurements: {(date, venue, race): {metric: {boat: seconds}}}. Only VIDEO_VENUES."""
    video = defaultdict(lambda: defaultdict(dict))
    for path in sorted(Path(directory).glob("*.json")):
        try:
            rows = json.loads(path.read_text(encoding="utf-8")).get("rows") or []
        except (ValueError, AttributeError):
            continue
        for r in rows:
            if (isinstance(r, dict) and r.get("source") == "video" and r.get("venue") in VIDEO_VENUES
                    and r.get("metric") in VIDEO_METRICS):
                video[r["date"], r["venue"], int(r["race"])][r["metric"]][int(r["boat"])] = r["seconds"]
    return video


def attach_video(records, video):
    for key, measured in video.items():
        if key in records:
            records[key] = {**records[key], "video": {k: dict(v) for k, v in measured.items()}}
    return records


def load_rider_profiles():
    with gzip.open(ROOT / "scraper" / "exstats.json.gz", "rt", encoding="utf-8") as f:
        return json.load(f).get("term_profiles") or {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--through", help="Last included race date in JST, YYYYMMDD")
    ap.add_argument("--output", type=Path, help="Write a private JSON file outside site/")
    ap.add_argument("--publish", action="store_true", help="Replace the protected Supabase snapshot")
    ap.add_argument("--require-complete", action="store_true", help="Apply the production checks to a local run")
    ap.add_argument("--with-rider-adjusted", action="store_true",
                    help="Add the rider-adjusted exhibition rating. Deploy the Premium function that accepts it first")
    ap.add_argument("--without-rider-deduction", action="store_true",
                    help="Leave out the rider deduction (for comparison only; members get it by default)")
    args = ap.parse_args()
    if not (args.output or args.publish):
        ap.error("choose --output or --publish")
    today = datetime.now(timezone(timedelta(hours=9))).date()
    through = args.through or (today - timedelta(days=1)).strftime("%Y%m%d")
    try:
        if day(through) >= today:
            ap.error("only past dates are accepted")
        records, history, schedules = load_inputs()
        if args.publish or args.require_complete:
            check_publish_inputs(records, through, today, ROOT / "site" / "data" / "races")
        from . import motor_generation
        periods = motor_generation.live_periods(ROOT / "site" / "data", through)
        profiles = load_rider_profiles()
        result = build(records, history, through, schedules, periods["venues"],
                       profiles if args.with_rider_adjusted else None,
                       {} if args.without_rider_deduction else profiles)
        for venue in periods["pending"]:
            result["venues"].pop(venue, None)
        if not result["venues"]:
            ap.error("No eligible venue data. The stored snapshot was left intact.")
        payload = json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        if args.output:
            out = args.output.resolve()
            if out.is_relative_to(ROOT / "site"):
                ap.error("premium data cannot be written in site/")
            write_private(out, payload)
        if args.publish:
            publish_snapshot(payload, os.environ.get("TEILOG_PREMIUM_FUNCTION_URL", "").rstrip("/"),
                             os.environ.get("TEILOG_PREMIUM_PUBLISH_KEY", ""))
    except (ValueError, RuntimeError) as exc:
        ap.error(str(exc))
    print("Premium snapshot", through, "venues", len(result["venues"]),
          "motors", sum(len(v["motors"]) for v in result["venues"].values()))


if __name__ == "__main__":
    main()
