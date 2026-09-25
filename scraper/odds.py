"""3連単オッズの取得・保存と、オッズ×AIの合成確率による期待値判定。

・公式の odds3t ページは「列＝1着艇、行＝2着・3着の組」の並び。これを 1-2-3, 1-2-4 … 6-5-4 の順（COMBOS）に並べ直す。
・市場の確率 q はオッズの逆数を正規化したもの。AIの確率 m と q^a × m^b で混ぜ、期待値 = 合成確率 × オッズ。
  a, b は scraper/ev_eval.py が過去レースで決めて model.json の "blend" に保存する。
"""
from __future__ import annotations

import gzip
import itertools
import json
import math
import re
from pathlib import Path

COMBOS = [f"{a}-{b}-{c}" for a, b, c in itertools.permutations(range(1, 7), 3)]
RE_ODDS = re.compile(r'class="oddsPoint[^"]*">([^<]*)<')
ODDS_DIR = Path(__file__).resolve().parent.parent / "history" / "odds"
DEFAULT_BLEND = {"market": 0.9, "model": 0.2, "ev_min": 1.0, "max_odds": 200.0, "status": "検証中"}


def parse_odds3t(html: str) -> list[float] | None:
    cells = RE_ODDS.findall(html)
    if len(cells) != 120:
        return None
    out = [math.nan] * 120
    for i, c in enumerate(cells):
        c = c.strip()
        try:
            v = float(c)
        except ValueError:
            v = math.nan
        out[(i % 6) * 20 + i // 6] = v
    return out


def market_probs(odds: list[float]) -> list[float]:
    inv = [1 / o if o and o == o and o > 0 else 0.0 for o in odds]
    s = sum(inv)
    return [v / s for v in inv] if s else [0.0] * len(odds)


def blend(model_p: dict, odds: list[float], a: float, b: float) -> list[float]:
    q = market_probs(odds)
    z = []
    for k, qi in zip(COMBOS, q):
        m = max(model_p.get(k, 0.0), 1e-9)
        z.append(math.exp(a * math.log(max(qi, 1e-9)) + b * math.log(m)) if qi > 0 else 0.0)
    s = sum(z)
    return [v / s for v in z] if s else z


def value_bets(model_p: dict, odds: list[float], params: dict | None = None) -> dict:
    p = {**DEFAULT_BLEND, **(params or {})}
    pb = blend(model_p, odds, p["market"], p["model"])
    bets = []
    for k, o, x in zip(COMBOS, odds, pb):
        if o == o and o and o <= p["max_odds"] and x * o >= p["ev_min"]:
            bets.append({"combo": k, "odds": o, "p": round(x, 4), "ev": round(x * o, 2)})
    bets.sort(key=lambda b: -b["ev"])
    return {"bets": bets, "params": {k: p[k] for k in ("market", "model", "ev_min", "max_odds", "status")},
            "skip": not bets}


# ---------------------------------------------------------------- 蓄積（確定オッズ）
def _file(ym):
    return ODDS_DIR / f"{ym}.jsonl.gz"


def load_month(ym) -> dict:
    p, out = _file(ym), {}
    if p.exists():
        with gzip.open(p, "rt", encoding="utf-8") as f:
            for line in f:
                k, v = json.loads(line)
                out[k] = [math.nan if x is None else x for x in v]
    return out


def save_month(ym, data: dict):
    ODDS_DIR.mkdir(parents=True, exist_ok=True)
    with gzip.open(_file(ym), "wt", encoding="utf-8") as f:
        for k in sorted(data):
            f.write(json.dumps([k, [None if x != x else x for x in data[k]]], separators=(",", ":")) + "\n")


def load_all() -> dict:
    out = {}
    for p in sorted(ODDS_DIR.glob("*.jsonl.gz")):
        out.update(load_month(p.name[:6]))
    return out


# ---------------------------------------------------------------- 蓄積（直前情報：展示の進入・ST・チルト・気象）
BEFORE_DIR = Path(__file__).resolve().parent.parent / "history" / "before"


def load_before() -> dict:
    out = {}
    for p in sorted(BEFORE_DIR.glob("*.jsonl.gz")):
        with gzip.open(p, "rt", encoding="utf-8") as f:
            for line in f:
                k, v = json.loads(line)
                out[k] = v
    return out


def save_before(data: dict):
    BEFORE_DIR.mkdir(parents=True, exist_ok=True)
    by = {}
    for k, v in data.items():
        by.setdefault(k[:6], {})[k] = v
    for ym, d in by.items():
        p = BEFORE_DIR / f"{ym}.jsonl.gz"
        old = {}
        if p.exists():
            with gzip.open(p, "rt", encoding="utf-8") as f:
                old = dict(json.loads(l) for l in f)
        old.update(d)
        with gzip.open(p, "wt", encoding="utf-8") as f:
            for k in sorted(old):
                f.write(json.dumps([k, old[k]], ensure_ascii=False, separators=(",", ":")) + "\n")


def pre_race_overrides(before: dict) -> dict:
    """直前情報から、締切前に分かる進入（展示の並び）と気象を取り出す"""
    out = {}
    for k, v in before.items():
        entry = v.get("entry") or []
        if sorted(entry) != [1, 2, 3, 4, 5, 6]:
            continue
        out[k] = {"course": {f: i + 1 for i, f in enumerate(entry)}, "wave": v.get("wave") or 0, "wind": v.get("wind") or 0}
    return out


def parse_oddstf(html: str) -> list[float] | None:
    """単勝オッズ（1〜6号艇）"""
    cells = RE_ODDS.findall(html)[:6]
    if len(cells) != 6:
        return None
    out = []
    for c in cells:
        try:
            out.append(float(c.strip()))
        except ValueError:
            out.append(math.nan)
    return out


# 検証中の仮説：B級で、展示の進入が3・4コース、かつそのコースでの1着率が全国平均の約1.5倍以上（rc_win≧0.4）の艇は、
# 市場（オッズ）の見立てより勝っている。単勝で狙う。
SPECIALIST_RULE = {"classes": ["B1", "B2"], "courses": [3, 4], "rc_win_min": 0.4}


def parse_odds2t(html: str) -> dict | None:
    """2連単オッズ {"1-2": 16.7, ...}（公式の並び：列=1着艇、行=2着艇の昇順）"""
    cells = RE_ODDS.findall(html)
    if len(cells) < 30:
        return None
    out = {}
    for i, c in enumerate(cells[:30]):
        a = i % 6 + 1
        b = [x for x in range(1, 7) if x != a][i // 6]
        try:
            out[f"{a}-{b}"] = float(c.strip())
        except ValueError:
            pass
    return out


# ---------------------------------------------------------------- 推奨買い目（合成オッズの下限つき）
# max_over_market: AIの確率がオッズから見た確率の2倍を超える目は入れない。
#   合成オッズを保つために、勝率・戦績の低い艇の人気薄を「穴埋め」で拾わないため（過去9千レースで回収率は変わらず、市場0.5%未満の超穴は0に）
RECO_RULE = {"min_comp": 5.0, "max_points": 10, "min_p": 0.01, "gachi_top_odds": 5.0, "confident_ai": 0.25, "max_over_market": 2.0}


def recommend(model_p3: list[float], odds: list[float], rule: dict | None = None) -> dict:
    """AIの確率が高い順に3連単を足し、合成オッズ（1/Σ(1/オッズ)）が下限を割らない範囲で最大10点選ぶ。

    判定：AIの本命の目が min_comp 倍未満 → 「購入非推奨（ガチガチ）」
          選んだ目のAI的中見込み ≥ confident_ai → 「自信あり」、それ以外 → 「推奨」
    市場の的中見込み（オッズから逆算）も併記する。過去検証では実際の的中率はこちらに近い。
    """
    r = {**RECO_RULE, **(rule or {})}
    q = market_probs(odds)
    ok = [o == o and o and o > 0 for o in odds]
    order = sorted(range(120), key=lambda j: -model_p3[j])
    top = order[0]
    picked, inv = [], 0.0
    for j in order:
        if len(picked) >= r["max_points"] or model_p3[j] < r["min_p"]:
            break
        if ok[j] and r.get("max_over_market") and model_p3[j] > r["max_over_market"] * q[j]:
            continue
        if ok[j] and inv + 1 / odds[j] <= 1 / r["min_comp"]:
            picked.append(j)
            inv += 1 / odds[j]
    comp = 1 / inv if inv else None
    ai_hit = sum(model_p3[j] for j in picked)
    mk_hit = sum(q[j] for j in picked)
    if not ok[top] or odds[top] < r["gachi_top_odds"]:
        verdict = "購入非推奨"
    elif not picked:
        verdict = "見送り"
    elif ai_hit >= r["confident_ai"]:
        verdict = "自信あり"
    else:
        verdict = "推奨"
    # 合成オッズどおりの配分（100円単位）。どれが当たっても払戻がほぼ同じになる最小の予算を探す
    alloc, alloc_min_ret = {}, None
    if picked:
        alloc, alloc_min_ret = allocate([odds[j] for j in picked], [COMBOS[j] for j in picked])
    return {"verdict": verdict, "bets": [{"combo": COMBOS[j], "odds": odds[j], "p": round(model_p3[j], 4)} for j in picked],
            "comp": round(comp, 2) if comp else None, "ai_hit": round(ai_hit, 3), "market_hit": round(mk_hit, 3),
            "top": {"combo": COMBOS[top], "odds": odds[top] if ok[top] else None}, "alloc": alloc,
            "alloc_min_return": alloc_min_ret, "comp_exact": round(comp, 2) if comp else None, "rule": r}


def allocate(odds_list: list[float], names: list[str], max_budget: int = 5000) -> tuple[dict, int]:
    """100円単位で、どれが当たっても払戻がそろう配分を探す。
    合成オッズの理論値（予算×合成オッズ）に対して、いちばん少ない払戻が97%以上になる最小予算を採用。"""
    inv = [1 / o for o in odds_list]
    s = sum(inv)
    best = None
    for budget in range(100 * len(odds_list), max_budget + 1, 100):
        units = [max(1, round(budget * x / s / 100)) for x in inv]
        total = sum(units) * 100
        min_ret = min(u * 100 * o for u, o in zip(units, odds_list))
        score = min_ret / total * s          # 1.0 = 理論どおり
        if best is None or score > best[0] + 1e-9:
            best = (score, units, total, min_ret)
        if score >= 0.97:
            break
    _, units, total, min_ret = best
    return {n: u * 100 for n, u in zip(names, units)}, int(min_ret)
