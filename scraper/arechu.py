"""荒れ注意（万舟＝3連単1万円以上が出やすいレース）の印。1号艇がA1・A2のレースだけが対象。

過去約3年・A級1号艇の約4.9万レースで、締切前に分かる数字だけの簡単な式（ロジスティック）を作った。
  ・勝率差 … 1号艇の全国勝率 − 2〜6号艇の全国勝率の平均（小さいほど荒れやすい）
  ・1号艇の展示タイム … 6艇の平均との差（遅いほど荒れやすい）
  ・外の最高勝率、A1か、波高、風速
新しい期間（2025/10〜）で試すと、印のつく上位10%の万舟率は約22%（A級1号艇全体は約16%）。
当てる式ではなく「万舟が出る確率が全体の約1.4倍」の目安。買い目は決められない。
"""
from __future__ import annotations

MEAN = [0.9494, -0.02, 6.5, 0.5417, 0.2459, 0.2735]
SD = [0.8653, 0.0442, 0.7508, 0.4983, 0.2105, 0.1791]
COEF = [-0.2329, 0.0937, -0.0657, 0.0064, 0.0426, 0.0365]
BIAS = -1.6856
MARK = 0.20          # 印をつける確率（過去の上位10%）
BASE = 0.157         # A級1号艇のレース全体の万舟率


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def score(boats: list, ex: dict | None = None, wave_cm=None, wind=None):
    """boats: [{frame, class, nat_win}]、ex: {枠: 展示タイム(秒)}。万舟の確率（0〜1）。対象外は None"""
    import math
    by = {b.get("frame"): b for b in boats or []}
    if set(by) != set(range(1, 7)) or by[1].get("class") not in ("A1", "A2"):
        return None
    nat = {f: _f(by[f].get("nat_win")) for f in by}
    if any(v is None for v in nat.values()):
        return None
    out = [nat[f] for f in range(2, 7)]
    ts = {f: _f((ex or {}).get(f)) for f in range(1, 7)}
    dev = MEAN[1]
    if all(t for t in ts.values()):
        dev = ts[1] - sum(ts.values()) / 6
    x = [nat[1] - sum(out) / 5, dev, max(out), 1.0 if by[1]["class"] == "A1" else 0.0,
         (_f(wave_cm) if _f(wave_cm) is not None else 2.5) / 10, (_f(wind) if _f(wind) is not None else 2.7) / 10]
    z = BIAS + sum(c * (v - m) / s for c, v, m, s in zip(COEF, x, MEAN, SD))
    return 1 / (1 + math.exp(-z))
