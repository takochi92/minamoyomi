"""毎朝の X 投稿文を site/data から作る（今日の開催・自信度の高いレース・昨日のAI本線の結果）

使い方: python tools/make_daily_x.py [--out out/x.json]
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out/x.json")
    a = ap.parse_args()
    index = json.loads((DATA / "index.json").read_text(encoding="utf-8"))
    history = json.loads((DATA / "history.json").read_text(encoding="utf-8"))
    date, text = build(index, history)
    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    post = {"project": "teirogu", "channel": "X", "date": date, "slot": "morning", "text": text}
    out.write_text(json.dumps({"posts": [post]}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(text)
    print(f"({x_len(text)}/280)")


if __name__ == "__main__":
    main()
