"""Historical diagnostic for strong-inside races with a course-3 specialist.

All player rates use races strictly before the current date in a rolling 365-day
window. The exhibition entry is used for ticket construction; confirmed odds
and payouts are diagnostic only, not a deadline-time purchase record.
"""
from __future__ import annotations

from collections import Counter, defaultdict, deque
from datetime import datetime, timedelta
import json

from scraper.history import load_all
from scraper.odds import load_before


def valid_entries(race, before):
    entries = race[11]
    if len(entries) != 6 or not before or len(before.get("entry", [])) != 6:
        return None
    by_frame = {e[0]: e for e in entries}
    if set(by_frame) != set(range(1, 7)):
        return None
    # No inference from the eventual entry: require the saved exhibition order
    # to match the official race entry exactly.
    if any(by_frame[frame][2] != course for course, frame in enumerate(before["entry"], 1)):
        return None
    if any(e[5] not in range(1, 7) for e in entries):
        return None
    return [by_frame[f] for f in before["entry"]]


def summarize(bucket):
    n = bucket["races"]
    spend = bucket["tickets"] * 100
    return {**bucket, "in_win_rate": round(bucket["in_wins"] / n, 4) if n else None,
            "in_first_10k_rate": round(bucket["in_first_10k"] / n, 4) if n else None,
            "ticket_hit_rate": round(bucket["hits"] / n, 4) if n else None,
            "diagnostic_roi": round(bucket["payout"] / spend, 4) if spend else None}


def run():
    races = sorted(load_all(), key=lambda r: (r[0], r[1], r[2]))
    before = load_before()
    # Each entry is (date, toban, course, winner). Update only after day changes.
    history = deque()
    counts = defaultdict(lambda: [0, 0])
    pending = []
    current_day = ""
    groups = defaultdict(Counter)
    for race in races:
        day = race[0]
        if day != current_day:
            for d, t, c, won in pending:
                counts[t, c][0] += 1
                counts[t, c][1] += won
                history.append((d, t, c, won))
            pending.clear()
            current_day = day
            cutoff = (datetime.strptime(day, "%Y%m%d") - timedelta(days=365)).strftime("%Y%m%d")
            while history and history[0][0] < cutoff:
                _, t, c, won = history.popleft()
                counts[t, c][0] -= 1
                counts[t, c][1] -= won
        key = f"{day}-{race[1]}-{race[2]}"
        ordered = valid_entries(race, before.get(key))
        if ordered is None:
            # Still train from official completed results, when valid.
            entries = race[11]
            if len(entries) == 6:
                pending.extend((day, e[1], e[2], int(e[5] == 1)) for e in entries
                               if e[2] in range(1, 7) and isinstance(e[5], int))
            continue
        pending.extend((day, e[1], e[2], int(e[5] == 1)) for e in ordered)
        if day < "20260401" or not race[8] or not isinstance(race[9], int):
            continue
        first = counts[ordered[0][1], 1]
        third = counts[ordered[2][1], 3]
        if first[0] < 20 or first[1] / first[0] < .65:
            continue
        specialist = third[0] >= 20 and third[1] / third[0] >= .15
        weak = sum(counts[e[1], c][0] >= 20 and counts[e[1], c][1] / counts[e[1], c][0] <= .05
                   for c, e in enumerate(ordered[1:], 2))
        # Four fixed tickets; no outcome-dependent selection.
        f1, f3 = ordered[0][0], ordered[2][0]
        tickets = {f"{f1}-{f3}-{ordered[c - 1][0]}" for c in (2, 4, 5, 6)}
        result = race[8]
        in_win = int(result.startswith(f"{f1}-"))
        payout = race[9] if result in tickets else 0
        labels = ["all_strong_in", "specialist" if specialist else "no_specialist"]
        if specialist:
            labels.append("specialist_weak_other" if weak >= 2 else "specialist_other")
        for label in labels:
            b = groups[label]
            b["races"] += 1
            b["in_wins"] += in_win
            b["in_first_10k"] += int(in_win and race[9] >= 10000)
            b["tickets"] += len(tickets)
            b["hits"] += int(result in tickets)
            b["payout"] += payout
            b["total_trifecta_payout"] += race[9]
    return {"period": "20260401 onward", "entry": "saved exhibition order equals actual entry",
            "training": "rolling previous 365 days, previous dates only", "groups": {k: summarize(v) for k, v in groups.items()}}


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
