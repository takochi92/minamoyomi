"""F持ち選手の「F後のスタート」を集計する。

  python -m scraper.fstart     # history/ から scraper/fstart.json.gz を作る（毎朝の history ジョブで実行）

F（フライング）を切った選手は、その後しばらくスタートを慎重にする（遅くなる）ことが多い。
F後に同じコースで何走し、平均STとスタート順（6艇中の何番目に早かったか）がどう変わったかを選手ごとに残す。

過去2年の検証（同じ級別どうしで比較）：
  1コースの選手がF持ち・F後のスタート順が平均4位以下 → 1着率 A1 72→66% / A2 60→51% / B1 41→33%
  2・3コースの選手が同じ条件 → すぐ外（3・4コース）の1着率 +1.3〜2.4ポイント（壁にならない）
"""
from __future__ import annotations

import gzip
import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from .history import load_all

OUT = Path(__file__).parent / "fstart.json.gz"
F_DAYS = 150        # F後この日数は「F持ち」として扱う
PRE_DAYS = 180      # F前の比較期間
SLOW_RANK = 4.0     # F後のスタート順の平均がこれ以上 → スタートが遅い（壁にならない）
MIN_N = 2           # F後に同じコースでこれだけ走っていれば判定する
RECENT = 30         # 展開メモ用：直近この走数のスタート順
RECENT_MIN = 6


def _d(s):
    return datetime.strptime(s, "%Y%m%d")


def build(races: list) -> dict:
    races = sorted(races, key=lambda r: (r[0], r[1], r[2]))
    starts = defaultdict(list)      # toban -> [(date, course, st, rank)]
    kim4 = defaultdict(list)        # toban -> 4コースで勝ったときの決まり手（新しい順に最大40）
    inpl = defaultdict(list)        # toban -> 1コースでの着順（最大60走）
    lastF = {}
    for r in races:
        E = r[11]
        sts = sorted((e[3], i) for i, e in enumerate(E) if e[3] is not None and e[4] == "")
        rank = {i: k + 1 for k, (_, i) in enumerate(sts)}
        w = next((e for e in E if e[5] == 1), None)
        if w and w[2] == 4 and r[3]:
            kim4[w[1]].append(r[3])
        for e in E:
            if e[2] == 1 and isinstance(e[5], int):
                inpl[e[1]].append(e[5])
        for i, e in enumerate(E):
            if e[4] == "F":
                lastF[e[1]] = r[0]
            elif e[3] is not None and i in rank:
                starts[e[1]].append((r[0], e[2], e[3], rank[i]))
    if not races:
        return {"asof": "", "racers": {}, "recent": {}}
    asof = races[-1][0]
    lim = (_d(asof) - timedelta(days=F_DAYS)).strftime("%Y%m%d")
    out = {}
    for t, f in lastF.items():
        if f < lim:
            continue
        pre_lim = (_d(f) - timedelta(days=PRE_DAYS)).strftime("%Y%m%d")
        post, pre = defaultdict(list), defaultdict(list)
        for d, c, st, rk in starts[t]:
            if d > f:
                post[c].append((st, rk))
            elif pre_lim <= d < f:
                pre[c].append((st, rk))
        summ = lambda xs: [len(xs), round(sum(x[0] for x in xs) / len(xs), 1), round(sum(x[1] for x in xs) / len(xs), 1)] if xs else [0, None, None]
        out[t] = {"f": f, "post": {str(c): summ(v) for c, v in post.items()}, "pre": {str(c): summ(v) for c, v in pre.items()}}
    # 全選手の直近30走のスタート順（6艇中の何番目に早かったか）の平均
    recent = {}
    for t, xs in starts.items():
        xs = xs[-RECENT:]
        if len(xs) >= RECENT_MIN:
            recent[t] = [len(xs), round(sum(x[3] for x in xs) / len(xs), 2)]
    for t, ks in kim4.items():
        ks = ks[-40:]
        mk, ms = ks.count("まくり"), ks.count("まくり差し")
        if mk + ms >= 3 and t in recent:
            recent[t].extend([mk, ms])
    # インで負けたときの着順：4着以下が多い＝攻められると飛び付いて抵抗する型
    inres = {}
    for t, ps in inpl.items():
        beaten = [p for p in ps[-60:] if p != 1]
        if len(beaten) >= 8:
            inres[t] = [len(beaten), sum(1 for p in beaten if p >= 4)]
    return {"asof": asof, "racers": out, "recent": recent, "inres": inres}


def load() -> dict:
    if not OUT.exists():
        return {}
    with gzip.open(OUT, "rt", encoding="utf-8") as f:
        return json.load(f).get("racers", {})


def load_recent() -> dict:
    if not OUT.exists():
        return {}
    with gzip.open(OUT, "rt", encoding="utf-8") as f:
        return json.load(f).get("recent", {})


def load_inres() -> dict:
    if not OUT.exists():
        return {}
    with gzip.open(OUT, "rt", encoding="utf-8") as f:
        return json.load(f).get("inres", {})


def judge(info: dict | None, course: int) -> dict | None:
    """その選手がこのコースに入ったときの、F後スタートの判定。データ不足なら None。"""
    if not info:
        return None
    n, st, rk = (info.get("post", {}).get(str(course)) or [0, None, None])
    if n < MIN_N:
        return {"f": info["f"], "n": n, "course": course, "slow": None}
    pn, pst, prk = (info.get("pre", {}).get(str(course)) or [0, None, None])
    return {"f": info["f"], "n": n, "course": course, "st": st, "rank": rk, "pre_n": pn, "pre_st": pst, "pre_rank": prk,
            "slow": rk >= SLOW_RANK}


def st_pairs(races: list, before: dict) -> dict:
    """展示のスタートタイミングと本番のスタートタイミングの組（選手ごとに直近80走）"""
    out = defaultdict(list)
    for r in sorted(races, key=lambda r: (r[0], r[1], r[2])):
        b = before.get(f"{r[0]}-{r[1]}-{r[2]}")
        if not b or len(b.get("st") or []) != len(b.get("entry") or []) or not b.get("entry"):
            continue
        for e in r[11]:
            if e[3] is None or e[4] or not e[2] or e[0] not in b["entry"]:
                continue
            ex = b["st"][b["entry"].index(e[0])]
            if ex is None:
                continue
            out[e[1]].append([e[2], round(ex * 100), e[3], r[0]])
    return {t: v[-80:] for t, v in out.items()}


def load_pairs() -> dict:
    if not OUT.exists():
        return {}
    with gzip.open(OUT, "rt", encoding="utf-8") as f:
        return json.load(f).get("stpairs", {})


def main():
    races = load_all((datetime.now() - timedelta(days=400)).strftime("%Y%m%d"))
    lim = (datetime.now() - timedelta(days=F_DAYS + PRE_DAYS + 30)).strftime("%Y%m%d")
    data = build([r for r in races if r[0] >= lim])
    try:
        from .odds import load_before
        data["stpairs"] = st_pairs(races, load_before())
    except Exception:
        data["stpairs"] = {}
    with gzip.open(OUT, "wt", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"fstart: {len(data['racers'])} racers with F (asof {data['asof']})")
    try:
        from . import motor
        motor.main()
    except Exception as ex:
        print("motor skipped:", ex)


if __name__ == "__main__":
    main()
