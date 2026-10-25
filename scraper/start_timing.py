"""Prior-day actual ST estimate, independently versioned from betting predictions.

The 730-day course mean is shrunk toward/away from the local course mean with
25 pseudo observations. Selected on development dates before 2026-04-01.
Meeting averages are factual references only, never a prediction correction.
"""
from collections import defaultdict
from datetime import datetime, timedelta
from functools import lru_cache
import hashlib
import math
import re
from threading import Lock

VERSION = 1
WINDOW_DAYS = 730
LOCAL_PRIOR_N = 25
FINGERPRINT = hashlib.sha256(f"st:{VERSION}:{WINDOW_DAYS}:{LOCAL_PRIOR_N}:prior-days-only".encode()).hexdigest()[:16]
_INDEX_LOCK = Lock()


def meeting_start(date, label):
    """Use the official scheduled date range, never infer a meeting from gaps."""
    m = re.search(r"(\d{1,2})/(\d{1,2})\s*[-〜～]\s*(\d{1,2})/(\d{1,2})", label or "")
    if not m:
        return None
    today = datetime.strptime(date, "%Y%m%d")
    am, ad, bm, bd = map(int, m.groups())
    for year in (today.year - 1, today.year):
        try:
            first = datetime(year, am, ad)
            last = datetime(year + int((bm, bd) < (am, ad)), bm, bd)
        except ValueError:
            continue
        if first <= today <= last and (last - first).days <= 31:
            return first.strftime("%Y%m%d")
    return None


class StartIndex:
    def __init__(self, races, date):
        self.date = date
        self.since = (datetime.strptime(date, "%Y%m%d") - timedelta(days=WINDOW_DAYS)).strftime("%Y%m%d")
        self.stats = defaultdict(lambda: [0, 0.0, 0.0])
        self.recent = defaultdict(list)
        recent_start = (datetime.strptime(date, "%Y%m%d") - timedelta(days=31)).strftime("%Y%m%d")
        seen = set()
        for r in races:
            key = (r[0], r[1], r[2])
            if not self.since <= r[0] < date or key in seen:
                continue
            seen.add(key)
            for e in r[11]:
                if e[2] not in range(1, 7) or e[3] is None or e[4]:
                    continue
                value = e[3] / 100
                if not math.isfinite(value) or value < 0:
                    continue
                for k in ((e[1], "", e[2]), (e[1], r[1], e[2])):
                    acc = self.stats[k]
                    acc[0] += 1
                    acc[1] += value
                    acc[2] += value * value
                if r[0] >= recent_start:
                    self.recent[(e[1], r[1])].append((r[0], value))
        self.fingerprint = hashlib.sha256(repr(sorted((k, tuple(v)) for k, v in self.stats.items())).encode()).hexdigest()[:16]

    def estimate(self, toban, venue, course, start=None):
        n, total, squares = self.stats[(toban, "", course)]
        if n < 3:
            return None
        ln, ls, lq = self.stats[(toban, venue, course)]
        base = total / n
        mean = (ls + LOCAL_PRIOR_N * base) / (ln + LOCAL_PRIOR_N)
        second = (lq + LOCAL_PRIOR_N * squares / n) / (ln + LOCAL_PRIOR_N)
        xs = [v for d, v in self.recent[(toban, venue)] if start and start <= d < self.date]
        return {"st": mean, "sd": math.sqrt(max(0, second - mean * mean)),
                "n": n, "course": course, "course_mean": base,
                "local_n": ln, "local_mean": ls / ln if ln else None,
                "local_weight": ln / (ln + LOCAL_PRIOR_N),
                "meeting_n": len(xs), "meeting_mean": sum(xs) / len(xs) if xs else None,
                "meeting_start": start, "asof_exclusive": self.date,
                "since": self.since, "source": "prior_day_actual_course_local"}

    def averages(self, toban, venue, course, start=None):
        n, total, _ = self.stats[(toban, "", course)]
        local = [self.stats[(toban, venue, c)] for c in range(1, 7)]
        ln = sum(x[0] for x in local)
        xs = [v for d, v in self.recent[(toban, venue)] if start and start <= d < self.date]
        return {'course': total / n if n else None, 'meeting': sum(xs) / len(xs) if xs else None,
                'local': sum(x[1] for x in local) / ln if ln else None}


@lru_cache(maxsize=1)
def _load_index(date):
    from .history import load_all
    since = (datetime.strptime(date, "%Y%m%d") - timedelta(days=WINDOW_DAYS)).strftime("%Y%m%d")
    return StartIndex(load_all(since), date)


def load_index(date):
    # Multiple race workers must share one cold load, not inflate memory sixfold.
    with _INDEX_LOCK:
        return _load_index(date)


def capture(race, venue, now, index=None):
    """Capture only before deadline. A late-running job cannot upgrade old data."""
    date = race["date"]
    dl = datetime.strptime(date + race["deadline"], "%Y%m%d%H:%M").replace(tzinfo=now.tzinfo)
    if now.tzinfo is None:
        raise ValueError("timezone-aware timestamp required")
    if now >= dl or now.strftime("%Y%m%d") != date or (race.get("result") or {}).get("finished"):
        return None
    boats = (race.get("racelist") or {}).get("boats") or []
    if not boats:
        return None
    se = (race.get("before") or {}).get("start_exhibition") or []
    frames = [x.get("frame") for x in se]
    courses = [x.get("course") for x in se]
    valid = len(se) == 6 and set(frames) == set(range(1, 7)) and set(courses) == set(range(1, 7))
    entry = {x["frame"]: x["course"] for x in se} if valid else {}
    idx = index or load_index(date)
    start = meeting_start(date, venue.get("day"))
    estimates = {}
    averages = {}
    for b in boats:
        frame = b["frame"]
        c = entry.get(frame, frame)
        averages[str(frame)] = idx.averages(b.get('toban', ''), race['jcd'], c, start)
        value = idx.estimate(b.get("toban", ""), race["jcd"], c, start)
        if value:
            estimates[str(frame)] = {**value, "entry_assumption": "exhibition" if valid else "frame", "toban": b.get("toban", "")}
    return {"version": VERSION, "fingerprint": FINGERPRINT, "data_fingerprint": idx.fingerprint,
            "captured_at": now.isoformat(), "boats": estimates, "averages": averages}
