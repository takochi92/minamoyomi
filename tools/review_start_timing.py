"""Chronological ST comparison. Only prior-day official results enter features.

The consecutive-day venue segment is a diagnostic proxy, NOT a verified meeting.
Never use its result to enable a production 'this meeting' correction.
"""
from __future__ import annotations

import argparse
from collections import defaultdict, deque
from datetime import datetime
from itertools import groupby
import gzip
import json
from pathlib import Path

import numpy as np

from scraper.history import HIST, load_all


def read_before():
    out = {}
    for p in sorted((HIST / "before").glob("*.jsonl.gz")):
        with gzip.open(p, "rt", encoding="utf-8") as f:
            for line in f:
                key, r = json.loads(line)
                date, venue, rno = key.split("-")
                out[(date, venue, int(rno))] = r
    return out


def examples(races, before):
    races = sorted(races, key=lambda r: (r[0], r[1], r[2]))
    pairs = defaultdict(lambda: deque(maxlen=80))
    stats = defaultdict(lambda: [0, 0.0])
    history = deque()
    last_day = {}
    segments = defaultdict(dict)
    records = []
    for date, day_iter in groupby(races, key=lambda r: r[0]):
        day = list(day_iter)
        ordinal = datetime.strptime(date, "%Y%m%d").toordinal()
        while history and history[0][0] < ordinal - 730:
            _, t, v, c, st = history.popleft()
            for k in ((t, "", c), (t, v, c)):
                stats[k][0] -= 1
                stats[k][1] -= st
        venues = {r[1] for r in day}
        for v in venues:
            if last_day.get(v) != ordinal - 1:
                segments[v] = {}
        updates = []
        pair_updates = []
        observations = []
        for r in day:
            b = before.get((date, r[1], r[2])) or {}
            ex = {frame: (i + 1, st) for i, (frame, st) in enumerate(zip(b.get("entry", []), b.get("st", [])))}
            for e in r[11]:
                t, c, st = e[1], e[2], e[3]
                if c not in range(1, 7) or st is None or e[4]:
                    continue
                st = st / 100
                gn, gs = stats[(t, "", c)]
                if gn:
                    updates.append((t, r[1], st - gs / gn))
                if e[0] in ex and ex[e[0]][1] is not None:
                    ec = ex[e[0]][0]
                    ps = [p for p in pairs[t] if p[0] >= ordinal - 400]
                    cp = [p for p in ps if p[1] == ec]
                    use = cp if len(cp) >= 3 else ps
                    if len(use) >= 3 and date >= "20251201":
                        baseline = sum(p[2] for p in use) / len(use)
                        gn, gs = stats[(t, "", ec)]
                        ln, ls = stats[(t, r[1], ec)]
                        delta = ls / ln - gs / gn if ln and gn >= 3 else 0.0
                        sn, ss = segments[r[1]].get(t, (0, 0.0))
                        records.append([date, r[1], r[2], t, ec, c, st, baseline,
                                        gs / gn if gn >= 3 else baseline, ln, delta,
                                        sn, ss / sn if sn else 0.0])
                    pair_updates.append((t, ordinal, c, st))
                observations.append((ordinal, t, r[1], c, st))
        # All predictions on this date precede ALL result updates on this date.
        for _, t, v, c, st in observations:
            for k in ((t, "", c), (t, v, c)):
                stats[k][0] += 1
                stats[k][1] += st
        history.extend(observations)
        for t, od, c, st in pair_updates:
            pairs[t].append((od, c, st))
        for v in venues:
            last_day[v] = ordinal
        for t, v, residual in updates:
            n, total = segments[v].get(t, (0, 0.0))
            segments[v][t] = (n + 1, total + residual)
    return records


def review():
    records = examples(load_all(), read_before())
    a = np.array([r[4:] for r in records], dtype=float)
    dates = np.array([r[0] for r in records])
    target, base, global_mean, n, delta, sn, sd = (a[:, i] for i in range(2, 9))
    predictions = {"existing": base, "course_730d": global_mean}
    for strength in (10, 25, 50):
        predictions[f"local_{strength}"] = base + delta * n / (n + strength)
        predictions[f"course_local_{strength}"] = global_mean + delta * n / (n + strength)
    for strength in (4, 8, 16):
        predictions[f"segment_diagnostic_{strength}"] = base + sd * sn / (sn + strength)
    dev = dates < "20260401"
    test = ~dev
    def metric(p, mask):
        err = p[mask] - target[mask]
        return {"n": int(mask.sum()), "mae": float(np.abs(err).mean()), "rmse": float(np.sqrt((err ** 2).mean())), "bias": float(err.mean())}
    metrics = {k: {"development": metric(p, dev), "holdout": metric(p, test)} for k, p in predictions.items()}
    deployable = [k for k in predictions if not k.startswith("segment") and k != "existing"]
    selected = min(deployable, key=lambda k: metrics[k]["development"]["mae"])
    p = predictions[selected]
    monthly = {m: {"existing": metric(base, test & np.char.startswith(dates, m)), "candidate": metric(p, test & np.char.startswith(dates, m))} for m in sorted({d[:6] for d in dates[test]})}
    days = sorted(set(dates[test]))
    daily = np.array([[(np.abs(base - target) - np.abs(p - target))[dates == d].sum(),
                       (np.abs(global_mean - target) - np.abs(p - target))[dates == d].sum(),
                       (dates == d).sum()] for d in days])
    rng = np.random.default_rng(20261025)
    boot = []
    for _ in range(2000):
        sampled = daily[rng.integers(0, len(days), len(days))].sum(axis=0)
        boot.append([sampled[0] / sampled[2], sampled[1] / sampled[2]])
    return {"period": [min(dates), max(dates)], "split": "20260401", "prior_days_only": True,
            "excludes": "F/L, missing ST; paired exhibition required for existing baseline; exhibition course used before race",
            "segment_warning": "consecutive venue days are an unverified meeting proxy; never deploy this diagnostic correction",
            "selected_on_development": selected, "metrics": metrics, "monthly": monthly,
            "improvement_95pct_day_block_bootstrap": np.quantile(np.array(boot)[:, 0], [.025, .975]).tolist(),
            "local_increment_95pct_day_block_bootstrap": np.quantile(np.array(boot)[:, 1], [.025, .975]).tolist(),
            "by_course_holdout": {str(c): {"existing": metric(base, test & (a[:, 0] == c)), "candidate": metric(p, test & (a[:, 0] == c))} for c in range(1, 7)},
            "changed_course_holdout_n": int((test & (a[:, 0] != a[:, 1])).sum())}


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    result = review()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
