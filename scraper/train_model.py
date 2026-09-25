"""過去データで予想モデルを学習・検証する。

  python -m scraper.train_model

1. history/ の全レースを日付順に流し、各レースの特徴量を「その日より前の直近365日」だけで計算
   （未来の情報が混ざらない）
2. 直近365日を検証用に取り分け、それより前で学習 → 検証期間で的中率・回収率を測る
3. 全期間で学習し直した係数を scraper/model.json に保存
4. 検証結果を scraper/model_report.json に保存（サイトの「予想の根拠」ページで公開）
"""
from __future__ import annotations

import itertools
import json
from collections import defaultdict, deque
from datetime import date as Date

import numpy as np
from scipy.optimize import minimize

from .history import load_all
from .model import FEATS, KIM, MODEL_PATH, ROOT, Stats, features

WINDOW = 365
WARMUP = 365
ABILITY = ["nat", "loc", "A1", "A2", "B2", "motor", "boat", "ex_dev", "ex_top", "avg_st", "f_recent"]
WEATHER = ["wave_in", "wave_out", "wind_in", "wind_out"]
STAGE_COLS = {
    "1": ["base_w"] + ABILITY + ["rc_win", "mu"] + WEATHER,
    "2": ["base_2", "rc_place"] + ABILITY + ["rc_win", "mu"] + WEATHER,
    "3": ["base_3", "rc_place"] + ABILITY + ["rc_win", "mu"] + WEATHER,
}
VARIANTS = {
    "コースだけ（場のコース別1着率）": ["base_w"],
    "＋選手力・機力・展示": ["base_w"] + ABILITY,
    "＋選手のコース別成績": ["base_w"] + ABILITY + ["rc_win"],
    "＋インの負け方×攻め手": ["base_w"] + ABILITY + ["rc_win", "mu"],
    "＋波・風（最終モデル）": STAGE_COLS["1"],
}


def _ord(d):
    return Date(int(d[:4]), int(d[4:6]), int(d[6:])).toordinal()


def build_dataset(races, pre=None):
    """pre: {key: {"course": {枠: コース}, "wave": cm, "wind": m}} 締切前に分かる進入・気象で上書き（検証用）"""
    races.sort(key=lambda r: (r[0], r[1], r[2]))
    by_day = defaultdict(list)
    for r in races:
        by_day[r[0]].append(r)
    days = sorted(by_day)
    start = _ord(days[0]) + WARMUP
    S, window, fh = Stats(), deque(), defaultdict(deque)
    Xs, Ps, D, T, PAY, MK, KEY = [], [], [], [], [], [], []
    for d in days:
        t = _ord(d)
        while window and window[0][0] < t - WINDOW:
            for r in window.popleft()[1]:
                S.apply(r, -1)
        if t >= start:
            for r in by_day[d]:
                E = sorted(r[11], key=lambda e: e[0])
                if len(E) != 6 or any(e[2] is None or not e[7] for e in E) or len({e[2] for e in E}) != 6:
                    continue
                if not any(e[5] == 1 for e in E):
                    continue
                key = f"{d}-{r[1]}-{r[2]}"
                ov = (pre or {}).get(key)
                boats = []
                for e in E:
                    q = fh[e[1]]
                    while q and q[0] < t - 180:
                        q.popleft()
                    b = e[7]
                    boats.append({"frame": e[0], "toban": e[1], "course": ov["course"][e[0]] if ov else e[2], "ex": e[6], "cls": b[0], "nat": b[1],
                                  "loc": b[3], "motor": b[5], "boat": b[6], "f_recent": len(q)})
                Xs.append(features(S, r[1], ov["wave"] if ov else r[6], ov["wind"] if ov else r[5], boats))
                Ps.append([e[5] if isinstance(e[5], int) else 9 for e in E])
                D.append(int(d)); T.append(r[8] or ""); PAY.append(r[9] or 0); KEY.append(key)
                MK.append(_matchup_row(S, E, r))
        for r in by_day[d]:
            S.apply(r, 1)
            for e in r[11]:
                if e[4] == "F" or e[5] == "F":
                    fh[e[1]].append(t)
        window.append((t, by_day[d]))
    build_dataset.keys = np.array(KEY)
    return (np.array(Xs), np.array(Ps, np.int8), np.array(D), np.array(T), np.array(PAY), MK)


def _matchup_row(S, E, r):
    """仮説の直接検証用：インの捲られ率と、3・4コース艇のそのコースでの捲り勝ち率"""
    inb = next((e for e in E if e[2] == 1), None)
    win = next((e for e in E if e[5] == 1), None)
    an = S.rc[inb[1]][1][0] if inb else 0
    if not inb or an < 20:
        return None
    mk_in = sum(v for k, v in S.rl[inb[1]].items() if k.endswith("-まくり")) / an
    out = []
    for c in (3, 4):
        b = next(e for e in E if e[2] == c)
        me = S.rc[b[1]][c]
        if me[0] >= 15:
            out.append((c, mk_in, me[4 + KIM.index("まくり")] / me[0], int(win is b and r[3] == "まくり"), int(win is b)))
    return out


# ---------------------------------------------------------------- 条件付きロジット
def fit(Xs, y, mask, l2=1e-3):
    R, n, K = Xs.shape

    def f(b):
        z = np.where(mask, Xs @ b, -1e9)
        zmax = z.max(1, keepdims=True)
        e = np.exp(z - zmax) * mask
        s = e.sum(1)
        ll = z[np.arange(R), y] - zmax[:, 0] - np.log(s)
        p = e / s[:, None]
        g = Xs[np.arange(R), y] - np.einsum("rn,rnk->rk", p, Xs)
        return -ll.mean() + l2 * b @ b, -g.mean(0) + 2 * l2 * b

    return minimize(f, np.zeros(K), jac=True, method="L-BFGS-B").x


def stage_data(X, P, cols, stage):
    ok = np.ones(len(P), bool)
    for s in range(1, stage + 1):
        ok &= (P == s).any(1)
    Xs = X[ok][:, :, [FEATS.index(c) for c in cols]]
    y = (P[ok] == stage).argmax(1)
    mask = P[ok] >= stage
    return Xs, y, mask


def fit_all(X, P):
    return {st: dict(zip(cols, map(float, fit(*stage_data(X, P, cols, int(st)))))) for st, cols in STAGE_COLS.items()}


def trifecta_probs(X, coef):
    sc = {}
    for st, c in coef.items():
        idx = [FEATS.index(n) for n in c]
        s = X[:, :, idx] @ np.array(list(c.values()))
        sc[st] = np.exp(s - s.max(1, keepdims=True))
    p1 = sc["1"] / sc["1"].sum(1, keepdims=True)
    combos = list(itertools.permutations(range(6), 3))
    out = np.zeros((len(X), 120))
    for k, (a, b, c) in enumerate(combos):
        pb = sc["2"][:, b] / (sc["2"].sum(1) - sc["2"][:, a])
        pc = sc["3"][:, c] / (sc["3"].sum(1) - sc["3"][:, a] - sc["3"][:, b])
        out[:, k] = p1[:, a] * pb * pc
    return out / out.sum(1, keepdims=True), p1, [f"{a+1}-{b+1}-{c+1}" for a, b, c in combos]


def evaluate(X, P, T, PAY, coef):
    pt, p1, names = trifecta_probs(X, coef)
    names = np.array(names)
    valid = (T != "") & (PAY > 0)
    order = np.argsort(-pt, 1)
    rank = np.full(len(X), 999)
    for i in np.where(valid)[0]:
        w = np.where(names[order[i]] == T[i])[0]
        if len(w):
            rank[i] = w[0]
    n = int(valid.sum())
    topn = {str(N): {"hit": round(float(((rank < N) & valid).sum() / n), 4),
                     "roi": round(float(PAY[(rank < N) & valid].sum() / (N * 100 * n)), 4)} for N in (1, 3, 5, 8, 10, 15, 20)}
    conf = {}
    pm = p1.max(1)
    for lo, hi, lab in ((0.65, 9, "鉄板"), (0.5, 0.65, "本命"), (0.38, 0.5, "やや混戦"), (0, 0.38, "混戦・荒れ注意")):
        m = valid & (pm >= lo) & (pm < hi)
        if m.sum():
            conf[lab] = {"races": int(m.sum()), "win_acc": round(float((p1[m].argmax(1) == (P[m] == 1).argmax(1)).mean()), 4),
                         "top8_hit": round(float(((rank < 8) & m).sum() / m.sum()), 4),
                         "top8_roi": round(float(PAY[(rank < 8) & m].sum() / (800 * m.sum())), 4)}
    return {"races": n, "trifecta_topN": topn, "by_confidence": conf}


def matchup_table(MK):
    rows = [x for m in MK if m for x in m]
    a = np.array(rows)
    out = {}
    for c in (3, 4):
        x = a[a[:, 0] == c]
        qi, qb = np.quantile(x[:, 1], [1 / 3, 2 / 3]), np.quantile(x[:, 2], [1 / 3, 2 / 3])
        ti, tb = np.digitize(x[:, 1], qi), np.digitize(x[:, 2], qb)
        grid = [[{"n": int(((ti == i) & (tb == j)).sum()),
                  "makuri_win": round(float(x[(ti == i) & (tb == j), 3].mean()), 4),
                  "win": round(float(x[(ti == i) & (tb == j), 4].mean()), 4)} for j in range(3)] for i in range(3)]
        out[str(c)] = {"in_cut": [round(float(v), 3) for v in qi], "att_cut": [round(float(v), 3) for v in qb], "grid": grid}
    return out


def main():
    races = load_all()
    X, P, D, T, PAY, MK = build_dataset(races)
    last = D.max()
    cut = int((Date.fromordinal(_ord(str(last)) - 364)).strftime("%Y%m%d"))
    tr, te = D < cut, D >= cut
    print("train", tr.sum(), "test", te.sum())

    variants = {}
    for name, cols in VARIANTS.items():
        b = fit(*stage_data(X[tr], P[tr], cols, 1))
        Xv, yv, mv = stage_data(X[te], P[te], cols, 1)
        z = np.where(mv, Xv[:, :, :] @ b, -1e9)
        p = np.exp(z - z.max(1, keepdims=True)) * mv
        p /= p.sum(1, keepdims=True)
        variants[name] = {"logloss": round(float(-np.log(p[np.arange(len(yv)), yv]).mean()), 4),
                          "win_acc": round(float((p.argmax(1) == yv).mean()), 4)}
        print(name, variants[name])

    coef_tr = fit_all(X[tr], P[tr])
    ev = evaluate(X[te], P[te], T[te], PAY[te], coef_tr)
    coef = fit_all(X, P)
    period = {"train": [str(D[tr].min()), str(D[tr].max())], "test": [str(D[te].min()), str(D[te].max())]}
    MODEL_PATH.write_text(json.dumps({"coef": coef, "trained_on": [str(D.min()), str(D.max())], "races": int(len(D))},
                                     ensure_ascii=False, indent=1), encoding="utf-8")
    report = {"period": period, "n_train": int(tr.sum()), "n_test": int(te.sum()), "variants": variants,
              "test": ev, "matchup": matchup_table([m for m, t in zip(MK, te) if t or True]),
              "coef": {k: round(v, 3) for k, v in coef["1"].items()}}
    rp = ROOT / "model_report.json"
    old = json.loads(rp.read_text(encoding="utf-8")) if rp.exists() else {}
    rp.write_text(json.dumps({**old, **report}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(ev, ensure_ascii=False))


if __name__ == "__main__":
    main()
