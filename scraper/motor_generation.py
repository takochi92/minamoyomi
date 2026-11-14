"""Resolve the active fleet from official notices and official racecards."""
import json
from functools import lru_cache
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "site" / "data"
NOTICES = Path(__file__).with_name("motor_renewals.json")
FILENAME = "motor-periods.json"


def read(path, default):
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=4)
def notices(path):
    return read(path, {})


def choose(periods, candidate):
    """Keep the newest fleet, preferring a notice over a matching inference."""
    if not periods:
        return candidate
    if candidate["date"] == periods["date"]:
        return candidate if candidate["source"] == "official_confirmed" else periods
    return max(periods, candidate, key=lambda p: p["date"])


def boundaries(through, inferred=None, published=None):
    result = {venue: {"date": date, "source": "zero_rate_inferred"}
              for venue, date in (inferred or {}).items() if date <= through}
    for venue, value in (published or {}).items():
        if value["date"] <= through:
            result[venue] = choose(result.get(venue), value)
    for venue, value in notices(NOTICES).items():
        if value["date"] <= through:
            result[venue] = choose(result.get(venue), {**value, "source": "official_confirmed"})
    return result


def card_counts(boats):
    # An absent number or rate is not evidence of a reset.
    rates = [b.get("motor_2") for b in boats]
    motors = {b.get("motor_no") for b in boats}
    if (len(boats) != 6 or len(motors) != 6 or any(type(m) is not int or m <= 0 for m in motors)
            or any(type(rate) not in (int, float) or not 0 <= rate <= 100 for rate in rates)):
        return None
    return sum(rate == 0 for rate in rates)


def meeting_start(date, label):
    match = re.search(r"(\d{1,2})/(\d{1,2})\s*[-〜～]\s*(\d{1,2})/(\d{1,2})", label)
    if not match:
        return date
    try:
        current = datetime.strptime(date, "%Y%m%d").date()
        sm, sd, em, ed = map(int, match.groups())
        start = current.replace(month=sm, day=sd)
        if start > current:
            start = start.replace(year=start.year - 1)
        end = start.replace(year=start.year + (em < sm), month=em, day=ed)
    except ValueError:
        return date
    return start.strftime("%Y%m%d") if start <= current <= end else date


def live_periods(data, through, inferred=None):
    old = read(data / FILENAME, {})
    active = boundaries(through, inferred, published=old.get("venues"))
    candidate_days = Counter()
    zero_counts = Counter()
    # Raw cards are retained for two weeks; the published ledger preserves earlier resets.
    earliest = min([old.get("date", ""), *old.get("pending", {}).values()])
    current_starts = set()
    dates = {p.name for p in (data / "races").iterdir()} if (data / "races").is_dir() else set()
    for date in sorted(dates | {through}):
        folder = data / "races" / date
        if not re.fullmatch(r"20\d{6}", date) or date > through or (earliest <= through and date < earliest):
            continue
        index = read(data / "day-index" / f"{date}.json", {})
        starts = {v["jcd"]: meeting_start(date, v.get("day", "")) for v in index.get("venues", [])
                  if not v.get("cancelled")}
        if date == through:
            current_starts = {venue for venue, start in starts.items() if start == date}
        for path in folder.glob("????.json"):
            race = read(path, {})
            venue = race.get("jcd")
            number = race.get("rno")
            if (race.get("date") != date or not isinstance(venue, str)
                    or not re.fullmatch(r"(0[1-9]|1[0-9]|2[0-4])", venue)
                    or type(number) is not int or not 1 <= number <= 12 or path.stem != f"{venue}{number:02d}"
                    or date < active.get(venue, {}).get("date", "")):
                continue
            zeros = card_counts((race.get("racelist") or {}).get("boats") or [])
            if zeros is not None:
                key = (venue, date, starts.get(venue, date))
                candidate_days[key] += 6
                zero_counts[key] += zeros
    pending = {venue: start for venue, start in old.get("pending", {}).items()
               if active.get(venue, {}).get("date", "") < start <= through}
    for (venue, date, start), total in sorted(candidate_days.items()):
        if start <= active.get(venue, {}).get("date", ""):
            continue
        if total >= 24 and zero_counts[venue, date, start] * 10 >= total * 9:
            active[venue] = {"date": start, "source": "zero_rate_inferred"}
            pending.pop(venue, None)
        elif total >= 24 and pending.get(venue) == start:
            pending.pop(venue)
        elif date == through and zero_counts[venue, date, start] >= 5:
            pending[venue] = start
    for venue in current_starts:
        if through > active.get(venue, {}).get("date", "") and candidate_days[venue, through, through] < 24:
            pending.setdefault(venue, through)
    return {"date": through, "venues": active, "pending": pending}


def for_display(data, periods):
    """Drop stale generation rows before rendering the motor list or search."""
    clean = dict(data)
    for venue in periods["pending"]:
        clean.pop(venue, None)
    for venue, period in periods["venues"].items():
        if venue in periods["pending"]:
            continue
        rows = clean.get(venue) or {}
        clean[venue] = {motor: row for motor, row in rows.items()
                        if row.get("history_boundary") == period["date"]}
    return clean


def saved_starts(data):
    return {venue: next(iter(starts)) for venue, rows in data.items()
            if len(starts := {row["history_boundary"] for row in rows.values()
                              if row.get("history_boundary")}) == 1}


def for_race(data, venue, date, boats, ledger):
    if sum(not b.get("motor_2") for b in boats) >= 5:
        return {}
    if ledger.get("pending", {}).get(venue, "99999999") <= date:
        return {}
    period = boundaries(date, published=ledger.get("venues")).get(venue)
    if period and period["date"] == date:
        return {}
    rows = data.get(venue, {})
    return {motor: row for motor, row in rows.items()
            if (not period or row.get("history_boundary") == period["date"])
            and (row.get("history_boundary") or "") <= date}
