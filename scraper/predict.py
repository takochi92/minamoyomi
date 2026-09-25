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

from . import coursestats
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
    fb = [{"frame": b["frame"], "toban": b.get("toban", ""), "course": course_of[b["frame"]],
           "ex": round(ex[b["frame"]] * 100) if has_ex else None, "cls": b.get("class", ""),
           "nat": b.get("nat_win"), "loc": b.get("loc_win"), "motor": b.get("motor_2"), "boat": b.get("boat_2"),
           "f_recent": b.get("f", 0)} for b in boats]
    X = features(S, jcd, wave, weather.get("wind_speed"), fb)
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
    ana = [{"combo": k, "p": round(p, 4)} for k, p in combos if int(k[0]) not in fav2 and k not in used and p >= 0.008][:2]
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
    comments = cs_comments + _comments(venue, rows, wind, wave, entry_changed, course_of, has_ex, boats)
    return {
        "stage": "直前" if has_ex else "事前",
        "entry": [f for f, _ in sorted(course_of.items(), key=lambda x: x[1])],
        "entry_changed": entry_changed,
        "wind": wind, "wave_cm": wave,
        "boats": rows, "marks": marks,
        "confidence": {"label": conf[0], "level": conf[1], "top_win": round(pmax, 3)},
        "bets": {"main": main, "sub": sub, "ana": ana, "exacta": exacta},
        "points": len(main) + len(sub),
        "p3": p3,
        "specialists": spec,
        "in_worry": in_worry(X, course_of, frames, cs_comments),
        "comments": comments,
        "course_stats": cs_view,
        "model": {"trained_on": model.get("trained_on"), "races": model.get("races")},
    }


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
    fh = [b for b in boats if b.get("f", 0) >= 1]
    if fh:
        out.append("F持ち：" + "、".join(f"{b['frame']}号艇" for b in fh) + "（過去データでもF持ちは1着率が下がる）。")
    return out
