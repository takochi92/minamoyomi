"""バフの数ごとに、実際の1着率が「市場（オッズ）」「AI」の見込みより上か下かを過去レースで調べる。

  python -m tools.buff_eval            # 結果を表で出し、scraper/buff_report.json に保存

・バフの計算はサイトと同じ（sitegen.buffs、予想モデル model.json の1着の段の寄与を要素ごとに足したもの）
・進入・波・風は締切前に分かる展示の情報を使う（実際の進入は使わない）
・市場の見込みは確定3連単オッズから出した1着の確率（控除分をならしたもの）
・95%区間は二項分布の正規近似。z は「市場の見込みどおりなら」からのずれ
"""
from __future__ import annotations

import json
import math
from collections import defaultdict

import numpy as np

from scraper import odds as O
from scraper.history import load_all
from scraper.model import FEATS, FEATURE_LABEL, MODEL_PATH
from scraper.sitegen import BUFF, buffs
from scraper.train_model import build_dataset, trifecta_probs

OUT = MODEL_PATH.parent / "buff_report.json"


def main():
    model = json.loads(MODEL_PATH.read_text(encoding="utf-8"))
    allodds = O.load_all()
    first = min(k[:8] for k in allodds)
    since = str(int(first[:4]) - 1) + first[4:8]           # オッズのある期間の1年前から（集計の助走）
    races = load_all(since)
    pre = O.pre_race_overrides(O.load_before())
    X, P, D, T, PAY, _ = build_dataset(races, pre)
    keys = build_dataset.keys
    sel = np.array([k in allodds and k in pre for k in keys])
    X, P, keys = X[sel], P[sel], keys[sel]
    print("races with odds", len(keys))
    _, p1, _ = trifecta_probs(X, model["coef"])
    c1 = model["coef"]["1"]
    idx = [FEATS.index(n) for n in c1]
    contrib = X[:, :, idx] * np.array(list(c1.values()))
    labels = [FEATURE_LABEL.get(n, n) for n in c1]
    firsts = [int(c[0]) - 1 for c in O.COMBOS]
    rows = []
    for i, k in enumerate(keys):
        q = O.market_probs(list(allodds[k]))
        mw = np.zeros(6)
        for j, v in enumerate(q):
            mw[firsts[j]] += v
        for b in range(6):
            parts = defaultdict(float)
            for lab, v in zip(labels, contrib[i, b]):
                parts[lab] += float(v)
            bf = buffs(parts)
            course = pre[k]["course"][b + 1]
            rows.append((sum(1 for _, lv in bf if lv > 0), sum(1 for _, lv in bf if lv == 2), tuple(sorted(n for n, lv in bf if lv > 0)),
                         course, int(P[i, b] == 1), float(p1[i, b]), float(mw[b])))

    def summarize(sub):
        n = len(sub)
        if not n:
            return None
        w = sum(r[4] for r in sub)
        ai = sum(r[5] for r in sub)
        mk = sum(r[6] for r in sub)
        rate = w / n
        se = math.sqrt(max(rate * (1 - rate), 1e-9) / n)
        sd_m = math.sqrt(sum(r[6] * (1 - r[6]) for r in sub)) or 1
        return {"n": n, "win": round(rate, 4), "ci": [round(rate - 1.96 * se, 4), round(rate + 1.96 * se, 4)],
                "ai": round(ai / n, 4), "market": round(mk / n, 4), "vs_market": round(rate / (mk / n), 3) if mk else None,
                "z": round((w - mk) / sd_m, 2)}

    rep = {"races": int(len(keys)), "period": [str(min(k[:8] for k in keys)), str(max(k[:8] for k in keys))], "by_count": {}, "by_count_out": {}, "by_buff": {}}
    for c in range(6):
        s = summarize([r for r in rows if r[0] == c])
        if s:
            rep["by_count"][str(c)] = s
        s = summarize([r for r in rows if r[0] == c and r[3] >= 2])
        if s:
            rep["by_count_out"][str(c)] = s
    for name in BUFF:
        s = summarize([r for r in rows if name in r[2]])
        rep["by_buff"][name] = s
    s = summarize([r for r in rows if r[0] >= 3 and r[1] >= 1])
    rep["3plus_with_strong"] = s
    # 金・銀の候補（金＝▲4つ以上、銀＝金でなくて条件を満たす艇）
    cand = {"gold": lambda r: r[0] >= 4,
            "silver:モーター+展示": lambda r: r[0] < 4 and {"モーター", "展示"} <= set(r[2]),
            "silver:モーター+得意コース": lambda r: r[0] < 4 and {"モーター", "得意コース"} <= set(r[2]),
            "silver:モーター+(展示か得意コース)": lambda r: r[0] < 4 and "モーター" in r[2] and ({"展示", "得意コース"} & set(r[2])),
            "silver:▲3つ": lambda r: r[0] == 3}
    half = len(rows) // 2      # 前半・後半に分けても同じ向きか
    rep["tiers"] = {k: {"all": summarize([r for r in rows if f(r)]), "first": summarize([r for r in rows[:half] if f(r)]),
                        "second": summarize([r for r in rows[half:] if f(r)])} for k, f in cand.items()}
    combos = defaultdict(list)
    for r in rows:
        if r[0] >= 2:
            combos["+".join(r[2])].append(r)
    rep["combos"] = {k: summarize(v) for k, v in sorted(combos.items(), key=lambda x: -len(x[1])) if len(v) >= 150}
    OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(rep, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
