"""予想本体。重みはすべて過去データで学習した model.json を使う（手で決めた係数は使わない）。

1着・2着・3着それぞれの条件付きロジットで各艇の強さを出し、3連単120通りの確率を計算して買い目を選ぶ。
特徴量の計算は学習時と同じ scraper/model.features()。学習と検証の中身は scraper/train_model.py。
"""
from __future__ import annotations

import itertools
import json
import math
from pathlib import Path
from typing import Optional

import numpy as np

from . import coursestats, fstart
from .model import FEATS, FEATURE_LABEL, features, load_model, load_stats, stage_scores
from .odds import SPECIALIST_RULE

VENUES = json.loads((Path(__file__).parent / "venues.json").read_text(encoding="utf-8"))["venues"]


def wind_info(wind_dir: Optional[int], speed: Optional[float]) -> dict:
    """公式の風向アイコン(is-wind1〜16)を 追い風/向かい風/横風 に変換（表示用）。

    アイコンはスタンドを下にした水面図上の矢印で、1=↑、5=→、9=↓、13=← と時計回り。
    1マークは右側なので、右向き＝追い風、左向き＝向かい風。
    """
    s = speed or 0
    if not wind_dir or wind_dir > 16 or s == 0:
        return {"type": "無風", "speed": s, "tail": 0.0, "arrow_deg": None, "level": "無風"}
    deg = (wind_dir - 1) * 22.5
    tail = math.sin(math.radians(deg))
    typ = "追い風" if tail >= 0.5 else ("向かい風" if tail <= -0.5 else "横風")
    level = "弱" if s <= 2 else ("中" if s <= 4 else "強")
    return {"type": typ, "speed": s, "tail": round(tail, 3), "arrow_deg": deg, "level": level}


# 「イン不安」：インのコース成績が下位25%、かつ外にインの負け方とかみ合う攻め手（上位25%）がいるレース。
# 過去1年（約9千レース・締切前の情報のみ）でインの1着は29%（全体55%）、オッズの見立ては30%。
# インを買い目から切ると的中・回収率とも下がったので、買い目は確率どおりのまま、印と根拠だけ出す。
IN_WORRY = {"in_rc_max": -0.15, "mu_min": 0.82, "mu_strong": 1.21, "hist": {1: 0.289, 2: 0.283}, "races": {1: 893, 2: 325}, "all": 0.551}


# 3・4コースがスタートの早い選手のとき、インのタイプ別（過去2年）
RESIST_STATS = {
    (3, "飛び付き"): {"n": 1509, "in_win": 0.37, "in_out": 0.34, "pay": 3230, "wins": {2: 0.19, 3: 0.25, 4: 0.11, 5: 0.06}},
    (3, "残す"): {"n": 7150, "in_win": 0.62, "in_out": 0.13, "pay": 2280, "wins": {2: 0.10, 3: 0.15, 4: 0.08, 5: 0.04}},
    (4, "飛び付き"): {"n": 1428, "in_win": 0.37, "in_out": 0.35, "pay": 3310, "wins": {2: 0.18, 3: 0.16, 4: 0.20, 5: 0.07}},
    (4, "残す"): {"n": 7305, "in_win": 0.59, "in_out": 0.14, "pay": 2450, "wins": {2: 0.10, 3: 0.10, 4: 0.14, 5: 0.05}},
}

# 展示タイムが内の艇より0.10秒以上速いとき（過去1年・約9千レース）
EXGAP_STATS = {3: {"n": 597, "win": 0.209, "base_win": 0.128, "makuri": 0.095, "base_makuri": 0.050},
               4: {"n": 699, "win": 0.210, "base_win": 0.103, "makuri": 0.122, "base_makuri": 0.046},
               5: {"n": 675, "win": 0.108, "base_win": 0.061, "makuri": 0.044, "base_makuri": 0.012}}
# 高回収狙い（検証中）：5コースの展示タイムが4コースより0.15秒以上速い → 5の頭
# 過去1年 177レースで5の1着18.1%（オッズの見込み12.8%）。偶数日・奇数日とも頭の回収率100%以上だったが件数が少ない
# 穴狙い（ツケマイ型）：3・4コースのまくり屋で、まくって勝つとインが4着以下に沈む選手。
# 過去約9,000レースの検証（イン抜き12点）：ツケマイ7割以上＋スタート3番手以内 回収72%、
# ツケマイ5割以上＋スタート3番手以内＋展示タイム2位以内＋インの逃げ率55%未満 回収80%（確定オッズ・楽観寄り）
# 攻めた艇がまくりで勝ったときの2・3着（コース）で多い並び。インを除いた上位6つ（過去3年）
# 例：4まくり → 5がマークして2着（5-6、5-2…）、3まくり → 4が連れて2着（4-5、4-2…）、5まくり → 叩かれた4は残りにくく6・2
# 検証（穴狙いの条件に当たった1,102レース、並びは反対側の日で学習）：イン抜き12点 回収69% → この6点 82%
# 4コース頭は「4が3を叩く」筋の4-56-1256に変更（同じ481レースで回収107%。ただし偶数日54%・奇数日164%と波が大きい）
FOLLOW = {3: [(4, 5), (4, 2), (2, 4), (5, 4), (4, 6), (5, 2)],
          4: [(5, 6), (5, 1), (5, 2), (6, 5), (6, 1), (6, 2)],   # 4が3を叩く筋：4-56-1256（3は潰れる想定）
          5: [(6, 2), (2, 6), (2, 3), (2, 4), (6, 3), (6, 4)]}
# 2・3着の選び方：AIの確率（勝率・展示・コース別成績・モーターなど選手ごとの材料）×「まくりで勝ったときの並びの出やすさ」
# 攻めた艇が1着のときの2・3着コースの組（過去3年）。mk＝まくりで勝ったとき、all＝勝ち方を問わず
MK_PAIRS = {"mk": {"3": {"65": 165, "42": 597, "14": 564, "25": 433, "41": 605, "46": 457, "15": 504, "45": 747, "26": 286, "24": 495, "56": 321, "61": 196, "16": 328, "64": 249, "52": 434, "54": 480, "51": 455, "21": 463, "12": 546, "62": 184}, "4": {"52": 651, "65": 375, "16": 407, "56": 769, "12": 488, "51": 924, "62": 287, "15": 670, "63": 170, "36": 185, "31": 240, "25": 438, "53": 467, "21": 448, "32": 171, "13": 320, "23": 242, "26": 307, "35": 215, "61": 377}, "5": {"23": 94, "61": 179, "14": 130, "31": 98, "16": 169, "63": 82, "12": 214, "64": 79, "34": 50, "26": 118, "21": 198, "32": 79, "36": 55, "24": 89, "41": 84, "62": 161, "13": 131, "42": 48, "46": 38, "43": 38}}, "all": {"3": {"12": 2257, "65": 261, "14": 2682, "42": 1052, "16": 1288, "15": 2272, "46": 724, "25": 1133, "41": 1260, "24": 1266, "45": 1171, "51": 905, "26": 665, "56": 521, "21": 1228, "61": 380, "64": 347, "52": 723, "54": 752, "62": 293}, "4": {"13": 1223, "56": 1035, "15": 1722, "52": 953, "21": 1157, "35": 835, "65": 531, "36": 589, "25": 878, "16": 1057, "51": 1360, "12": 1499, "26": 612, "62": 428, "61": 546, "32": 561, "31": 795, "53": 773, "63": 294, "23": 740}, "5": {"34": 352, "43": 351, "12": 1059, "13": 960, "31": 490, "41": 652, "32": 387, "23": 430, "16": 805, "61": 374, "21": 701, "14": 883, "42": 435, "63": 204, "36": 272, "24": 389, "26": 362, "64": 227, "46": 484, "62": 298}}}
# 検証（穴狙い1,102レース）：固定の筋6点 的中77 回収91%（日によって72〜115%）→ AI×展開補正の上位6点 的中119 回収86%（80〜91%で安定）
# インの展示タイムが「いつもの順位」より3つ以上悪い（過去3年 1,614レース）：インの1着 50.0%（全体 55.7%）
# オッズはそれでもインを52%前後と見ていて、実際（46%）より高く評価しがち（約9,000レースのうち該当104レース、偶数日・奇数日とも同じ傾向）
EX_DROP = {"gap": 3, "n": 1614, "in_win": 0.500, "all": 0.557, "mkt": 0.52, "act": 0.46}
# 2・3コースの選手がいるとき、すぐ外が1着になる全体の割合（過去3年）
# 選手ごとの「叩かれやすさ」：3コースのとき4に勝たれる率が16%以上の選手 → 4の1着 14%（全体10%）。ただしオッズもほぼ同じだけ見ている
WALL_BASE = {3: 0.13, 4: 0.106}
# 厳選本命：イン逃げが堅く、逃げたときの2着の軸もはっきりしているレースだけ、1-軸-3着上位3点
# 検証（約9,000レース・61日）：AIのイン1着60%以上・逃げたときの2着がその艇40%以上・3点の合成オッズ2.5倍以上
#  → 749レース（1日約12R）的中27% 回収82%（偶数日83%・奇数日82%）。人気や級別ではなくAIの確率で決めるので、人気薄の軸でも入る
#  合成2.5倍未満（安い目ばかり）の596レースも3点で的中40%・回収85%だったので、オッズに関係なく3点で出す
# （全レースの本線・押さえ10〜15点と回収率は同程度で、点数は3点）
# 予想の作り方を変えたら上げる。締切前のレースは、版が違えば次の更新で予想を作り直す
PRED_VERSION = 29
HONMEI = {"in": 0.60, "axis": 0.40, "k": 3}
# イン逃げのとき2・3着に残る率（過去3年）：4コース42.6% / 5コース31.0% / 6コース18.3%
# 選手ごとに差が大きい（6コースでも35〜45%の選手は、逃げのとき1-その艇が絡む率18.8%＝普通の6コースの2倍以上）。ただしオッズもほぼ同じだけ見ている
NOKO_BASE = {2: 0.571, 3: 0.536, 4: 0.426, 5: 0.310, 6: 0.183}
# B級の逃げ残し巧者（3・4・6コースで、逃げのとき2・3着に残る率が平均より10ポイント以上高い・20走以上）はオッズに軽視されがち
#  例：4コース 実際29.7%・オッズ22.6% / 6コース 実際15.7%・オッズ11.7%
#  検証（738レース・1日約12R）：1-その艇が絡む目のAI上位4点 的中19% 回収91%（偶数日84%・奇数日99%）。A1は逆にオッズどおり
TSUKE = {"n": 3, "rate": 0.5, "rate_hi": 0.7, "st": 3.0, "ex_rank": 2, "in_esc": 0.55}
ANA_RULE = {"gap": 0.15, "n": 177, "win": 0.181, "mkt": 0.128}

# チルト1.0以上（伸び型）の過去1年の実績（2025/9〜2026/9・展示の進入・確定オッズのある約9千レース）
TILT_STATS = {4: {"n": 92, "win": 0.239, "base_win": 0.101, "mkt": 0.183, "top3": 0.598, "base_top3": 0.469},
              5: {"n": 130, "win": 0.146, "base_win": 0.060, "mkt": 0.143, "top3": 0.469, "base_top3": 0.364},
              6: {"n": 311, "win": 0.071, "base_win": 0.023, "mkt": 0.100, "top3": 0.299, "base_top3": 0.232}}

# 展開メモの条件と、過去2年（約11万レース）の実績。壁＝すぐ内のコース
TENKAI = {"wall_slow": 4.0, "att_fast": 3.0,
          "follow": {"まくり": {"n": 1969, "win4": 0.230, "w45": 0.125, "base_w45": 0.046, "top6": 0.265, "base_top6": 0.220},
                     "まくり差し": {"n": 477, "win4": 0.161, "top6": 0.193, "base_top6": 0.220}},
          "stats": {3: {"n": 4312, "win": 0.211, "base_win": 0.128, "makuri": 0.088, "base_makuri": 0.052},
                    4: {"n": 4442, "win": 0.199, "base_win": 0.105, "makuri": 0.120, "base_makuri": 0.049}}}


KEEP_BASE = 0.459   # 3・4コースのまくり勝ちで、インが2・3着に残った割合（過去3年・16,420回）


def _ana_bets(head, c, course_of, combos, k=6, tk=None, drop=None):
    """頭固定で、2・3着をAIの確率×まくり展開での並びの出やすさで並べた上位k点。
    tk=(まくり勝ち数, そのうちインが4着以下) があれば、その選手の「インを残すか沈めるか」のくせで補正
    （握って回ってインを残す型なら 3-1-x、ツケマイ型なら 3-45-x を上げる。検証：攻め頭6点の回収 81%→85%）"""
    mk, al = MK_PAIRS["mk"].get(str(c), {}), MK_PAIRS["all"].get(str(c), {})
    nm, na = sum(mk.values()) or 1, sum(al.values()) or 1
    sc = []
    for cb, p in combos:
        h, a, b = cb.split("-")
        if int(h) != head:
            continue
        if drop and drop in (int(a), int(b)):
            continue   # スタートの遅い壁は叩かれて残らない想定（2・3着から外す）
        key = f"{course_of[int(a)]}{course_of[int(b)]}"
        # まくりで勝ったときの2・3着の並びの出やすさ（実数）を主に、AIの確率は平方根で弱めて掛ける。
        # AIの2・3着は「頭がまくった」ことを知らないので、内の2・3コースを残しすぎる（4-2-3 のような買い目）。
        # 検証（2025年〜、攻め艇が壁より0.08以上早くスタートして勝ったレース）：3点の的中
        #   4コース頭 32.9%→35.1%、3コース頭 33.7%→36.8%（AIの代わりに全国勝率で並べた簡易版での比較）
        lift = ((mk.get(key, 0) + 2) / (nm + 40)) / (p ** 0.5 if p > 0 else 1)
        if tk and tk[0] >= 3:
            keep = (tk[0] - tk[1] + 5 * KEEP_BASE) / (tk[0] + 5)
            lift *= (keep / KEEP_BASE) if "1" in key else ((1 - keep) / (1 - KEEP_BASE))
        sc.append((p * lift, cb))
    sc.sort(reverse=True)
    return [cb for _, cb in sc[:k]]


def in_worry(X, course_of, frames, cs_comments):
    ci = [i for i, f in enumerate(frames) if course_of[f] == 1]
    if not ci:
        return None
    i = ci[0]
    rc = float(X[i, FEATS.index("rc_win")])
    mu = X[:, FEATS.index("mu")]
    outs = [(float(mu[j]), frames[j]) for j in range(len(frames)) if j != i]
    top_mu, top_f = max(outs)
    if rc > IN_WORRY["in_rc_max"] or top_mu < IN_WORRY["mu_min"]:
        return None
    lv = 2 if top_mu >= IN_WORRY["mu_strong"] else 1
    reasons = [c for c in cs_comments if "率" in c and ("警戒" in c or "逃げ率" in c)]
    return {"level": lv, "attacker": top_f, "reasons": reasons, "hist_in_win": IN_WORRY["hist"][lv],
            "hist_races": IN_WORRY["races"][lv], "hist_all": IN_WORRY["all"]}


def predict(jcd: str, racelist: dict, before: Optional[dict] = None) -> dict:
    S, model = load_stats(), load_model()
    if S is None or model is None:
        raise RuntimeError("course_stats.json.gz / model.json がありません（python -m scraper.history と scraper.train_model を実行）")
    venue = VENUES[jcd]
    boats = sorted(racelist["boats"], key=lambda b: b["frame"])
    frames = [b["frame"] for b in boats]
    before = before or {}
    bb = {b["frame"]: b for b in before.get("boats", [])}
    st_ex = {s["frame"]: s for s in before.get("start_exhibition", [])}
    weather = before.get("weather") or {}
    wind = wind_info(weather.get("wind_dir"), weather.get("wind_speed"))
    wave = weather.get("wave_cm")

    if len(st_ex) == 6 and not racelist.get("fixed_entry"):
        course_of = {f: st_ex[f]["course"] for f in frames}
    else:
        course_of = {f: f for f in frames}
    entry_changed = any(course_of[f] != f for f in frames)

    ex = {f: bb.get(f, {}).get("exhibit_time") for f in frames}
    has_ex = all(ex.values())
    try:
        from . import motor as _motor
        madj = {} if sum(1 for b in boats if not b.get("motor_2")) >= 5 else _motor.load().get(jcd, {})   # 入れ替え直後は使わない
    except Exception:
        madj = {}
    fb = [{"frame": b["frame"], "toban": b.get("toban", ""), "course": course_of[b["frame"]],
           "ex": round(ex[b["frame"]] * 100) if has_ex else None, "cls": b.get("class", ""),
           "nat": b.get("nat_win"), "loc": b.get("loc_win"), "motor": b.get("motor_2"), "boat": b.get("boat_2"),
           "f_recent": b.get("f", 0), "motor_adj": (madj.get(str(b.get("motor_no"))) or {}).get("adj")} for b in boats]
    try:
        from .windmap import to_compass
        wdir = to_compass(jcd, weather.get("wind_dir"))
    except Exception:
        wdir = None
    X = features(S, jcd, wave, weather.get("wind_speed"), fb, wind_dir=wdir)
    sc = stage_scores(X, model)

    def soft(v):
        e = np.exp(v - v.max())
        return e / e.sum()

    p1 = soft(sc["1"])
    e2, e3 = np.exp(sc["2"] - sc["2"].max()), np.exp(sc["3"] - sc["3"].max())
    combos = []
    for a, b, c in itertools.permutations(range(6), 3):
        pb = e2[b] / (e2.sum() - e2[a])
        pc = e3[c] / (e3.sum() - e3[a] - e3[b])
        combos.append((f"{frames[a]}-{frames[b]}-{frames[c]}", float(p1[a] * pb * pc)))
    tot = sum(p for _, p in combos)
    p3 = [round(p / tot, 6) for _, p in combos]   # 1-2-3, 1-2-4 … の順（odds.COMBOS と同じ）
    combos = sorted(((k, p / tot) for k, p in combos), key=lambda x: -x[1])

    top2 = {f: 0.0 for f in frames}
    top3 = {f: 0.0 for f in frames}
    for k, p in combos:
        a, b, c = map(int, k.split("-"))
        top2[a] += p; top2[b] += p
        top3[a] += p; top3[b] += p; top3[c] += p

    ex_rank = {f: r for r, f in enumerate(sorted(frames, key=lambda f: ex[f]), 1)} if has_ex else {}
    rows = []
    for i, b in enumerate(boats):
        f = b["frame"]
        parts = {}
        for n, v in zip(sc["contrib_names"], sc["contrib"][i]):
            lab = FEATURE_LABEL.get(n, n)
            parts[lab] = parts.get(lab, 0.0) + float(v)
        rows.append({
            "frame": f, "course": course_of[f], "name": b["name"], "class": b.get("class", ""),
            "p_win": round(float(p1[i]), 4), "p_top2": round(top2[f], 4), "p_top3": round(top3[f], 4),
            "parts": {k: round(v, 3) for k, v in parts.items()},
            "exhibit_time": ex[f], "exhibit_rank": ex_rank.get(f),
            "ex_st": st_ex.get(f, {}).get("st"), "ex_st_flag": st_ex.get(f, {}).get("flag", ""),
        })

    order = sorted(rows, key=lambda r: -(r["p_win"] * 2 + r["p_top3"]))
    marks = {str(r["frame"]): m for m, r in zip(["◎", "○", "▲", "△", "×"], order)}

    main, cum = [], 0.0
    for k, p in combos:
        if len(main) >= 6 or (len(main) >= 3 and cum >= 0.30):
            break
        main.append({"combo": k, "p": round(p, 4)})
        cum += p
    used = {m["combo"] for m in main}
    sub = [{"combo": k, "p": round(p, 4)} for k, p in combos if k not in used][:4]
    used |= {s["combo"] for s in sub}
    fav2 = {r["frame"] for r in sorted(rows, key=lambda r: -r["p_win"])[:2]}
    ana_list = [{"combo": k, "p": round(p, 4)} for k, p in combos if int(k[0]) not in fav2 and k not in used and p >= 0.008][:2]
    ex2 = {}
    for k, p in combos:
        ex2[k[:3]] = ex2.get(k[:3], 0) + p
    exacta = [{"combo": k, "p": round(p, 4)} for k, p in sorted(ex2.items(), key=lambda x: -x[1])[:3]]

    pmax = float(p1.max())
    conf = ("鉄板", 4) if pmax >= 0.65 else ("本命", 3) if pmax >= 0.5 else ("やや混戦", 2) if pmax >= 0.38 else ("混戦・荒れ注意", 1)

    spec = []
    rcw = X[:, FEATS.index("rc_win")]
    for i, b in enumerate(boats):
        c = course_of[b["frame"]]
        if b.get("class") in SPECIALIST_RULE["classes"] and c in SPECIALIST_RULE["courses"] and rcw[i] >= SPECIALIST_RULE["rc_win_min"]:
            me = S.rc[b.get("toban", "")][c]
            spec.append({"frame": b["frame"], "course": c, "name": b["name"], "class": b.get("class"),
                         "starts": int(me[0]), "wins": int(me[1]), "ratio": round(float(math.exp(rcw[i])), 2)})

    cs_view, cs_comments = coursestats.view(S, jcd, [{"frame": b["frame"], "course": course_of[b["frame"]],
                                                       "toban": b.get("toban", ""), "name": b["name"]} for b in boats])
    comments = cs_comments + _comments(venue, rows, wind, wave, entry_changed, course_of, has_ex, boats) + _local_notes(S, jcd, boats, venue, entry_changed)

    # F持ち選手の「F後のスタート」（同じコースでの平均STとスタート順）
    fs_all = fstart.load()
    fs = []
    for b in boats:
        if not b.get("f"):
            continue
        j = fstart.judge(fs_all.get(b.get("toban", "")), course_of[b["frame"]])
        if j:
            j.update({"frame": b["frame"], "name": b["name"], "f_count": b.get("f")})
            fs.append(j)
    # 展開メモ：内の壁のスタートが遅く、外がスタートで行ける → まくり展開
    rec = fstart.load_recent()
    try:
        walld = fstart.load_wall()
    except Exception:
        walld = {}
    byc = {course_of[b["frame"]]: b for b in boats}
    fsd = {j["frame"]: j for j in fs}
    tenkai = []
    for att in (3, 4):
        wb, ab = byc.get(att - 1), byc.get(att)
        if not wb or not ab:
            continue
        ws, as_ = rec.get(wb.get("toban", "")), rec.get(ab.get("toban", ""))
        if not ws or not as_:
            continue
        wf = fsd.get(wb["frame"])
        wall_slow = ws[1] >= TENKAI["wall_slow"] or bool(wf and wf.get("slow"))
        if wall_slow and as_[1] <= TENKAI["att_fast"]:
            st = TENKAI["stats"][att]
            wv = walld.get(f"{wb.get('toban', '')}-{att - 1}")
            tenkai.append({"wall_beaten": list(wv) if wv else None,
                           "att": ab["frame"], "att_course": att, "att_name": ab["name"], "att_rank": as_[1],
                           "wall": wb["frame"], "wall_course": att - 1, "wall_name": wb["name"], "wall_rank": ws[1],
                           "wall_f": bool(wf and wf.get("slow")), **st})
            if att == 4 and len(as_) >= 4:
                mk, ms = as_[2], as_[3]
                tenkai[-1]["style"] = "まくり" if mk / (mk + ms) >= 0.65 else ("まくり差し" if ms / (mk + ms) >= 0.65 else "両方")
                tenkai[-1]["style_n"] = [mk, ms]
    # チルトを跳ねた伸び型（4〜6コースでチルト1.0以上）
    for b in boats:
        t = bb.get(b["frame"], {}).get("tilt")
        c = course_of[b["frame"]]
        if t is not None and t >= 1.0 and c >= 4:
            tenkai.append({"type": "tilt", "frame": b["frame"], "name": b["name"], "course": c, "tilt": t, **TILT_STATS[c]})
    # インの「攻められ方」：負けたとき4着以下が多い＝飛び付き型、2〜3着に残す＝残す型
    inb = byc.get(1)
    ir = fstart.load_inres().get(inb.get("toban", "")) if inb else None
    if ir:
        out = ir[1] / ir[0]
        ityp = "飛び付き" if out >= 0.55 else None     # 残す型は多数派なのでメモには出さない
        att = [byc[c] for c in (3, 4) if byc.get(c) and rec.get(byc[c].get("toban", "")) and rec[byc[c]["toban"]][1] <= 2.8]
        if ityp and att:
            a = att[0]
            ac = course_of[a["frame"]]
            tenkai.append({"type": "resist", "in": inb["frame"], "in_name": inb["name"], "style": ityp, "beaten": ir[0], "out": ir[1],
                           "att": a["frame"], "att_name": a["name"], "att_course": ac, **RESIST_STATS[(ac, ityp)]})

    # モーターの機歴（場・モーター番号ごと）：展示タイムが場の中で上位、または前節のオリジナル展示が抜けている
    try:
        from . import motor as _motor
        mstat = _motor.load().get(jcd, {})
    except Exception:
        mstat = {}
    # 入れ替え直後（番組表のモーター2連率がほぼ全艇0.00）は、同じ番号でも別のモーターなので出さない
    if sum(1 for b in boats if not b.get("motor_2")) >= 5:
        mstat = {}
    for b in boats:
        ms = mstat.get(str(b.get("motor_no")))
        if not ms or ms["n"] < 10 or ms.get("ex") is None or "rank" not in ms:
            continue
        L = ms.get("last") or {}
        ori = L.get("ori") or {}
        good = []
        if ms["rank"] <= max(3, round(ms["of"] * 0.15)):
            good.append(f"展示タイムは場の{ms['of']}基中{ms['rank']}位（6艇平均より{-ms['ex']:.2f}秒速い）")
        if L.get("ex") is not None and L["ex"] <= -0.05 and L.get("n", 0) >= 4:
            good.append(f"前節（{int(L['from'][4:6])}/{int(L['from'][6:])}〜）は展示タイムが平均より{-L['ex']:.2f}秒速い")
        for it, lab in (("直線", "伸び"), ("一周", "回り"), ("まわり足", "出足")):
            v = ori.get(it)
            if v is not None and v <= -0.08:
                good.append(f"前節の{it}タイムが平均より{-v:.2f}秒速い（{lab}型）")
        if good:
            tenkai.append({"type": "motor", "frame": b["frame"], "name": b["name"], "motor_no": b.get("motor_no"),
                           "reasons": good, "since": ms.get("since"), "win": ms["win"], "n": ms["n"], "makuri": ms["makuri"],
                           "last_makuri": L.get("makuri", 0), "last_n": L.get("n", 0)})

    # 展示タイムが内の艇より0.1秒以上速い → まくりが決まりやすい
    ana = None
    if has_ex:
        for c in (3, 4, 5):
            a, w = byc.get(c), byc.get(c - 1)
            if not a or not w:
                continue
            gap = round(ex[w["frame"]] - ex[a["frame"]], 2)
            if gap >= 0.10:
                tenkai.append({"type": "exgap", "frame": a["frame"], "name": a["name"], "course": c, "gap": gap,
                               "inner": w["frame"], "inner_name": w["name"], **EXGAP_STATS[c]})
            if c == 5 and gap >= ANA_RULE["gap"]:
                others = sorted((r for r in rows if r["frame"] != a["frame"]), key=lambda r: -r["p_top3"])[:3]
                combos_ = [f"{a['frame']}-{x['frame']}-{y['frame']}" for x in others for y in others if x is not y]
                ana = {**ANA_RULE, "frame": a["frame"], "name": a["name"], "course": c, "gap": gap, "bets": combos_}
    # 厳選本命
    honmei_pick = None
    inb_h = byc.get(1)
    if inb_h and has_ex:
        I = inb_h["frame"]
        hin = [(cb, p) for cb, p in combos if int(cb.split("-")[0]) == I]
        pin = sum(p for _, p in hin) / (sum(p for _, p in combos) or 1)
        sec = {}
        for cb, p in hin:
            sec[int(cb.split("-")[1])] = sec.get(int(cb.split("-")[1]), 0) + p
        if sec and pin >= HONMEI["in"]:
            AX, px = max(sec.items(), key=lambda x: x[1])
            share = px / (sum(sec.values()) or 1)
            if share >= HONMEI["axis"]:
                th = sorted(((int(cb.split("-")[2]), p) for cb, p in hin if int(cb.split("-")[1]) == AX), key=lambda x: -x[1])[:HONMEI["k"]]
                xb = next((b for b in boats if b["frame"] == AX), {})
                cut = [f for f in frames if f not in (I, AX) and f not in [t for t, _ in th]]
                honmei_pick = {"in": I, "in_name": inb_h["name"], "axis": AX, "axis_name": xb.get("name", ""), "axis_course": course_of[AX],
                               "p_in": round(pin, 3), "p_axis": round(share, 3), "thirds": [t for t, _ in th], "cut": cut,
                               "bets": [f"{I}-{AX}-{t}" for t, _ in th]}
    # 穴狙い（厳選）：たこさんの穴目の条件が「すべて」そろった3・4コースだけ
    #  ①まくり型（まくり勝ちでインを沈めた割合5割以上、または4コースのまくり勝ち2回以上）
    #  ②最近のスタートが3番手以内 ③展示タイムが壁（すぐ内）より0.05秒以上速い
    #  ④壁のスタートが遅い（平均4番手以降）か、壁が「叩かれやすい」選手
    #  ⑤締切前のオッズがインを信じすぎていない（インの1着の見込み45%未満）→ run.py で判定
    # 検証（約9,000レース・61日）：①②だけ 回収65% → ①②③ 84% → ①〜④ 92% → ①〜⑤ 97%（1日約2レース・的中率20%）
    tsuke_pick = None
    try:
        tkd = fstart.load_tsuke()
    except Exception:
        tkd = {}
    inb_ = byc.get(1)
    for c in (4, 3):
        a, w = byc.get(c), byc.get(c - 1)
        if not a or not w or not inb_ or not has_ex:
            continue
        tk = tkd.get(a.get("toban", ""))
        stv = rec.get(a.get("toban", ""))
        wst = rec.get(w.get("toban", ""))
        if not stv:
            continue
        rate = tk[1] / tk[0] if tk and tk[0] >= 3 else 0
        mk4 = stv[2] if c == 4 and len(stv) >= 4 else 0
        gap = round(ex[w["frame"]] - ex[a["frame"]], 2) if ex.get(w["frame"]) and ex.get(a["frame"]) else None
        wv = walld.get(f"{w.get('toban', '')}-{c - 1}")
        wrate = wv[1] / wv[0] if wv and wv[0] >= 15 else None
        ok1 = rate >= 0.5 or mk4 >= 2
        ok2 = stv[1] <= 3.0
        ok3 = gap is not None and gap >= 0.05
        ok4 = bool(wst and wst[1] >= 4.0) or (wrate is not None and wrate >= (0.14 if c == 4 else 0.17))
        if not (ok1 and ok2 and ok3 and ok4):
            continue
        why = [("まくり型：" + (f"まくり勝ち{tk[0]}回のうち{tk[1]}回でインを4着以下に沈めた" if rate >= 0.5 else f"{c}コースでのまくり勝ち{mk4}回")),
               f"スタートが早い：最近の平均{stv[1]:.1f}番手",
               f"展示で壁より速い：{c - 1}コースの{w['name']}より{gap:.2f}秒",
               "壁が弱い：" + "・".join(x for x in (
                   f"{w['name']}のスタートは平均{wst[1]:.1f}番手" if wst and wst[1] >= 4.0 else "",
                   f"{c - 1}コースのとき{c}コースに勝たれる率{wrate * 100:.0f}%（{wv[0]}走）" if wrate is not None and wrate >= (0.14 if c == 4 else 0.17) else "") if x)]
        tsuke_pick = {"kind": "tsuke", "frame": a["frame"], "name": a["name"], "course": c, "rate": round(rate, 2),
                      "in": inb_["frame"], "in_name": inb_["name"], "why": why, "bets": _ana_bets(a["frame"], c, course_of, combos, tk=tk)}
        break
    ana = None
    # 穴目：展開メモで「外から一撃」の材料がある艇がいれば、その艇の頭を2点だけ押さえる
    ana_reason = ""
    ana_bets = ana_list
    hot = [t for t in tenkai if t.get("type") in ("tilt", "exgap")] + [t for t in tenkai if not t.get("type") and t.get("att")]
    if hot:
        t0 = hot[0]
        hf = t0.get("frame") or t0.get("att")
        if hf and course_of.get(hf, 1) >= 2:
            others = sorted((r for r in rows if r["frame"] != hf), key=lambda r: -r["p_top3"])[:2]
            pmap = dict(combos)
            ana_bets = [{"combo": f"{hf}-{x['frame']}-{y['frame']}", "p": round(pmap.get(f"{hf}-{x['frame']}-{y['frame']}", 0), 4)}
                   for x, y in ((others[0], others[1]), (others[1], others[0]))]
            ana_reason = ""  # 穴狙いに一本化したため、本線・押さえの下の穴2点は出さない
    # 本線・押さえの組み直し
    #  ・厳選本命の条件 → 1-軸-3着上位の3点だけ（固いレースに10倍前後を10点以上並べない）
    #  ・イン逃げが怪しい（AIのイン1着60%未満）＋3・4コースの攻めの材料あり → 押さえに攻め頭を3点足す
    #    検証（該当1,126レース）：今の10点 的中40%・回収81% → 本線AI上位5点＋押さえ攻め頭3点の8点 的中33%・回収80%
    bet_mode, attack_note = "", ""
    pmap_ = dict(combos)
    normal6 = sorted(main + sub, key=lambda b: -b["p"])[:6]
    normal6 = {"main": normal6[:min(len(main), 4)], "sub": normal6[min(len(main), 4):]}
    if honmei_pick:
        main = [{"combo": c, "p": round(pmap_.get(c, 0), 4)} for c in honmei_pick["bets"]]
        sub = []
        bet_mode = "honmei"
    else:
        inb_m = byc.get(1)
        pin_m = sum(p for cb, p in combos if inb_m and int(cb.split("-")[0]) == inb_m["frame"]) / (sum(p for _, p in combos) or 1)
        att_c = None
        if tsuke_pick:
            att_c = tsuke_pick["course"]
        else:
            for t in tenkai:
                cc = t.get("att_course") if not t.get("type") else (t.get("course") if t.get("type") in ("exgap", "tilt") else None)
                if cc in (3, 4):
                    att_c = cc
                    break
        if inb_m and pin_m < 0.60 and att_c and byc.get(att_c):
            have = {b["combo"] for b in main + sub}
            ah = byc[att_c]["frame"]
            have5 = {b["combo"] for b in sorted(main + sub, key=lambda b: -b["p"])[:5]}
            wall_slow = next((t["wall"] for t in tenkai if not t.get("type") and t.get("att_course") == att_c), None)
            add = [c for c in _ana_bets(ah, att_c, course_of, combos, k=8, tk=tkd.get(byc[att_c].get("toban", "")), drop=wall_slow) if c not in have5][:3]
            if add:
                # 本線はAIの上位5点に絞り、押さえは攻め頭3点だけ（13点→8点。回収率は80%のまま、検証は偶数日81%・奇数日79%）
                top5 = sorted(main + sub, key=lambda b: -b["p"])[:5]
                main = top5
                sub = [{"combo": c, "p": round(pmap_.get(c, 0), 4)} for c in add]
                bet_mode = "attack"
                tkv = tkd.get(byc[att_c].get("toban", ""))
                style = ""
                if tkv and tkv[0] >= 3:
                    keep = (tkv[0] - tkv[1]) / tkv[0]
                    style = (f"（まくって勝った{tkv[0]}回のうちインが2・3着に残ったのは{tkv[0] - tkv[1]}回。" +
                             ("握って回ってインを残す型なので、2・3着にインを入れています）" if keep >= 0.55 else
                              "ツケマイでインごと沈める型なので、2・3着は外寄りにしています）" if keep <= 0.35 else "）"))
                attack_note = f"イン逃げの見込みが{pin_m * 100:.0f}%と低めで、{att_c}コースの攻めの材料があるため、{ah}号艇の頭を押さえに{len(add)}点{style}"
    if not bet_mode:
        # いつものレースも6点まで（検証7,631レース：10点 回収78% / 6点 78%・偶数日76%・奇数日79%。点数を減らしても回収率は同じ）
        allb = sorted(main + sub, key=lambda b: -b["p"])[:6]
        main = allb[:min(len(main), 4)]
        sub = allb[len(main):]
        # 外の頭も2点押さえる：AIが外（2〜6コース）で一番1着を見ている艇の頭、上位2点
        # 検証（9,083レース）：全体の回収率は77%で変わらず、足した2点だけでも73%。外の頭での的中が約3%のレースで拾える
        #（「展示上位＋コース1着率が高い」で選ぶと64%に下がった。オッズがそこを見ているため、AIの確率で選ぶ）
        inb_o = byc.get(1)
        if inb_o:
            heads = {}
            for cb, p in combos:
                h = int(cb.split("-")[0])
                if h != inb_o["frame"]:
                    heads[h] = heads.get(h, 0) + p
            if heads:
                oh = max(heads, key=heads.get)
                have = {b["combo"] for b in main + sub}
                ranked = [cb for cb, _ in sorted(((cb, p) for cb, p in combos if cb.startswith(f"{oh}-")), key=lambda x: -x[1]) if cb not in have]
                add = ranked[:2]
                extra = ""
                # 4コース頭のときは、5コースの選手が「5コースで3着内46%以上（20走以上）」なら、2点のうち1点を5絡みにする
                # 検証（外の頭が4コースで、該当523レース）：AIの上位2点 回収62% → 1点を5絡みに 82%（偶数日75%・奇数日93%）
                if course_of[oh] == 4 and byc.get(5):
                    f5 = byc[5]["frame"]
                    c5 = ((cs_view or {}).get("boats") or {}).get(str(f5)) or ((cs_view or {}).get("boats") or {}).get(f5) or {}
                    if c5.get("starts", 0) >= 20 and (c5.get("top3") or 0) >= 0.46 and not any(str(f5) in cb.split("-")[1:] for cb in add):
                        five = next((cb for cb in ranked if str(f5) in cb.split("-")[1:]), None)
                        if five:
                            add = add[:1] + [five]
                            extra = f"。5コースの{byc[5]['name']}は5コースで3着内{c5['top3'] * 100:.0f}%（{c5['starts']}走）なので、1点は5絡みに"
                if add:
                    sub = sub + [{"combo": c, "p": round(pmap_.get(c, 0), 4)} for c in add]
                    ob = next((b for b in boats if b["frame"] == oh), {})
                    attack_note = f"外の押さえ：{oh}号艇{ob.get('name', '')}（{course_of[oh]}コース）の頭も2点。外の艇でAIが一番1着を見ている艇です{extra}"
    # 逃げ残し巧者（4〜6コースで、イン逃げのとき2・3着に残る率がそのコースの平均より15ポイント以上高い・25走以上）
    try:
        nkd = fstart.load_noko()
    except Exception:
        nkd = {}
    nokoshi = []
    for b in boats:
        cc = course_of[b["frame"]]
        v = nkd.get(f"{b.get('toban', '')}-{cc}") if cc >= 4 else None
        if v and v[0] >= 25 and v[1] / v[0] >= NOKO_BASE[cc] + 0.15:
            nokoshi.append({"frame": b["frame"], "course": cc, "n": v[0], "k": v[1], "rate": round(v[1] / v[0], 3), "base": NOKO_BASE[cc]})
    # B級の逃げ残し巧者がいれば、1-その艇が絡む目のAI上位4点を押さえに入れる（固い3点のレースは除く）
    noko_note = ""
    if bet_mode != "honmei" and byc.get(1):
        I = byc[1]["frame"]
        have = {b["combo"] for b in main + sub}
        for b in boats:
            cc = course_of[b["frame"]]
            v = nkd.get(f"{b.get('toban', '')}-{cc}") if cc in (3, 4, 6) else None   # 5コースはオッズどおりで妙味なし
            if not v or v[0] < 20 or b.get("class") not in ("B1", "B2") or v[1] / v[0] < NOKO_BASE[cc] + 0.10:
                continue
            cs = sorted(((cb, p) for cb, p in combos if cb.startswith(f"{I}-") and str(b["frame"]) in cb.split("-")[1:]), key=lambda x: -x[1])[:4]
            add = [cb for cb, _ in cs if cb not in have]
            sub = sub + [{"combo": cb, "p": round(pmap_.get(cb, 0), 4)} for cb in add]
            have |= set(add)
            noko_note = (f"{b['frame']}号艇{b['name']}（{b.get('class')}）は{cc}コースでイン逃げのとき2・3着に{v[1] / v[0] * 100:.0f}%残す選手"
                         f"（平均{NOKO_BASE[cc] * 100:.0f}%・{v[0]}走）。B級の残し巧者はオッズに軽く見られがちなので、1-{b['frame']}絡みを押さえに")
            break
    # 裏目：4コースがまくり型でスタートも早い → 4が絞って行くと、5コースがまくり差しで突き抜ける形がある
    # 検証（1,806レース）：5頭のAI上位3点 的中44回・回収114%（偶数日101%・奇数日130%）。ただし月ごとの波が大きい（0〜291%）
    ura_note = ""
    if bet_mode != "honmei" and byc.get(4) and byc.get(5):
        r4 = rec.get(byc[4].get("toban", ""))
        if r4 and r4[1] <= 3.0 and len(r4) >= 4 and r4[2] >= 2:
            f5 = byc[5]["frame"]
            have = {b["combo"] for b in main + sub}
            ura = [cb for cb, _ in sorted(((cb, p) for cb, p in combos if cb.startswith(f"{f5}-")), key=lambda x: -x[1])][:3]
            add = [cb for cb in ura if cb not in have]
            if add:
                sub = sub + [{"combo": c, "p": round(pmap_.get(c, 0), 4)} for c in add]
                try:
                    ir = fstart.load_inres().get(byc[1].get("toban", "")) if byc.get(1) else None
                except Exception:
                    ir = None
                itype = ""
                if ir and ir[0] >= 8:
                    out_r = ir[1] / ir[0]
                    itype = ("インは張って抵抗する型（負けると4着以下が" + f"{out_r * 100:.0f}%）で、もつれやすい。" if out_r >= 0.55 else
                             "インは無理に抵抗しない型（負けても2・3着に残すことが多い）なので、5-1の形も。" if out_r <= 0.35 else "")
                ura_note = (f"裏目：4コースの{byc[4]['name']}はまくり型（4コースのまくり勝ち{r4[2]}回）でスタートも早い。"
                            f"4が絞って行くと5コースの{byc[5]['name']}がまくり差しで突き抜ける形があるので、5の頭を{len(add)}点。{itype}")
    # 攻め勝負（インを切る）：4がまくり型でスタートも早いレースは、4頭3点＋5頭3点の6点を別に出す
    # 検証（1,806レース）：インも含めた12点 回収80%・合成の中央値2.0倍 → インを切った6点 回収87%（偶数日78%・奇数日96%）・合成の中央値13.9倍・的中7%
    seme = []
    if byc.get(4) and byc.get(5):
        r4 = rec.get(byc[4].get("toban", ""))
        if r4 and r4[1] <= 3.0 and len(r4) >= 4 and r4[2] >= 2:
            w3 = next((t["wall"] for t in tenkai if not t.get("type") and t.get("att_course") == 4), None)
            seme += _ana_bets(byc[4]["frame"], 4, course_of, combos, k=3, tk=tkd.get(byc[4].get("toban", "")), drop=w3)
            f5 = byc[5]["frame"]
            seme += [cb for cb, _ in sorted(((cb, p) for cb, p in combos if cb.startswith(f"{f5}-")), key=lambda x: -x[1])][:3]
    iw = in_worry(X, course_of, frames, cs_comments)
    # インの展示タイムが、その選手のいつもの順位よりかなり悪い → 行き足・伸びが来ていない可能性
    try:
        exu = fstart.load_exrank()
    except Exception:
        exu = {}
    if inb_ and has_ex:
        u = exu.get(inb_.get("toban", ""))
        tr = next((r.get("exhibit_rank") for r in rows if r["frame"] == inb_["frame"]), None)
        if u and tr and tr - u[1] >= EX_DROP["gap"]:
            why = (f"1コースの{inb_['name']}は展示タイムが6人中{tr}位。いつもは平均{u[1]:.1f}位"
                   + (f"（1位になる割合{u[2] * 100:.0f}%）" if u[2] >= 0.2 else "") + "なので、今日は足が来ていない可能性")
            if iw:
                iw["reasons"] = iw["reasons"] + [why]
            else:
                iw = {"level": 1, "attacker": None, "reasons": [why], "hist_in_win": EX_DROP["in_win"], "hist_races": EX_DROP["n"],
                      "hist_all": EX_DROP["all"], "by": "exdrop"}
    for j in fs:
        if j["course"] == 1 and j["slow"] and j["n"] >= 3:
            why = f"1コースの{j['name']}はF持ち。F後の1コースはスタート順が平均{j['rank']:.1f}番目（{j['n']}走）と遅め"
            if iw:
                iw["reasons"] = [why] + iw["reasons"]
            else:
                iw = {"level": 1, "attacker": None, "reasons": [why], "hist_in_win": None, "hist_races": None,
                      "hist_all": IN_WORRY["all"], "by": "fstart"}
    return {
        "version": PRED_VERSION,
        "stage": "直前" if has_ex else "事前",
        "entry": [f for f, _ in sorted(course_of.items(), key=lambda x: x[1])],
        "entry_changed": entry_changed,
        "wind": wind, "wave_cm": wave,
        "boats": rows, "marks": marks,
        "confidence": {"label": conf[0], "level": conf[1], "top_win": round(pmax, 3)},
        "bets": {"main": main, "sub": sub, "ana": ana_bets, "exacta": exacta, "ana_reason": ana_reason, "mode": bet_mode, "attack": attack_note, "normal": normal6 if bet_mode == "honmei" else None, "hon": main if bet_mode == "honmei" else None, "noko": noko_note, "ura": ura_note, "seme": seme},
        "points": len(main) + len(sub),
        "p3": p3,
        "specialists": spec,
        "in_worry": iw,
        "fstart": fs,
        "tenkai": tenkai,
        "ana_pick": ana,
        "tsuke_pick": tsuke_pick,
        "honmei_pick": honmei_pick,
        "nokoshi": nokoshi,
        "comments": comments,
        "course_stats": cs_view,
        "model": {"trained_on": model.get("trained_on"), "races": model.get("races")},
    }


def _local_notes(S, jcd, boats, venue, entry_changed) -> list[str]:
    """当地の得意・苦手（3連対率の差）と、前付けしやすい選手（展示前のみ）"""
    out, good, bad = [], [], []
    for b in boats:
        t = b.get("toban", "")
        rv = S.rv.get(t, {}).get(jcd) if t in S.rv else None
        tot = sum(S.rv[t].values()) if t in S.rv and S.rv[t] else None
        if rv is not None and tot is not None and rv[0] >= 15 and tot[0] >= 40:
            d = rv[1] / rv[0] - tot[1] / tot[0]
            if d >= 0.12:
                good.append(f"{b['frame']}号艇 {b['name']}（3連対率 {rv[1] / rv[0] * 100:.0f}%、いつもは{tot[1] / tot[0] * 100:.0f}%）")
            elif d <= -0.12:
                bad.append(f"{b['frame']}号艇 {b['name']}（{rv[1] / rv[0] * 100:.0f}%、いつもは{tot[1] / tot[0] * 100:.0f}%）")
    if good:
        out.append(f"{venue['name']}が得意：" + "、".join(good) + "。")
    if bad:
        out.append(f"{venue['name']}が苦手：" + "、".join(bad) + "。")
    if not entry_changed:
        for b in boats:
            f = S.rf.get(b.get("toban", "")) if b.get("toban", "") in S.rf else None
            if b["frame"] >= 2 and f is not None and f[0] >= 30 and f[1] / f[0] >= 0.15:
                out.append(f"進入注意：{b['frame']}号艇 {b['name']}は前付けが多い選手（枠より内に入った率 {f[1] / f[0] * 100:.0f}%）。")
    return out


def _comments(venue, rows, wind, wave, entry_changed, course_of, has_ex, boats) -> list[str]:
    out = []
    c1 = venue["courses"][0]["win"]
    if c1 >= 58:
        out.append(f"{venue['name']}は1コース1着率{c1:.0f}%とイン有利な水面。")
    elif c1 <= 48:
        out.append(f"{venue['name']}は1コース1着率{c1:.0f}%とイン受難の水面。")
    if venue.get("note"):
        out.append(venue["note"])
    # 学習結果：風速・波高が上がるほど1コースの勝率は下がり、4〜6コースは上がる（向きは未反映）
    if (wind.get("speed") or 0) >= 5 or (wave or 0) >= 7:
        out.append(f"風速{wind.get('speed', 0):.0f}m・波高{(wave or 0):.0f}cm：過去データでは荒れ水面ほどイン逃げが減り、外の艇が届きやすい。")
    if entry_changed:
        mv = [f"{f}号艇→{c}コース" for f, c in course_of.items() if f != c]
        out.append("展示で進入変化あり（" + "、".join(mv) + "）。")
    if has_ex:
        top = min(rows, key=lambda r: r["exhibit_time"])
        out.append(f"展示タイム1位は{top['frame']}号艇 {top['name']}（{top['exhibit_time']:.2f}）。")
    else:
        out.append("※展示前の暫定予想です。展示タイムの反映後に更新されます。")
    # F持ちの一言は、その艇の「このレースでの見込み」と合わせて書く（F＝来ない、と読めないように）
    rw = {r["frame"]: r for r in rows}
    for b in boats:
        if b.get("f", 0) < 1:
            continue
        r = rw.get(b["frame"], {})
        c = course_of[b["frame"]]
        if c == 1:
            txt = "スタートを慎重にしやすく、インの逃げには割り引きが必要。"
        elif r.get("p_top3", 0) >= 0.35:
            txt = f"頭（1着）は狙いにくいが、3着内は十分（AIの見込み{r['p_top3'] * 100:.0f}%）。外から残る分には影響は小さい。"
        else:
            txt = "スタートを慎重にしやすく、自分から攻めて勝ち切る形は取りにくい。"
        out.append(f"F持ち：{b['frame']}号艇 {b['name']}（{c}コース）。{txt}")
    return out
