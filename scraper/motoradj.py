"""乗り手を差し引いたモーター評価。

番組表のモーター2連率は「そのモーターに乗った選手の腕」も混ざっている。
ここでは1走ごとに「2着以内に入ったか（1/0）」から「その選手の全国2連率とコースから見込める2着以内の率」を引き、
その差をモーターごとに足していく（入れ替え後だけ）。プラスなら「乗り手の力以上に走っている」モーター。

  value = 差の合計 / (走数 + K)   … 走数が少ないうちは0に寄せる
"""
from __future__ import annotations

from collections import defaultdict

K = 20          # 0に寄せる強さ（走数換算）
BUCKET = 5      # 全国2連率を5%きざみで分ける


def _bucket(nat2):
    return max(0, min(int((nat2 or 0) // BUCKET), 14))


def base_table(races: list) -> dict:
    """(コース, 全国2連率の区分) → 2着以内の率。モーター番号のない古い記録でも作れる"""
    acc = defaultdict(lambda: [0, 0])
    for r in races:
        for e in r[11]:
            b = e[7] if len(e) > 7 else None
            if not e[2] or not b or not isinstance(e[5], int):
                continue
            a = acc[(e[2], _bucket(b[2]))]
            a[0] += 1
            a[1] += int(e[5] <= 2)
    out = {}
    for c in range(1, 7):
        tot = [sum(v[i] for (cc, _), v in acc.items() if cc == c) for i in (0, 1)]
        pc = tot[1] / tot[0] if tot[0] else 0.33
        for k in range(15):
            n, w = acc.get((c, k), (0, 0))
            out[(c, k)] = (w + 50 * pc) / (n + 50)
    return out


def renewed_venues(day_races: list) -> set:
    """その日に番組表のモーター2連率がほぼ全艇0.00の場（＝モーターが新しくなった開催）"""
    cnt = defaultdict(lambda: [0, 0])
    for r in day_races:
        for e in r[11]:
            b = e[7] if len(e) > 7 else None
            if b and len(b) > 5 and b[5] is not None:
                cnt[r[1]][0] += 1
                cnt[r[1]][1] += int(b[5] == 0)
    return {j for j, (n, z) in cnt.items() if n >= 24 and z / n >= 0.9}


class MotorAdj:
    def __init__(self, base: dict):
        self.base = base
        self.m = defaultdict(lambda: [0, 0.0])     # (場, 号機) → [走数, 差の合計]
        self.fresh = defaultdict(bool)             # 場 → 入れ替えを見た後か（見る前の号機は前のモーターかもしれないので使わない）
        self.last = {}                             # 場 → 最後に「全艇0.00」だった日（序数）

    def start_day(self, day_races: list, t: int):
        """t: 日付の序数。新モーターの最初の開催は数日続けて0.00なので、前の0.00の日から4日以上あいたときだけ数え直す"""
        for j in renewed_venues(day_races):
            if t - self.last.get(j, -99) > 3:
                for k in [k for k in self.m if k[0] == j]:
                    del self.m[k]
            self.last[j] = t
            self.fresh[j] = True

    def value(self, jcd, mno):
        if mno is None or not self.fresh[jcd]:
            return 0.0
        v = self.m.get((jcd, mno))
        return v[1] / (v[0] + K) if v else 0.0

    def apply(self, r):
        if not self.fresh[r[1]]:
            return
        for e in r[11]:
            b = e[7] if len(e) > 7 else None
            mno = e[8] if len(e) > 8 else None
            if mno is None or not e[2] or not b or not isinstance(e[5], int):
                continue
            v = self.m[(r[1], mno)]
            v[0] += 1
            v[1] += int(e[5] <= 2) - self.base[(e[2], _bucket(b[2]))]


def current(races: list) -> dict:
    """いまの評価：{場: {号機(str): 値}}（入れ替え後のモーターだけ）。日付順に流して最後の状態を返す"""
    from datetime import date as _D
    old = [r for r in races if not any(len(e) > 8 and e[8] is not None for e in r[11])]
    ma = MotorAdj(base_table(old or races))
    by = defaultdict(list)
    for r in races:
        by[r[0]].append(r)
    for d in sorted(by):
        ma.start_day(by[d], _D(int(d[:4]), int(d[4:6]), int(d[6:])).toordinal())
        for r in by[d]:
            ma.apply(r)
    out = defaultdict(dict)
    for (j, mno), (n, _) in ma.m.items():
        if ma.fresh[j] and n:
            out[j][str(mno)] = round(ma.value(j, mno), 4)
    return dict(out)
