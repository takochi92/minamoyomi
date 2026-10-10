"""X の投稿文を site/data から作る
  morning … 今日の開催・自信度の高いレース・昨日のAI本線の結果（毎朝 8:13）
  evening … 今日のAI本線の結果（外れも含む）と、今日フライングした選手（毎晩 21:43）
  feature … 機能紹介。tools/x_feature.txt の本文をそのまま（手動で実行したときだけ）

使い方: python tools/make_daily_x.py [--slot morning|evening|feature] [--out out/x.json]
出力: Atelier に送る形の JSON（{"posts": [{"project": "teirogu", "channel": "X", ...}]}）と、本文を標準出力に
"""
import argparse
import datetime as dt
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "site" / "data"
SITE = "https://teilog.pages.dev"
WEEK = "月火水木金土日"
TAGS = "#ボートレース #競艇予想"
NOTE = "※20歳未満は購入不可。のめり込みに注意"


def x_len(text):
    """X の数え方：全角2・半角1、URL は 23"""
    text = re.sub(r"https?://\S+", "x" * 23, text)
    return sum(2 if ord(c) > 0x2FF else 1 for c in text)


def build(index, history):
    day = dt.datetime.strptime(index["date"], "%Y%m%d").date()
    venues = [v for v in index.get("venues", []) if not v.get("cancelled")]
    head = [f"【{day.month}/{day.day}（{WEEK[day.weekday()]}）の艇ろぐ】", f"今日は{len(venues)}場で開催"]
    big = [f"🏆{v['name']} {v['grade']}"
           for v in venues if v.get("grade") and v["grade"] != "一般"]

    # AI の自信度が高いレース（鉄板）を締切の早い順に
    sure = sorted((r.get("deadline", "99:99"), f"{v['name']}{r['rno']}R")
                  for v in venues for r in v.get("races", []) if r.get("confidence") == "鉄板")

    prev = (day - dt.timedelta(days=1)).strftime("%Y%m%d")
    h = history.get(prev) or {}
    result = []
    if h.get("races"):
        result = [f"昨日のAI本線：{h['races']}レース中 {h.get('hits_main', 0)}的中"]
        best = (h.get("best") or [None])[0]
        if best:
            result.append(f"最高配当 {best['venue']}{best['rno']}R {best['combo']} {best['payout']:,}円")

    tail = ["予想・直前情報はこちら", SITE, NOTE, TAGS]

    def compose(n_big, n_sure, n_result):
        blocks = [head + big[:n_big]]
        if sure[:n_sure]:
            blocks.append(["AIの自信が高いレース", "・" + "、".join(n for _, n in sure[:n_sure])])
        if result[:n_result]:
            blocks.append(result[:n_result])
        blocks.append(tail)
        return "\n\n".join("\n".join(b) for b in blocks)

    # 長すぎたら、自信のあるレースの数 → 大きな大会の行 → 最高配当 の順に減らす
    n_big, n_sure, n_result = min(len(big), 2), min(len(sure), 4), len(result)
    text = compose(n_big, n_sure, n_result)
    while x_len(text) > 280:
        if n_sure > 2:
            n_sure -= 1
        elif n_big > 0:
            n_big -= 1
        elif n_result > 1:
            n_result -= 1
        elif n_sure > 0:
            n_sure -= 1
        else:
            break
        text = compose(n_big, n_sure, n_result)
    return day.isoformat(), text


def flyings(day, races_dir):
    """その日のレース結果から、フライング（F）した選手 → [(締切, 場, R, 名前)]"""
    out = []
    for p in sorted((races_dir / day).glob("*.json")):
        try:
            r = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        res = r.get("result") or {}
        if not res.get("finished"):
            continue
        names = {b.get("frame"): b.get("name", "") for b in (r.get("racelist") or {}).get("boats", [])}
        for s in res.get("start") or []:
            if s.get("flag") == "F":
                out.append((r.get("deadline", ""), r.get("venue", ""), r.get("rno"), names.get(s.get("frame"), "").replace("\u3000", " ")))
    return sorted(out)


def build_evening(index, history, races_dir):
    day = dt.datetime.strptime(index["date"], "%Y%m%d").date()
    h = history.get(index["date"]) or {}
    head = [f"【{day.month}/{day.day}（{WEEK[day.weekday()]}）の結果】"]
    result, best = [], []
    if h.get("races"):
        result.append(f"AI本線 {h['races']}R中{h.get('hits_main', 0)}的中")
        b = (h.get("best") or [None])[0]
        if b:
            best.append(f"最高配当 {b['venue']}{b['rno']}R {b['combo']} {b['payout']:,}円")
    fs = flyings(index["date"], races_dir)
    tail = [SITE, NOTE, TAGS]

    def compose(n, with_best):
        if fs:
            fl = [f"今日のフライング {len(fs)}人（F後はスタート控えめになりがち）"] + [f"・{v}{rno}R {name}" for _, v, rno, name in fs[:n]] + (["ほか"] if n < len(fs) else [])
        else:
            fl = ["今日のフライングは0人でした"]
        return "\n\n".join("\n".join(x) for x in [head + result + (best if with_best else []), fl, tail] if x)

    # 長すぎたら、最高配当 → フライングの名前（後ろから）の順に減らす
    n, with_best = len(fs), True
    text = compose(n, with_best)
    while x_len(text) > 280:
        if with_best and best:
            with_best = False
        elif n > 0:
            n -= 1
        else:
            break
        text = compose(n, with_best)
    return day.isoformat(), text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out/x.json")
    ap.add_argument("--slot", default="morning", choices=["morning", "evening", "feature"])
    a = ap.parse_args()
    index = json.loads((DATA / "index.json").read_text(encoding="utf-8"))
    history = json.loads((DATA / "history.json").read_text(encoding="utf-8"))
    if a.slot == "evening":
        date, text = build_evening(index, history, DATA / "races")
    elif a.slot == "feature":
        date = (dt.datetime.utcnow() + dt.timedelta(hours=9)).date().isoformat()
        text = (ROOT / "tools" / "x_feature.txt").read_text(encoding="utf-8").strip()
        if x_len(text) > 280:
            raise SystemExit(f"x_feature.txt が長すぎます（{x_len(text)}/280）")
    else:
        date, text = build(index, history)
    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    post = {"project": "teirogu", "channel": "X", "date": date, "slot": a.slot, "text": text}
    out.write_text(json.dumps({"posts": [post]}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(text)
    print(f"({x_len(text)}/280)")


if __name__ == "__main__":
    main()
