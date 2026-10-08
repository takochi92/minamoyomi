"""X（旧Twitter）に貼るための文。share.html（コピー用）と weekly.html（週ごとの成績）で使う。

・どの文も280（全角140字）に収まるように、項目の数を減らして調整する
・「必ず当たる」「儲かる」とは書かない。外れも含めた数字をそのまま出す
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from urllib.parse import quote

LIMIT = 280
TAGS = "#ボートレース #競艇予想"
NOTE = "※20歳未満は購入できません"


def weight(text: str) -> int:
    """X の文字数の数え方（URLは23、半角は1、全角は2）"""
    t = re.sub(r"https?://\S+", "x" * 23, text)
    return sum(1 if ord(c) < 0x1100 or 0x2000 <= ord(c) <= 0x200D or 0x2010 <= ord(c) <= 0x201F else 2 for c in t)


def fit(head: str, items: list[str], tail: str) -> str:
    """head・items・tail を改行でつなぎ、280に収まるまで items を後ろから減らす"""
    items = list(items)
    while True:
        t = "\n".join([head, *items, "", tail]).strip()
        if weight(t) <= LIMIT or not items:
            return t
        items.pop()


def intent(text: str) -> str:
    return "https://twitter.com/intent/tweet?text=" + quote(text)


def mday(d: str) -> str:
    wd = "月火水木金土日"[datetime.strptime(d, "%Y%m%d").weekday()]
    return f"{int(d[4:6])}/{int(d[6:8])}({wd})"


def pct(a, b, digits=0):
    return f"{a / b * 100:.{digits}f}%" if b else "-"


def morning(d: str, venues: list[dict], url: str) -> str:
    """今日の注目：AIの見込みが高い順（level）に、締切前のレース"""
    rows = []
    for v in venues:
        if v.get("cancelled"):
            continue
        for r in v.get("races", []):
            if r.get("result") or not r.get("honmei"):
                continue
            rows.append((-(r.get("level") or 0), r.get("deadline", ""), v["name"], r))
    rows.sort(key=lambda x: (x[0], x[1]))
    items = [f"・{n}{r['rno']}R（{r['deadline']}）{r.get('confidence', '')} 本線 {r['honmei'][0]}" for _, _, n, r in rows[:5]]
    n = sum(1 for v in venues if not v.get("cancelled"))
    return fit(f"【{mday(d)} AI予想】開催{n}場\nAIの見込みが高いレース", items, f"全レースの予想 {url}\n{TAGS}")


def targets(d: str, items: list[tuple], url: str) -> str:
    """狙い目レーサー：items = [(venue, rno, deadline, course, name, class)]"""
    rows = [f"・{v}{rno}R（{dl}）{c}コース {name}（{cls}）" for v, rno, dl, c, name, cls in items[:5]]
    return fit(f"【{mday(d)} 狙い目レーサー】\n今日のコースで、実力のわりに勝てている選手", rows, f"{url}\n{TAGS}")


def confident(venue: str, rno: int, deadline: str, n: int, comp: float, url: str) -> str:
    return fit(f"【自信ありレース】{venue}{rno}R 締切{deadline}", [f"AIの見込みが高く、合成オッズ{comp:.1f}倍で{n}点に絞れたレースです"],
               f"{url}\n#ボートレース{venue} #競艇予想\n{NOTE}")


def buff_all(items: list[tuple], url: str) -> str:
    """バフ全部のせ：items = [(場, R, 締切, 艇番, コース, [バフ名])]"""
    rows = [f"・{v}{rno}R（{dl}）{f}号艇 {c}コース：{'・'.join(bf)}" for v, rno, dl, f, c, bf in items[:4]]
    return fit("【バフ全部のせ】\n展示・モーター・得意コース・得意場・スタートの強みが4つ以上そろった艇", rows, f"{url}\n{TAGS}")


def day_result(d: str, h: dict, url: str) -> str:
    """その日の結果（外れも含めて）"""
    items = [f"本線・押さえ {h.get('races', 0)}R中{h.get('hits', 0)}的中・回収率{pct(h.get('return', 0), h.get('invest', 0))}"]
    if h.get("rc_races"):
        items.append(f"自信あり {h['rc_races']}R中{h.get('rc_hits', 0)}的中・回収率{pct(h.get('rc_return', 0), h.get('rc_invest', 0))}")
    best = (h.get("best") or [])[:2]
    items += [f"高配当 {b['venue']}{b['rno']}R {b['combo']} {b['payout']:,}円" for b in best]
    return fit(f"【{mday(d)}の結果】", items, f"外れも含めて毎日公開しています\n{url}\n{TAGS}")


KEYS = ("races", "hits", "invest", "return", "rc_races", "rc_hits", "rc_invest", "rc_return", "h_races", "h_hits", "h_invest", "h_return")


def week_sum(hist: dict, start: str, end: str) -> dict:
    out = {k: 0 for k in KEYS}
    best, days = [], 0
    for d, h in hist.items():
        if start <= d <= end:
            days += 1
            for k in KEYS:
                out[k] += h.get(k, 0) or 0
            best += [{**b, "date": d} for b in h.get("best") or []]
    out["best"] = sorted(best, key=lambda b: -b.get("payout", 0))[:5]
    out["days"] = days
    return out


def weeks(hist: dict, today: str, n: int = 4) -> list[tuple[str, str, dict]]:
    """今日より前に終わった週（月〜日）を新しい順に"""
    t = datetime.strptime(today, "%Y%m%d")
    end = t - timedelta(days=t.weekday() + 1)          # 先週の日曜
    out = []
    for _ in range(n):
        start = end - timedelta(days=6)
        s, e = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")
        w = week_sum(hist, s, e)
        if w["days"]:
            out.append((s, e, w))
        end = start - timedelta(days=1)
    return out


def week_text(s: str, e: str, w: dict, url: str) -> str:
    items = [f"本線・押さえ {w['races']:,}R中{w['hits']:,}的中（{pct(w['hits'], w['races'])}）回収率{pct(w['return'], w['invest'])}"]
    if w["rc_races"]:
        items.append(f"自信あり {w['rc_races']}R中{w['rc_hits']}的中・回収率{pct(w['rc_return'], w['rc_invest'])}")
    if w["h_races"]:
        items.append(f"厳選本命 {w['h_races']}R中{w['h_hits']}的中・回収率{pct(w['h_return'], w['h_invest'])}")
    if w["best"]:
        b = w["best"][0]
        items.append(f"最高配当 {b['venue']}{b['rno']}R {b['combo']} {b['payout']:,}円")
    return fit(f"【先週の成績 {int(s[4:6])}/{int(s[6:])}〜{int(e[4:6])}/{int(e[6:])}】", items, f"外れも含めて全部公開しています\n{url}\n{TAGS}")
