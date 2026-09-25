"""オッズ×AIの合成で「期待値のある買い目」だけ買った場合の成績を、過去の確定オッズで検証する。

  python -m scraper.ev_eval

・AIは検証期間（直近365日）より前のデータだけで学習
・検証期間のオッズのあるレースを日付の偶数日／奇数日に分け、片方で合成の割合(a,b)を決めてもう片方で成績を測る（交差検証）
・買い方のルールは事前に固定：合成確率×オッズ ≥ 1.0、オッズ200倍以下
・結果は model_report.json の "ev" に、合成の割合は model.json の "blend" に保存
・95%区間の下限が100%を超えたら status を「有効」、それ以外は「検証中」
"""
from __future__ import annotations

import json
from datetime import date as Date

import numpy as np

from . import odds as O
from .history import load_all
from .model import FEATS, MODEL_PATH, ROOT
from .train_model import _ord, build_dataset, fit_all, trifecta_probs

RULE = {"ev_min": 1.0, "max_odds": 200.0}
NOTE = ("はじめは「実際の進入コース」で検証して回収率205%に見えましたが、実際の進入は締切後にしか分からない情報のため不採用にしました。"
        "展示の並び・直前の気象だけで検証し直すと、期待値が1を超える買い目はほぼ出なくなります。"
        "オッズを土台に、AI・展示ST・チルトで補正するモデルも試しましたが、1着予想の精度が市場をわずかに上回るだけで、控除率25%を越える買い目は出ませんでした。"
        "確定オッズと直前情報は毎晩集め続け、条件を満たした時点で自動的に「有効」に切り替わります。")
GRID = [round(x, 1) for x in np.arange(0.0, 1.61, 0.1)]


def _blend(q, m, a, b):
    z = a * np.log(np.clip(q, 1e-9, 1)) + b * np.log(np.clip(m, 1e-9, 1))
    z = np.where(q > 0, np.exp(z - z.max(1, keepdims=True)), 0)
    return z / z.sum(1, keepdims=True)


def _fit_ab(q, m, win):
    best = None
    for a in GRID:
        for b in GRID:
            if a == 0 and b == 0:
                continue
            p = _blend(q, m, a, b)
            v = float(-np.log(np.clip(p[win], 1e-9, 1)).mean())
            if best is None or v < best[0]:
                best = (v, a, b)
    return best[1], best[2]


def _strategy(p, odds, win, pay, rule):
    sel = (p * odds >= rule["ev_min"]) & np.isfinite(odds) & (odds <= rule["max_odds"])
    hit = (sel & win).any(1)
    ret = np.where(hit, pay, 0).astype(float)
    cost = sel.sum(1) * 100.0
    return sel, ret, cost


def _summary(ret, cost, sel, n_races):
    idx = np.where(cost > 0)[0]
    if not len(idx):
        return {"races_checked": int(n_races), "bet_races": 0, "bets": 0, "hits": 0, "invest": 0, "return": 0, "roi": None, "ci95": None}
    rng = np.random.default_rng(0)
    boots = [ret[s].sum() / cost[s].sum() for s in (rng.choice(idx, len(idx)) for _ in range(2000))]
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return {"races_checked": int(n_races), "bet_races": int(len(idx)), "bets": int(sel.sum()),
            "hits": int((ret > 0).sum()), "invest": int(cost.sum()), "return": int(ret.sum()),
            "roi": round(float(ret.sum() / cost.sum()), 3), "ci95": [round(float(lo), 3), round(float(hi), 3)]}


def main():
    races = load_all()
    pre = O.pre_race_overrides(O.load_before())
    X, P, D, T, PAY, _ = build_dataset(races, pre)
    keys = build_dataset.keys
    cut = int(Date.fromordinal(_ord(str(D.max())) - 364).strftime("%Y%m%d"))
    tr = D < cut
    coef = fit_all(X[tr], P[tr])
    allodds = O.load_all()
    # 検証はオッズと直前情報（展示の進入）の両方があるレースだけ。進入は展示の並びを使う（実際の進入は締切後の情報なので使わない）
    te = np.where((D >= cut) & np.array([k in allodds and k in pre for k in keys]) & (T != "") & (PAY > 0))[0]
    print("検証レース（オッズあり）", len(te))
    pt, p1, names = trifecta_probs(X[te], coef)
    odds = np.array([allodds[k] for k in keys[te]], float)
    q = np.array([O.market_probs(list(o)) for o in odds])
    win = np.zeros_like(pt, bool)
    for i, t in enumerate(T[te]):
        if t in names:
            win[i, names.index(t)] = True
    pay = PAY[te]
    even = (D[te] % 2 == 0)

    rets, costs, sels, folds = np.zeros(len(te)), np.zeros(len(te)), np.zeros_like(win), []
    for fit_mask in (even, ~even):
        a, b = _fit_ab(q[fit_mask], pt[fit_mask], win[fit_mask])
        ev_mask = ~fit_mask
        p = _blend(q[ev_mask], pt[ev_mask], a, b)
        sel, ret, cost = _strategy(p, odds[ev_mask], win[ev_mask], pay[ev_mask], RULE)
        rets[ev_mask], costs[ev_mask], sels[ev_mask] = ret, cost, sel
        folds.append({"market": a, "model": b})
    main_res = _summary(rets, costs, sels, len(te))

    # 参考：ルール違いとAI単独
    variants = {}
    for cap in (50.0, 200.0, 1e9):
        r2, c2, s2 = np.zeros(len(te)), np.zeros(len(te)), np.zeros_like(win)
        for fit_mask, f in zip((even, ~even), folds):
            ev_mask = ~fit_mask
            p = _blend(q[ev_mask], pt[ev_mask], f["market"], f["model"])
            s, r, c = _strategy(p, odds[ev_mask], win[ev_mask], pay[ev_mask], {"ev_min": 1.0, "max_odds": cap})
            r2[ev_mask], c2[ev_mask], s2[ev_mask] = r, c, s
        variants[f"オッズ{int(cap) if cap < 1e8 else '上限なし'}倍まで"] = _summary(r2, c2, s2, len(te))
    s, r, c = _strategy(pt, odds, win, pay, RULE)
    variants["AI単独（オッズを混ぜない）"] = _summary(r, c, s, len(te))
    nb = np.ones(len(te), bool)
    for N in (8,):
        order = np.argsort(-pt, 1)[:, :N]
        sel = np.zeros_like(win)
        np.put_along_axis(sel, order, True, 1)
        hit = (sel & win).any(1)
        variants["参考：AIの上位8点を全レース"] = _summary(np.where(hit, pay, 0).astype(float), sel.sum(1) * 100.0, sel, len(te))

    a, b = _fit_ab(q, pt, win)
    status = "有効" if (main_res.get("ci95") or [0])[0] > 1.0 else "検証中"
    blend = {"market": a, "model": b, **RULE, "status": status}
    model = json.loads(MODEL_PATH.read_text(encoding="utf-8"))
    model["blend"] = blend
    MODEL_PATH.write_text(json.dumps(model, ensure_ascii=False, indent=1), encoding="utf-8")
    rp = ROOT / "model_report.json"
    report = json.loads(rp.read_text(encoding="utf-8")) if rp.exists() else {}
    report["ev"] = {"period": [str(D[te].min()), str(D[te].max())], "races": int(len(te)), "rule": RULE,
                    "folds": folds, "result": main_res, "variants": variants, "blend": blend,
                    "market_ll": round(float(-np.log(np.clip(q[win], 1e-9, 1)).mean()), 4),
                    "model_ll": round(float(-np.log(np.clip(pt[win], 1e-9, 1)).mean()), 4),
                    "note": NOTE}
    report["specialist"] = specialist_table(races, keys[te], P[te], X[te], q, pre)
    rp.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report["ev"], ensure_ascii=False, indent=1))


def specialist_table(races, keys, P, X, q, pre):
    """B級の外コース巧者（コース別成績が全国平均より高い）の、実際の1着率と市場の見立ての比較"""
    info = {f"{r[0]}-{r[1]}-{r[2]}": r for r in races}
    rc = X[:, :, FEATS.index("rc_win")]
    q1 = q.reshape(-1, 6, 20).sum(2)
    won = P == 1
    cls = np.array([[e[7][0] if e[7] else "" for e in sorted(info[k][11], key=lambda e: e[0])] for k in keys])
    course = np.array([[pre[k]["course"][f] for f in range(1, 7)] for k in keys])
    out = {}
    for c in range(2, 7):
        m = np.isin(cls, ["B1", "B2"]) & (course == c) & (rc >= 0.4)
        if m.sum() >= 20:
            out[str(c)] = {"boats": int(m.sum()), "win": round(float(won[m].mean()), 3), "market": round(float(q1[m].mean()), 3)}
    return out


if __name__ == "__main__":
    main()
