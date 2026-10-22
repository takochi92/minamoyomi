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


# 頭の枠別：荒れ注意のレース（過去約3年・約1万）で、2着・3着の組み合わせが多かった順（上位12）。
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


# 頭の選び方：外（2〜6号艇）のうち、「全国勝率」「枠の勝ちやすさ」「展示タイム（6艇平均との差）」の合計がいちばん高い艇。
# 荒れ注意の過去約1万レース（2025年より前）で学習し、2025年以降で検証した値。
HEAD_SLOT = {2: 0.0, 3: -0.14, 4: -0.35, 5: -0.84, 6: -1.73}   # 勝率が高くても、5・6コースは頭を取りにくい
HEAD_NAT = 0.68
HEAD_EX = -4.97                                                    # 展示タイムが平均より1秒速いと+4.97（実際は0.1秒で0.5）


def ana(boats: list, ex: dict | None = None):
    """荒れ注意のレースの穴予想：頭＝外で「勝率・枠・展示」の合計がいちばん高い艇。2・3着は、その頭の枠で多かった展開の順に12点。
    （頭の枠なりの進入を想定）。過去の荒れ注意レースで試すと（学習2025年前・検証2025年以降）、
    頭の的中 約22%、3連単の的中 約17%、回収 約83%。頭を全国勝率だけで選ぶと、頭の的中 約17%・3連単 約13%・回収 約84%。"""
    nat = {b.get("frame"): (_f(b.get("nat_win")) or 0) for b in boats}
    ts = {f: _f((ex or {}).get(f)) for f in range(1, 7)}
    avg = sum(ts.values()) / 6 if all(ts.values()) else None
    def sc(f):
        dev = (ts[f] - avg) if avg is not None else 0.0
        return HEAD_SLOT[f] + HEAD_NAT * nat.get(f, 0) + HEAD_EX * dev
    head = max(range(2, 7), key=sc)
    return head, [(head, b, c) for b, c in PAIRS[head]]


# スタート展示と行き足から組む「展開」で頭を選ぶ（15日・約1,400レースで学習。頭に来る艇の選び方の係数）
# 検証（日ごとに分けた交差検証）：行き足＋枠 頭の的中 17.5%、全国勝率だけ 16.5%、展示STを重くすると13〜15%に下がる。
# 展示STは参考程度の重みにとどめ、主役は行き足（直線・一周・まわり足・展示タイム）と枠。
# 特徴：内側の艇より展示STが速い幅、すぐ内側の艇との展示STの差、直線・一周・まわり足・展示タイムの6艇内の位置（速いほど+）
TK_SLOT = {2: 0.0, 3: 0.25, 4: 0.03, 5: -0.61, 6: -1.12}
TK_W = {"st_inner": 2.77, "st_adj": -0.93, "str": -0.01, "lap": 0.31, "turn": 0.10, "ext": 0.26}


def _z(vals):
    m = sum(vals) / len(vals)
    sd = (sum((v - m) ** 2 for v in vals) / len(vals)) ** 0.5 or 1.0
    return [(v - m) / sd for v in vals]


def head_by_tenkai(race: dict):
    """スタート展示（展示ST・展示の進入）と、一周・まわり足・直線・展示タイムから頭を選ぶ。
    データがそろわなければ None。{'head', 'info': {...頭の艇の根拠}}"""
    bi = race.get("before") or {}
    se = bi.get("start_exhibition") or []
    ori = race.get("oriten") or {}
    if len(se) != 6 or not ori.get("rows") or len(ori["rows"]) != 6:
        return None
    try:
        items = ori["items"]
        idx = {k: items.index(k) for k in ("一周", "まわり足", "直線")}
        o = {int(f): v for f, v in ori["rows"].items()}
        st = {int(x["frame"]): float(x["st"]) for x in se}
        crs = {int(x["frame"]): int(x["course"]) for x in se}
        ext = {int(b["frame"]): float(b["exhibit_time"]) for b in bi.get("boats", [])}
        if len(st) != 6 or len(ext) != 6 or len(o) != 6:
            return None
        fs = list(range(1, 7))
        zs = {k: dict(zip(fs, _z([float(o[f][idx[k]]) for f in fs]))) for k in idx}
        zx = dict(zip(fs, _z([ext[f] for f in fs])))
    except (KeyError, ValueError, TypeError, IndexError):
        return None
    by_c = {c: f for f, c in crs.items()}
    best = None
    for f in range(1, 7):
        c = crs[f]
        if c < 2:
            continue
        inner = [st[by_c[i]] for i in range(1, c) if i in by_c]
        adv = min(inner) - st[f] if inner else 0.0
        adj = st[by_c[c - 1]] - st[f] if (c - 1) in by_c else 0.0
        sc = (TK_SLOT.get(c, -1.5) + TK_W["st_inner"] * adv + TK_W["st_adj"] * adj + TK_W["str"] * -zs["直線"][f]
              + TK_W["lap"] * -zs["一周"][f] + TK_W["turn"] * -zs["まわり足"][f] + TK_W["ext"] * -zx[f])
        if best is None or sc > best[0]:
            def rk(vals, f=f):
                return 1 + sum(1 for g in fs if vals[g] < vals[f])
            best = (sc, f, dict(course=c, st=st[f], adv=adv, str=rk({g: float(o[g][idx["直線"]]) for g in fs}),
                                lap=rk({g: float(o[g][idx["一周"]]) for g in fs}), turn=rk({g: float(o[g][idx["まわり足"]]) for g in fs}), ext=rk(ext)))
    return {"head": best[1], "info": best[2]} if best else None


def tenkai(head: int, combos: list, ex_rank: dict | None = None) -> dict:
    """穴予想の展開の説明。{'kimarite': 文, 'groups': [{'second': 2着の枠, 'story': 文, 'tickets': [...]}]}（2着の枠ごと）"""
    km = "・".join(f"{k}{v}%" for k, v in KIM[head])
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
    return {"kimarite": f"{head}号艇は、{head}コースから{km}で頭に立つ形が多い。{ex}",
            "groups": [{"second": b, "story": story[b], "tickets": groups[b]} for b in order]}


def from_race(race: dict):
    """レースのデータ（出走表・展示・水面）から荒れ注意を判定。印がつくなら {p, head, tickets}、つかなければ None"""
    rl = (race.get("racelist") or {}).get("boats", [])
    bi = race.get("before") or {}
    w = bi.get("weather") or {}
    ex = {b.get("frame"): b.get("exhibit_time") for b in bi.get("boats", [])}
    pr = score(rl, ex, w.get("wave_cm"), w.get("wind_speed"))
    if pr is None or pr < MARK:
        return None
    tk0 = head_by_tenkai(race)
    if tk0:
        head = tk0["head"]
        combos = [(head, b, c) for b, c in PAIRS[head]]
    else:
        head, combos = ana(rl, ex)
    ts = {f: _f(t) for f, t in ex.items()}
    rank = {f: 1 + sum(1 for t in ts.values() if t < ts[f]) for f in ts} if len(ts) == 6 and all(ts.values()) else None
    if tk0:
        i = tk0["info"]
        fast = f"内側の艇より{i['adv']:.2f}秒速くスリットを抜ける形" if i["adv"] > 0.005 else "内側の艇とスタートはほぼ同じ"
        why = (f"頭に選んだ理由（スタート展示と行き足から組んだ展開）：{head}号艇は{i['course']}コースで、展示STは{i['st']:.2f}。{fast}。"
               f"行き足は、直線{i['str']}位・一周{i['lap']}位・まわり足{i['turn']}位・展示タイム{i['ext']}位（6艇中）。")
    else:
        nat = {b.get("frame"): _f(b.get("nat_win")) or 0 for b in rl}
        nrank = 1 + sum(1 for f in range(2, 7) if nat[f] > nat[head])
        why = f"頭に選んだ理由（スタート展示がまだ出ていないため仮）：全国勝率{nat[head]:.2f}（外の5艇で{nrank}位）"
        why += f"、展示タイム{rank[head]}位" if rank else ""
        why += "。スタート展示が出たら、スタートと行き足から選び直します。"
    return {"p": pr, "head": head, "tickets": [f"{a}-{b}-{c}" for a, b, c in combos], "why": why, "tenkai": tenkai(head, combos, rank)}
