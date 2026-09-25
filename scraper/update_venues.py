"""レース場データ（直近3か月のコース別成績・水質・干満差）を公式サイトから取り直す。

  python -m scraper.update_venues

月1回（GitHub Actions の monthly ジョブ）で実行する想定。
手書きのメモ（note）は残したまま、数値だけ差し替える。
"""
import json
import time
import re
import unicodedata
from pathlib import Path

from bs4 import BeautifulSoup

from .fetch import Fetcher

PATH = Path(__file__).parent / "venues.json"
KIM = ["逃げ", "捲り", "差し", "捲り差し", "抜き", "恵まれ"]


def parse_stadium(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "header", "footer"]):
        t.decompose()
    lines = [unicodedata.normalize("NFKC", x).strip() for x in (soup.find("main") or soup.body).get_text("\n").split("\n")]
    lines = [x for x in lines if x]
    i0 = lines.index("恵まれ")
    nums = []
    for s in lines[i0 + 1:]:
        if re.fullmatch(r"[\d.]+", s):
            nums.append(float(s))
        if len(nums) >= 78:
            break
    courses = []
    for c in range(6):
        b = nums[c * 13:(c + 1) * 13]
        courses.append({"course": c + 1, "win": b[1], "second": b[2], "third": b[3], "kimarite": dict(zip(KIM, b[7:13]))})
    period = next((re.search(r"集計期間:(.+?)単位", x).group(1).strip() for x in lines if "集計期間" in x), "")

    def after(key):
        return lines[lines.index(key) + 1] if key in lines else ""

    return {"courses": courses, "water": after("水質"), "tide": after("干満差") == "あり", "period": period}


def main():
    data = json.loads(PATH.read_text(encoding="utf-8"))
    f = Fetcher(max_requests=30)
    period = ""
    for jcd, v in data["venues"].items():
        time.sleep(1.5)
        html = f.s.get("https://www.boatrace.jp/owpc/pc/data/stadium", params={"jcd": jcd}, timeout=20).text
        s = parse_stadium(html)
        v.update(courses=s["courses"], water=s["water"] or v["water"], tide=s["tide"])
        period = s["period"] or period
    if period:
        data["period"] = period + "（BOAT RACE公式 レース場データ）"
    PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print("updated", period)


if __name__ == "__main__":
    main()
