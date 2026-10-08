"""乗り手を差し引いたモーター評価（motor_adj）が予想に効くかを確かめる。

  python -m tools.motor_eval

モーター番号のそろっている期間のレースを日付で前後に分け、前で学習・後ろで検証する。
「いまの特徴量」と「＋motor_adj」「モーター2連率を motor_adj に置きかえ」を比べる。
"""
from __future__ import annotations

import json
import sys
from datetime import date as Date, timedelta

import numpy as np

from scraper.history import load_all
from scraper.model import FEATS
from scraper.train_model import STAGE_COLS, build_dataset, evaluate, fit, stage_data


def logloss(X, P, cols, tr, te, stage=1):
    b = fit(*stage_data(X[tr], P[tr], cols, stage))
    Xv, yv, mv = stage_data(X[te], P[te], cols, stage)
    z = np.where(mv, Xv @ b, -1e9)
    p = np.exp(z - z.max(1, keepdims=True)) * mv
    p /= p.sum(1, keepdims=True)
    return float(-np.log(p[np.arange(len(yv)), yv]).mean()), float((p.argmax(1) == yv).mean()), dict(zip(cols, b))


def main():
    allr = load_all()
    withm = sorted({r[0] for r in allr if all(len(e) > 8 and e[8] is not None for e in r[11])})
    m0 = withm[0]
    since = (Date(int(m0[:4]), int(m0[4:6]), int(m0[6:])) - timedelta(days=365)).strftime("%Y%m%d")
    races = [r for r in allr if r[0] >= since]
    del allr
    print("motor_no from", m0, "races since", since, len(races), file=sys.stderr)
    X, P, D, T, PAY, _ = build_dataset(races)
    ia = FEATS.index("motor_adj")
    cov = (X[:, :, ia] != 0).any(1)
    days = np.unique(D)
    cut = days[int(len(days) * 0.55)]
    tr, te = D < cut, D >= cut
    print("samples", len(D), "train", int(tr.sum()), "test", int(te.sum()), "cut", cut, "motor_adj入り", float(cov[te].mean()), file=sys.stderr)
    out = {"train": [int(D[tr].min()), int(D[tr].max())], "test": [int(D[te].min()), int(D[te].max())],
           "coverage_test": round(float(cov[te].mean()), 3)}
    variants = {
        "いま": STAGE_COLS,
        "＋乗り手を引いたモーター": {k: v + ["motor_adj"] for k, v in STAGE_COLS.items()},
        "モーター2連率→置きかえ": {k: [c if c != "motor" else "motor_adj" for c in v] for k, v in STAGE_COLS.items()},
    }
    for name, cols in variants.items():
        res = {}
        for st in ("1", "2", "3"):
            ll, acc, b = logloss(X, P, cols[st], tr, te, int(st))
            res[st] = {"logloss": round(ll, 5), "acc": round(acc, 4)}
            if st == "1":
                res["coef"] = {k: round(float(b[k]), 3) for k in ("motor", "motor_adj") if k in b}
        coef = {st: dict(zip(c, map(float, fit(*stage_data(X[tr], P[tr], c, int(st)))))) for st, c in cols.items()}
        ev = evaluate(X[te], P[te], T[te], PAY[te], coef)
        res["top"] = {n: ev["trifecta_topN"][n] for n in ("1", "5", "10")}
        out[name] = res
        print(name, json.dumps(res, ensure_ascii=False), file=sys.stderr)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
