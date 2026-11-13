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
MIN_RUNS = 6
HALF_LIFE = 14
TRIAL_RATINGS = ("exhibition", "straight")
# Rider-adjusted exhibition (research/improvements/RIDER_ADJUSTED_MOTOR.md). The published snapshot
# only carries it when the build is asked to, because the Premium function must accept the key first.
ADJUSTED_HALF_LIFE = 45
RIDER_SHRINK_RUNS = 8
RIDER_TERM_DECAY = .5
# Official course maps document the early straight section at these venues.
EXIT_SECTION_VENUES = {"02", "04", "07", "14", "22"}
# The replay found clear A/D separation but unstable intermediate ordering here.
# Use B for the middle band rather than presenting two distinct grades.
MIDDLE_BAND_VENUES = {"turn": {"09", "12", "15"}, "overall": {"06", "22"}}
TWO_SECTION_VENUES = {"12", "13", "18"}


def day(value):
    if not re.fullmatch(r"20[0-9]{6}", value):
        raise ValueError("expected YYYYMMDD")
    return date(int(value[:4]), int(value[4:6]), int(value[6:8]))


def observations(race, venue=None):
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


def pairing_ratings(meets, venue):
    samples = defaultdict(list)
    for meet in meets:
        for d, title, race in meet:
            for key, motor, rider, value in observations(race, venue):
                if key in ("turn", "acceleration", "overall"):
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


def build(records, motor_history, through, meeting_dates=None, periods=None, rider_profiles=None):
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
        for meeting in recent:
            meet = meeting[0][0]
            for d, _, race in meeting:
                for key, motor, rider, delta in observations(race):
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
        if baselines is not None:
            # Every finished meeting in the window, minus what each rider usually does. A rider the
            # profiles do not know is treated as average. Different riders must have used the motor.
            adjusted = defaultdict(list)
            for meeting in complete:
                meet = meeting[0][0]
                for d, _, race in meeting:
                    for key, motor, rider, delta in observations(race):
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
        pairings = pairing_ratings(meets[-4:], venue)
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
        if outcome.get("finished") or outcome.get("cancelled"):
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
    return archived_records(), history, schedules


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
        result = build(records, history, through, schedules, periods["venues"],
                       load_rider_profiles() if args.with_rider_adjusted else None)
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
