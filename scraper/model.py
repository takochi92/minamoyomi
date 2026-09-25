"""学習済み予想モデル（学習と本番で同じ特徴量計算を共有する）。

・Stats … 過去レースの集計（選手×コース、1コース時の負け方、場×コース、全国）
・features() … 1レース6艇の特徴量。学習時は「その日より前」の Stats、本番は course_stats.json の Stats
・model.json … 条件付きロジットの係数（1着・2着・3着の3段）。scraper/train_model.py が作る
"""
from __future__ import annotations

import gzip
import json
import math
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

import numpy as np

KIM = ["逃げ", "差し", "まくり", "まくり差し", "抜き", "恵まれ"]
ATTACK = ["差し", "まくり", "まくり差し"]
M = 20        # 選手成績を全国平均に寄せる強さ（出走数換算）
MV = 50       # 場成績を全国平均に寄せる強さ
FEATS = ["base_w", "base_2", "base_3", "rc_win", "rc_place", "mu", "nat", "loc", "A1", "A2", "B2",
         "motor", "boat", "ex_dev", "ex_top", "avg_st", "f_recent", "wave_in", "wave_out", "wind_in", "wind_out"]
FEATURE_LABEL = {
    "base_w": "場のコース別1着率", "rc_win": "選手のコース別成績", "rc_place": "選手のコース別連対", "mu": "インの負け方×攻め手",
    "nat": "全国勝率", "loc": "当地勝率", "A1": "級別", "A2": "級別", "B2": "級別", "motor": "モーター", "boat": "ボート",
    "ex_dev": "展示タイム", "ex_top": "展示タイム", "avg_st": "平均ST", "f_recent": "F持ち",
    "wave_in": "波・風", "wave_out": "波・風", "wind_in": "波・風", "wind_out": "波・風",
}
ROOT = Path(__file__).parent
STATS_PATH = ROOT / "course_stats.json.gz"
MODEL_PATH = ROOT / "model.json"


# ---------------------------------------------------------------- 集計
class Stats:
    """レース記録 R = [date,jcd,rno,決まり手,風向,風速,波,固定,3連単,払戻,人気, entries]
       entry = [枠,登番,進入,ST(1/100秒),F/L,着(int or 記号),展示(1/100秒), 番組表情報 or None]"""

    def __init__(self):
        self.rc = defaultdict(lambda: defaultdict(lambda: np.zeros(10)))  # 登番→コース→[出走,1着,2着,3着,決まり手6]
        self.rl = defaultdict(Counter)                                     # 登番→1コースで負けた相手 "c-決まり手"
        self.rst = defaultdict(lambda: np.zeros(2))                         # 登番→[ST合計(秒), 件数]
        self.nc = defaultdict(lambda: np.zeros(10))
        self.nl = Counter()
        self.nn = 0
        self.vc = defaultdict(lambda: defaultdict(lambda: np.zeros(10)))
        self.vl = defaultdict(Counter)
        self.vn = Counter()

    def apply(self, r, sign=1):
        jcd, kim, E = r[1], r[3], r[11]
        ents = [e for e in E if e[2]]
        if len(ents) < 5:
            return
        k = kim if kim in KIM else None
        self.nn += sign
        self.vn[jcd] += sign
        win = next((e for e in ents if e[5] == 1), None)
        inb = next((e for e in ents if e[2] == 1), None)
        for e in ents:
            toban, course, st, flag, place = e[1], e[2], e[3], e[4], e[5]
            v = np.zeros(10)
            v[0] = 1
            if place in (1, 2, 3):
                v[place] = 1
            if place == 1 and k:
                v[4 + KIM.index(k)] = 1
            v *= sign
            self.rc[toban][course] += v
            self.nc[course] += v
            self.vc[jcd][course] += v
            if st is not None and not flag:
                self.rst[toban] += sign * np.array([st / 100, 1])
        if inb and win and win is not inb and k:
            key = f"{win[2]}-{k}"
            self.nl[key] += sign
            self.vl[jcd][key] += sign
            self.rl[inb[1]][key] += sign

    # ---- 保存・読込
    def to_json(self) -> dict:
        def arr(a):
            return [round(float(x), 3) for x in a]
        return {
            "nn": self.nn, "nl": dict(self.nl), "nc": {str(c): arr(v) for c, v in self.nc.items()},
            "vn": dict(self.vn), "vl": {j: dict(v) for j, v in self.vl.items()},
            "vc": {j: {str(c): arr(v) for c, v in d.items()} for j, d in self.vc.items()},
            "r": {t: {"c": {str(c): arr(v) for c, v in d.items() if v[0] > 0}, "l": dict(self.rl[t]), "s": arr(self.rst[t])}
                  for t, d in self.rc.items() if any(v[0] > 0 for v in d.values())},
        }

    @classmethod
    def from_json(cls, j: dict) -> "Stats":
        S = cls()
        S.nn = j["nn"]
        S.nl = Counter(j["nl"])
        for c, v in j["nc"].items():
            S.nc[int(c)] = np.array(v)
        S.vn = Counter(j["vn"])
        for jcd, d in j["vl"].items():
            S.vl[jcd] = Counter(d)
        for jcd, d in j["vc"].items():
            for c, v in d.items():
                S.vc[jcd][int(c)] = np.array(v)
        for t, d in j["r"].items():
            for c, v in d["c"].items():
                S.rc[t][int(c)] = np.array(v)
            S.rl[t] = Counter(d["l"])
            S.rst[t] = np.array(d["s"])
        return S


@lru_cache(maxsize=1)
def load_stats():
    if not STATS_PATH.exists():
        return None
    with gzip.open(STATS_PATH, "rt", encoding="utf-8") as f:
        return Stats.from_json(json.load(f))


@lru_cache(maxsize=1)
def load_model():
    if not MODEL_PATH.exists():
        return None
    return json.loads(MODEL_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 特徴量
def _z(vals):
    a = np.array([v if v is not None else np.nan for v in vals], float)
    if not np.isfinite(a).any():
        return np.zeros(len(vals))
    m = np.nanmean(a)
    s = np.nanstd(a) if np.isfinite(a).sum() > 1 else 1.0
    return np.nan_to_num((a - m) / (s or 1.0))


def national_rates(S, c):
    n = S.nc[c]
    if not n[0]:
        return [0.1, 0.1, 0.1]
    return [max(n[i] / n[0], 0.005) for i in (1, 2, 3)]


def features(S: Stats, jcd: str, wave, wind_speed, boats: list[dict]) -> np.ndarray:
    """boats: 枠順に6艇 {frame, toban, course, ex(1/100秒 or None), cls, nat, loc, motor, boat, f_recent}"""
    X = np.zeros((6, len(FEATS)))
    fi = {n: i for i, n in enumerate(FEATS)}
    p = {c: national_rates(S, c) for c in range(1, 7)}
    nat = _z([b["nat"] for b in boats])
    loc = _z([b["loc"] if (b["loc"] or 0) > 0 else None for b in boats])
    mot = _z([b["motor"] for b in boats])
    bt = _z([b["boat"] for b in boats])
    exs = [b["ex"] for b in boats]
    has_ex = all(exs)
    exm = float(np.mean(exs)) if has_ex else 0
    exmin = min(exs) if has_ex else 0
    inb = next((b for b in boats if b["course"] == 1), None)
    A = S.rl[inb["toban"]] if inb else Counter()
    an = S.rc[inb["toban"]][1][0] if inb else 0
    wave = wave or 0
    ws = wind_speed or 0
    for i, b in enumerate(boats):
        c, toban = b["course"], b["toban"]
        vc = S.vc[jcd][c]
        for j, name in ((1, "base_w"), (2, "base_2"), (3, "base_3")):
            pv = (vc[j] + MV * p[c][j - 1]) / (vc[0] + MV)
            X[i, fi[name]] = math.log(max(pv, 0.003))
        me = S.rc[toban][c]
        X[i, fi["rc_win"]] = math.log(((me[1] + M * p[c][0]) / (me[0] + M)) / p[c][0])
        X[i, fi["rc_place"]] = math.log(((me[2] + me[3] + M * (p[c][1] + p[c][2])) / (me[0] + M)) / (p[c][1] + p[c][2]))
        if c != 1 and inb and S.nn:
            num = den = 0.0
            nc = S.nc[c]
            for k in ATTACK:
                key = f"{c}-{k}"
                pl = S.nl[key] / S.nn
                pa = nc[4 + KIM.index(k)] / nc[0] if nc[0] else 0
                if pl <= 0 or pa <= 0:
                    continue
                a_l = ((A[key] + M * pl) / (an + M)) / pl
                b_a = ((me[4 + KIM.index(k)] + M * pa) / (me[0] + M)) / pa
                num += pl * a_l * b_a
                den += pl
            if den:
                X[i, fi["mu"]] = math.log(num / den)
        X[i, fi["nat"]] = nat[i]
        X[i, fi["loc"]] = loc[i]
        X[i, fi["A1"]] = b["cls"] == "A1"
        X[i, fi["A2"]] = b["cls"] == "A2"
        X[i, fi["B2"]] = b["cls"] == "B2"
        X[i, fi["motor"]] = mot[i]
        X[i, fi["boat"]] = bt[i]
        if has_ex:
            X[i, fi["ex_dev"]] = np.clip((exm - b["ex"]) / 5, -3, 3)
            X[i, fi["ex_top"]] = b["ex"] == exmin
        rs = S.rst[toban]
        if rs[1] >= 5:
            X[i, fi["avg_st"]] = np.clip(0.17 - rs[0] / rs[1], -0.08, 0.08) * 10
        X[i, fi["f_recent"]] = min(b.get("f_recent", 0) or 0, 2)
        X[i, fi["wave_in"]] = wave / 10 if c == 1 else 0
        X[i, fi["wave_out"]] = wave / 10 if c >= 4 else 0
        X[i, fi["wind_in"]] = ws / 5 if c == 1 else 0
        X[i, fi["wind_out"]] = ws / 5 if c >= 4 else 0
    return X


def stage_scores(X: np.ndarray, model: dict) -> dict:
    """段ごとの強さ（対数スケール）と、特徴量ごとの寄与"""
    out = {}
    for st in ("1", "2", "3"):
        coef = model["coef"][st]
        idx = [FEATS.index(n) for n in coef]
        w = np.array(list(coef.values()))
        out[st] = X[:, idx] @ w
        if st == "1":
            out["contrib"] = X[:, idx] * w
            out["contrib_names"] = list(coef)
    return out
