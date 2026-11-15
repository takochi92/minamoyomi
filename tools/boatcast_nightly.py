"""Nightly: measure the exhibition replays of every venue that raced today and has a profile.

  python -m tools.boatcast_nightly [--date YYYYMMDD] [--stop 0630] [--dry-run]

- Race cards come from origin/main (git fetch + git archive into a temporary folder), because this
  checkout's site/data is not updated.
- Venues go in PRIORITY order (venues with blank premium items first), then the rest by number.
- Numbers only: tools.boatcast_measure writes research/boatcast-measure/<date>-<venue>.json and
  deletes its temporary samples. No video or still image is kept.
- Stops before starting a venue after --stop (JST, next morning) and gives each venue at most the
  time left (one race takes about 4 minutes).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "tools" / "boatcast" / "profiles"
# 江戸川 (all items blank), then the six venues without 立ち上がり, then the rest
PRIORITY = ["03", "01", "06", "11", "12", "13", "18"]
JST = timezone(timedelta(hours=9))
MINUTES_PER_RACE = 4.5


def now():
    return datetime.now(JST)


def order(venues):
    first = [v for v in PRIORITY if v in venues]
    return first + sorted(v for v in venues if v not in first)


def deadline(start, stop):
    """The next stop time after start (stop is HHMM in JST, usually the next morning)."""
    end = start.replace(hour=int(stop[:2]), minute=int(stop[2:]), second=0, microsecond=0)
    return end if end > start else end + timedelta(days=1)


def fetch_cards(date, dest):
    subprocess.run(["git", "fetch", "-q", "origin", "main"], cwd=ROOT, check=True, timeout=300)
    path = f"site/data/races/{date}"
    archive = subprocess.run(["git", "archive", "origin/main", path], cwd=ROOT, capture_output=True, timeout=300)
    if archive.returncode:
        return {}
    subprocess.run(["tar", "-x", "-C", str(dest)], input=archive.stdout, check=True)
    races = Path(dest) / "site" / "data" / "races"
    venues = {}
    for p in sorted((races / date).glob("*.json")):
        venues.setdefault(p.stem[:2], []).append(int(p.stem[2:]))
    return races, venues


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=now().strftime("%Y%m%d"))
    ap.add_argument("--stop", default="0630")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    start = now()
    end = deadline(start, args.stop)
    with tempfile.TemporaryDirectory(prefix="bc-cards-") as tmp:
        fetched = fetch_cards(args.date, tmp)
        if not fetched or not fetched[1]:
            print(start.isoformat(timespec="seconds"), args.date, "no race cards on origin/main", flush=True)
            return 1
        races, venues = fetched
        todo = [v for v in order(venues) if (PROFILES / f"{v}.json").is_file()]
        skipped = sorted(v for v in venues if v not in todo)
        print(start.isoformat(timespec="seconds"), args.date, "measure", todo, "no profile", skipped, flush=True)
        if args.dry_run:
            return 0
        env = {**os.environ, "BOATCAST_RACES_DIR": str(races)}
        for v in todo:
            left = (end - now()).total_seconds()
            if left < MINUTES_PER_RACE * 60 * 2:
                print(now().isoformat(timespec="seconds"), "stop: time, not measured", todo[todo.index(v):], flush=True)
                break
            print(now().isoformat(timespec="seconds"), "venue", v, flush=True)
            try:
                subprocess.run([sys.executable, "-m", "tools.boatcast_measure", "run", "--date", args.date,
                                "--venue", v, "--races", ",".join(map(str, sorted(venues[v])))],
                               cwd=ROOT, env=env, timeout=left)
            except subprocess.TimeoutExpired:
                print(now().isoformat(timespec="seconds"), "stop: time inside", v, flush=True)
                break
        print(now().isoformat(timespec="seconds"), "done", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
