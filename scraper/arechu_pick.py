"""厳選荒れレース（検証中）：荒れ注意のレースのうち、プレミアムのモーター総評で荒れやすいものだけを選ぶ。

選ぶ条件（どちらか）
  ・1コースの艇の総評が D … インのエンジンがいちばん下の評価
  ・頭（外の艇でAIの1着確率1位）の総評が S … 攻める側のエンジンがいちばん上の評価
総評は今節の号機×選手の評価（前日までの今節のレースから作る。初日は無い）。

検証（2026/9/27〜11/16・51日、荒れ注意336レース。AIはそれより前で学習、総評は前日までのデータで作成。12点）
  荒れ注意全部                    336レース 的中20.8%・回収102%
  1コースD または 頭S（採用）       56レース 的中26.8%・回収148%（1日1〜3レース）
  1コースC・D または 頭S・A         125レース 的中23.2%・回収129%（2026/11/19 は17レース中12レースが該当し、多すぎた）
  頭S・A かつ 1コースC・D            37レース 的中27.0%・回収115%
  （総評C・Dの艇を2着から切る形は、どれも回収が下がったので使わない）
9つの選び方を比べていちばん良いものを選んだので、偶然の可能性もある。件数も少ないので「検証中」とし、成績は続けて記録する。
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta
from pathlib import Path

HEAD_GOOD = ("S",)
IN_WEAK = ("D",)
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


def pick(race: dict, head: int, field: dict) -> dict | None:
    """厳選なら {'head', 'reasons': [{frame, name, grade, role}]}。外れたら None"""
    grades = overall(race, field)
    pb = {b["frame"]: b for b in (race.get("prediction") or {}).get("boats") or []}
    names = {b["frame"]: b.get("name", "") for b in (race.get("racelist") or {}).get("boats", [])}
    inb = next((f for f, b in pb.items() if b.get("course") == 1), 1)
    reasons = []
    if grades.get(inb) in IN_WEAK:
        reasons.append({"frame": inb, "name": names.get(inb, ""), "grade": grades[inb], "role": "in"})
    if grades.get(head) in HEAD_GOOD:
        reasons.append({"frame": head, "name": names.get(head, ""), "grade": grades[head], "role": "head"})
    return {"head": head, "reasons": reasons} if reasons else None


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
