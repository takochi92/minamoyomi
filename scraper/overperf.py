"""「実力のわりに、このコースで勝てる選手」を探す。

ただ強い選手（A1）はどのコースでも1着率が高いので、コース別1着率の順位では強い人が並ぶだけになる。
そこで、全国勝率・級別・コースだけで決まる「実力どおりなら取れる1着の数（期待）」を出し、
実際の1着数との比（実力補正スコア）で並べる。スコア1.6＝実力から見込まれるより6割多く勝っている。

  python -m scraper.overperf     # scraper/overperf.json.gz を作る（毎朝の history ワークフローで実行）

基準モデル：レース内の条件付きロジット（コース＋全国勝率＋全国勝率×コース＋級別）。選手のコース別成績は使わない。
スコアは (実際の1着＋2) / (期待の1着＋2) で、出走が少ない選手ほど1に寄せる。
"""
from __future__ import annotations

import gzip
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from scipy.optimize import minimize

from .history import load_all

PATH = Path(__file__).resolve().parent / "overperf.json.gz"
CL = {"A1": 0, "A2": 1, "B1": 2}
PRIOR = 2.0


def features(entries):
    """コース順に並んだ6艇 → 特徴量 (6, 11)"""
    X = np.zeros((6, 11))
    for i, e in enumerate(entries):
        nat = (e[7][1] or 0) if e[7] else 0
        if i:
            X[i, i] = 1
        X[i, 6] = nat
        X[i, 7] = nat * (i + 1) / 6
        c = CL.get(e[7][0] if e[7] else "", None)
        if c is not None:
            X[i, 8 + c] = 1
    return X


def _rows(races):
    for r in races:
        E = r[11]
        if len(E) != 6 or r[7] or any(e[2] is None or not e[7] for e in E):
            continue
        E = sorted(E, key=lambda e: e[2])
        if [e[2] for e in E] != [1, 2, 3, 4, 5, 6]:
            continue
        w = np.array([e[5] == 1 for e in E], float)
        if w.sum() != 1:
            continue
        yield r, E, features(E), w


def fit(rows):
    X = np.array([x for _, _, x, _ in rows])
    W = np.array([w for _, _, _, w in rows])

    def nll(b):
        z = X @ b
        z -= z.max(1, keepdims=True)
        p = np.exp(z)
        p /= p.sum(1, keepdims=True)
        return -np.log(p[W == 1] + 1e-12).sum()

    return minimize(nll, np.zeros(X.shape[2]), method="L-BFGS-B").x


def pwin(X, b):
    z = X @ b
    z -= z.max()
    p = np.exp(z)
    return p / p.sum()


def score(o, e):
    return (o + PRIOR) / (e + PRIOR)


def main(now=None):
    now = now or datetime.now(timezone(timedelta(hours=9)))
    since = (now - timedelta(days=365)).strftime("%Y%m%d")
    rows = list(_rows(load_all(since)))
    b = fit(rows)
    oe = defaultdict(lambda: defaultdict(lambda: [0, 0, 0.0]))
    for r, E, X, w in rows:
        p = pwin(X, b)
        for i, e in enumerate(E):
            a = oe[e[1]][i + 1]
            a[0] += 1
            a[1] += int(w[i])
            a[2] += float(p[i])
    out = {"since": since, "races": len(rows), "coef": [round(float(x), 4) for x in b],
           "oe": {t: {str(c): [v[0], v[1], round(v[2], 2)] for c, v in d.items()} for t, d in oe.items()}}
    with gzip.open(PATH, "wt", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"))
    print("overperf", len(rows), "races", len(oe), "racers")


def load():
    try:
        with gzip.open(PATH, "rt", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None


if __name__ == "__main__":
    main()
