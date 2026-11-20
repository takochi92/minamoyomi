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


# 頭の枠別：荒れ注意のレース（過去約3年・約1万）で、2着・3着の組み合わせが多かった順（上位12）。AIの予想がまだ無いときだけ使う。
# 頭が外のとき、1号艇が2着に残る形（差し・まくり差しで頭を譲る）がいちばん多く、次に外・内の艇が続く。
PAIRS = {
    2: [(1, 3), (1, 4), (1, 5), (1, 6), (4, 1), (3, 1), (3, 4), (3, 5), (3, 6), (4, 5), (5, 1), (4, 3)],
    3: [(1, 5), (1, 4), (1, 2), (1, 6), (2, 4), (4, 1), (2, 5), (2, 1), (4, 5), (5, 1), (4, 2), (4, 6)],
    4: [(1, 2), (1, 3), (1, 5), (5, 1), (5, 6), (2, 1), (5, 2), (3, 5), (2, 5), (1, 6), (2, 3), (3, 6)],
    5: [(1, 3), (1, 2), (1, 4), (1, 6), (2, 1), (2, 3), (6, 1), (4, 1), (3, 1), (2, 6), (4, 6), (4, 3)],
    6: [(1, 2), (1, 5), (2, 1), (1, 3), (1, 4), (4, 2), (2, 3), (5, 4), (3, 2), (2, 5), (4, 3), (4, 1)],
}
# 頭の枠別：その枠が頭に来たときの決まり手の割合（％）
KIM = {
    2: [("差し", 59), ("まくり", 25), ("抜き", 10)],
    3: [("まくり", 40), ("まくり差し", 36), ("差し", 12)],
    4: [("まくり", 44), ("差し", 23), ("まくり差し", 23)],
    5: [("まくり差し", 57), ("まくり", 22), ("抜き", 10)],
    6: [("まくり差し", 33), ("まくり", 28), ("差し", 21)],
}


def head_of(boats: list, pred: dict | None = None):
    """荒れた場合の頭：外（1コース以外）の艇で、AIの1着確率がいちばん高い艇（レースページの「穴・攻めの材料」と同じ決め方）。
    AIの予想がまだ無いときだけ、外（2〜6号艇）で全国勝率1位。(枠, 'ai'|'nat_win') を返す"""
    pb = [b for b in (pred or {}).get("boats") or [] if b.get("p_win") is not None and b.get("course", b.get("frame")) != 1]
    if pb:
        return max(pb, key=lambda b: b["p_win"])["frame"], "ai"
    out = sorted(range(2, 7), key=lambda f: -(_f(next((b.get("nat_win") for b in boats if b.get("frame") == f), 0)) or 0))
    return out[0], "nat_win"


N_TICKETS = 12


def tickets_for(race: dict):
    """荒れ注意のレースの穴予想（採用券）：(頭, 決め方, 買い目)。
    頭＝外の艇でAIの1着確率1位、買い目＝その頭の3連単をAIの確率の高い順に12点。
    過去1年（2025/11〜2026/11、荒れ注意の印がつく約9,800レース、学習はそれより前）で、的中約17%・回収約82%。
    以前の「外で全国勝率1位の頭×展開の多い順12点」は同じ期間で的中約12%・回収約73%、AIの上位6点（ふつうの形）は回収約79%。
    AIの予想（3連単の確率）がまだ無いときは、以前の決め方で出す。"""
    from itertools import permutations
    rl = (race.get("racelist") or {}).get("boats", [])
    pred = race.get("prediction") or {}
    head, basis = head_of(rl, pred)
    p3 = pred.get("p3") or []
    if basis == "ai" and len(p3) == 120:
        pm = dict(zip((f"{a}-{b}-{c}" for a, b, c in permutations(range(1, 7), 3)), p3))
        mine = sorted((c for c in pm if c.startswith(f"{head}-")), key=lambda c: -pm[c])[:N_TICKETS]
        return head, basis, mine
    head = sorted(range(2, 7), key=lambda f: -(_f(next((b.get("nat_win") for b in rl if b.get("frame") == f), 0)) or 0))[0]
    return head, "nat_win", [f"{head}-{b}-{c}" for b, c in PAIRS[head]]


def tenkai(head: int, combos: list, ex_rank: dict | None = None, course: int | None = None) -> dict:
    """荒れた場合の展開の説明。combos は (頭, 2着, 3着)。{'kimarite': 文, 'groups': [{'second': 2着の枠, 'story': 文, 'tickets': [...]}]}（2着の枠ごと）"""
    km = "・".join(f"{k}{v}%" for k, v in KIM.get(course or head, []))
    groups, order = {}, []
    for _, b, c in combos:
        if b not in groups:
            groups[b] = []
            order.append(b)
        groups[b].append(f"{head}-{b}-{c}")
    story = {}
    for b in order:
        if b == 1:
            story[b] = "1号艇は頭を譲っても2着に残る（差し・まくり差しで頭が入れ替わる展開）"
        elif b > head:
            story[b] = f"外の{b}号艇が続く（{head}号艇が攻めた外を回って流れ込む）"
        else:
            story[b] = f"内の{b}号艇が残る（{head}号艇が攻めたあと、内で粘る）"
    rank = (ex_rank or {}).get(head)
    ex = f"展示タイムは6艇中{rank}位。" if rank else ""
    c = course or head
    how = f"{head}号艇は、{c}コースから{km}で頭に立つ形が多い。" if km else ""
    return {"kimarite": how + ex,
            "groups": [{"second": b, "story": story[b], "tickets": groups[b]} for b in order]}


def from_race(race: dict):
    """レースのデータ（出走表・展示・水面）から荒れ注意を判定。印がつくなら {p, head, basis, p_win, tickets, tenkai}、つかなければ None。
    tickets は採用券そのもの（締切前に固定した券があればそれ。ページの採用予想と同じ券しか出さない）。"""
    rl = (race.get("racelist") or {}).get("boats", [])
    bi = race.get("before") or {}
    w = bi.get("weather") or {}
    ex = {b.get("frame"): b.get("exhibit_time") for b in bi.get("boats", [])}
    pr = score(rl, ex, w.get("wave_cm"), w.get("wind_speed"))
    if pr is None or pr < MARK:
        return None
    pred = race.get("prediction") or {}
    head, basis, tickets = tickets_for(race)
    saved = race.get("primary_slip") or {}
    if saved.get("source") == "arechu" and saved.get("tickets"):
        fixed = list(saved["tickets"])
        if int(fixed[0].split("-")[0]) != head:
            basis = "legacy"          # 2026-11-19 までの決め方（外で全国勝率1位の頭）で固定した券
        head, tickets = int(fixed[0].split("-")[0]), fixed
    combos = [tuple(map(int, t.split("-"))) for t in tickets]
    ts = {f: _f(t) for f, t in ex.items()}
    rank = {f: 1 + sum(1 for t in ts.values() if t < ts[f]) for f in ts} if len(ts) == 6 and all(ts.values()) else None
    pb = next((b for b in pred.get("boats") or [] if b.get("frame") == head), {})
    return {"p": pr, "head": head, "basis": basis, "p_win": pb.get("p_win"), "tickets": tickets,
            "tenkai": tenkai(head, combos, rank, pb.get("course"))}
