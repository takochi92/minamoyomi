"""レースページの「コース戦績」欄と見立てコメント（数値は直近365日の公式データ集計）。

予想の加点そのものは model.features()（rc_win・mu）で行い、ここは表示と説明だけを担当する。
"""
from __future__ import annotations

from .model import KIM, Stats


def _loss_rates(L, n):
    if not n:
        return {}
    sashi = L.get("2-差し", 0)
    makuri = sum(v for k, v in L.items() if k.endswith("-まくり"))
    mz = sum(v for k, v in L.items() if k.endswith("-まくり差し"))
    other = sum(L.values()) - sashi - makuri - mz
    return {"差され": sashi / n, "捲られ": makuri / n, "捲り差され": mz / n, "その他": other / n}


def boat_profile(S: Stats, toban, course):
    nat, me = S.nc[course], S.rc[toban][course]
    n = me[0]
    st = S.rst[toban]
    return {
        "starts": int(n),
        "win": me[1] / n if n else None,
        "top2": (me[1] + me[2]) / n if n else None,
        "top3": (me[1] + me[2] + me[3]) / n if n else None,
        "kimarite": {k: int(me[4 + i]) for i, k in enumerate(KIM) if me[4 + i]},
        "avg_st": round(st[0] / st[1], 2) if st[1] else None,
        "nat_win": nat[1] / nat[0] if nat[0] else None,
        "nat_top3": (nat[1] + nat[2] + nat[3]) / nat[0] if nat[0] else None,
    }


def in_profile(S: Stats, toban, jcd):
    c1, n1 = S.rc[toban][1], S.nc[1]
    return {
        "starts": int(c1[0]),
        "escape": c1[1] / c1[0] if c1[0] else None,
        "loss": _loss_rates(S.rl[toban], c1[0]),
        "nat_escape": n1[1] / n1[0] if n1[0] else None,
        "nat_loss": _loss_rates(S.nl, S.nn),
        "ven_loss": _loss_rates(S.vl[jcd], S.vn[jcd]),
    }


def view(S: Stats, jcd: str, boats: list[dict]):
    prof = {b["frame"]: boat_profile(S, b["toban"], b["course"]) for b in boats}
    inb = next((b for b in boats if b["course"] == 1), None)
    inp = in_profile(S, inb["toban"], jcd) if inb else None
    return {"in": inp, "boats": prof}, _comments(inb, inp, boats, prof)


def _comments(inb, inp, boats, prof):
    out = []
    if not inp or inp["starts"] < 10:
        return out
    esc, nesc = inp["escape"], inp["nat_escape"]
    if esc is not None and nesc:
        out.append(f"1コース{inb['name']}の逃げ率{esc*100:.0f}%（全国平均{nesc*100:.0f}%・{inp['starts']}走）。")
    weapon = {"差され": ("差し", [2]), "捲られ": ("まくり", [2, 3, 4, 5]), "捲り差され": ("まくり差し", [3, 4, 5])}
    for loss, (kim, courses) in weapon.items():
        r, nr = inp["loss"].get(loss, 0), inp["nat_loss"].get(loss, 0)
        if nr and r >= nr * 1.3 and r >= 0.06:
            line = f"{inb['name']}は{loss}率{r*100:.0f}%（全国{nr*100:.0f}%）"
            hits = [f"{b['course']}コース{b['name']}（このコースで{kim}勝ち{prof[b['frame']]['kimarite'][kim]}回）"
                    for b in boats if b["course"] in courses and prof[b["frame"]]["kimarite"].get(kim, 0) >= 2]
            out.append(line + ("。" + "、".join(hits) + "の" + kim + "に警戒。" if hits else "。"))
    return out
