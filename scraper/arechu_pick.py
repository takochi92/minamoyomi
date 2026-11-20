"""厳選荒れレース（検証中）：荒れ注意のレースのうち「インがA1なのに、AIはインを弱いと見ている」レースだけを選ぶ。

選ぶ条件（両方）
  ・1コースの選手が A1 … 人気が集まりやすく、外の頭のオッズに妙味が出る
  ・AIが見ているインの1着確率が 40% 未満
買い目は arechu.tickets_for（頭＝外の艇でAIの1着確率1位、その頭のAI上位12点）。

検証（過去1年＝2025/11/17〜2026/11/16、荒れ注意9,823レース。AIはそれより前のデータで学習。12点）
  荒れ注意すべて                     9,823レース（1日27） 的中17% 回収82%（前半86%・後半78%）
  インA1 かつ イン確率40%未満（採用）   369レース（1日約1）  的中24% 回収119%（前半115%・後半123%）
  ＋インの展示5位以下                   253レース            的中28% 回収142%（前半123%・後半161%）
  約500通りの組み合わせから選んだので偶然の分は割り引いて見る。上位はどれも「インがA1なのにデータでは弱い」形で、
  前半・後半の両方で100%を超えたものを採った。プレミアムの総評（2026/9/27〜しか無い）は選ぶ条件に使わず、参考として表示するだけ。
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta
from pathlib import Path

IN_CLASS = "A1"
IN_P_MAX = 0.40
_CACHE: dict = {}
_LOCK = threading.Lock()
LEDGER = "arechu_pick.json"


def snapshot(date: str):
    """その日の朝の時点（前日まで）のプレミアム評価。{場: field}。作れないときは {}"""
    with _LOCK:              # レースの更新は並列なので、評価づくりは1回だけ
        if date not in _CACHE:
            _CACHE[date] = _build(date)
        return _CACHE[date]


def _build(date: str):
    try:
        from . import premium_motor as pm
        records, history, schedules = pm.load_inputs()
        through = (datetime.strptime(date, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")
        out = pm.build(records, history, through, schedules)["venues"]
    except Exception:  # 評価が作れなくても、ふつうの予想は止めない
        out = {}
    return out


def overall(race: dict, field: dict) -> dict:
    """{枠: 総評}。今節（同じ節の名前）で前3日以内に更新された評価だけ"""
    title = ((race.get("racelist") or {}).get("title") or "").strip()
    today = datetime.strptime(race["date"], "%Y%m%d")
    out = {}
    for b in (race.get("racelist") or {}).get("boats", []):
        s = (((field or {}).get("pairings") or {}).get(str(b.get("motor_no")), {}).get(str(b.get("toban")), {}) or {}).get("overall")
        if not s or (s.get("title") or "").strip() != title:
            continue
        if (today - datetime.strptime(s["through"], "%Y%m%d")).days > 3:
            continue
        out[b["frame"]] = s["grade"]
    return out


def pick(race: dict, head: int, field: dict | None = None) -> dict | None:
    """厳選なら {'head', 'reasons': [{frame, name, class, p_win, role, grade?}]}。外れたら None。
    grade はプレミアムの総評（あるときだけ。選ぶ条件には使わない）"""
    pb = {b["frame"]: b for b in (race.get("prediction") or {}).get("boats") or []}
    rl = {b["frame"]: b for b in (race.get("racelist") or {}).get("boats", [])}
    inb = next((f for f, b in pb.items() if b.get("course") == 1), None)
    if inb is None or inb not in rl:
        return None
    p_in = pb[inb].get("p_win")
    if rl[inb].get("class") != IN_CLASS or p_in is None or p_in >= IN_P_MAX:
        return None
    reason = {"frame": inb, "name": rl[inb].get("name", ""), "class": IN_CLASS, "p_win": round(p_in, 3), "role": "in"}
    grade = overall(race, field or {}).get(inb)
    if grade:
        reason["grade"] = grade
    return {"head": head, "reasons": [reason]}


def update_ledger(data: Path, dates) -> dict:
    """結果の出た厳選荒れレースを台帳（site/data/arechu_pick.json）に足す。レースのファイルが消えても成績が残る"""
    path = Path(data) / LEDGER
    try:
        book = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        book = {"races": {}}
    changed = False
    for d in dates:
        for f in sorted((Path(data) / "races" / d).glob("*.json")):
            try:
                r = json.loads(f.read_text(encoding="utf-8"))
            except ValueError:
                continue
            slip, res = r.get("primary_slip") or {}, r.get("result") or {}
            if not r.get("arechu_pick") or slip.get("source") != "arechu" or not res.get("finished") or "hit" not in r:
                continue
            key = f"{r['date']}-{r['jcd']}-{r['rno']:02d}"
            row = {"date": r["date"], "jcd": r["jcd"], "venue": r.get("venue", ""), "rno": r["rno"],
                   "head": r["arechu_pick"]["head"], "reasons": r["arechu_pick"]["reasons"],
                   "trifecta": res.get("trifecta"), "hit": bool(r["hit"]), "invest": r["invest"], "return": r["return"]}
            if book["races"].get(key) != row:
                book["races"][key] = row
                changed = True
    if changed:
        path.write_text(json.dumps(book, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return book


def totals(book: dict) -> dict:
    rows = list((book or {}).get("races", {}).values())
    inv = sum(x["invest"] for x in rows)
    ret = sum(x["return"] for x in rows)
    return {"races": len(rows), "hits": sum(1 for x in rows if x["hit"]), "invest": inv, "return": ret,
            "roi": ret / inv if inv else None, "since": min((x["date"] for x in rows), default="")}
