"""BOAT RACE オフィシャルサイトの HTML パーサ。

2026-09 時点の HTML 構造に合わせている。サイト側の改修で壊れた場合は
tests/fixtures の HTML を最新のものに差し替えてテストを回すと原因箇所がすぐわかる。
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional

from bs4 import BeautifulSoup


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def _t(el) -> str:
    """要素のテキストを NFKC 正規化・空白整理して返す。"""
    if el is None:
        return ""
    s = unicodedata.normalize("NFKC", el.get_text(" ", strip=True))
    return re.sub(r"\s+", " ", s).strip()


def _lines(el) -> list[str]:
    """<br> 区切りのセルを行ごとのリストにする。"""
    if el is None:
        return []
    s = unicodedata.normalize("NFKC", el.get_text("|", strip=True))
    return [x.strip() for x in s.split("|") if x.strip()]


def _num(s: str) -> Optional[float]:
    m = re.search(r"-?(?:\d+(?:\.\d+)?|\.\d+)", s or "")
    return float(m.group()) if m else None


# ---------------------------------------------------------------- 本日のレース一覧
GRADE_CLASSES = ["SG", "PG1", "G1", "G2", "G3", "ippan"]
GRADE_LABEL = {"SG": "SG", "PG1": "PG1", "G1": "G1", "G2": "G2", "G3": "G3", "ippan": "一般"}
TIMEZONE_LABEL = {"is-nighter": "ナイター", "is-morning": "モーニング", "is-summer": "サマータイム", "is-midnight": "ミッドナイト"}


def parse_index(html: str) -> list[dict]:
    """/owpc/pc/race/index → 開催場のリスト。"""
    soup = _soup(html)
    venues = []
    seen = set()
    for tbody in soup.select(".table1 table tbody"):
        a = tbody.find("a", href=re.compile(r"raceindex\?jcd=\d{2}"))
        if not a:
            continue
        jcd = re.search(r"jcd=(\d{2})", a["href"]).group(1)
        if jcd in seen:
            continue
        seen.add(jcd)
        grade, timezone = "一般", ""
        for td in tbody.find_all("td"):
            for c in td.get("class") or []:
                key = c.replace("is-", "")
                if key in GRADE_CLASSES:
                    grade = GRADE_LABEL[key]
                if c in TIMEZONE_LABEL:
                    timezone = TIMEZONE_LABEL[c]
        day = ""
        for td in tbody.find_all("td"):
            txt = _t(td)
            if re.search(r"\d+/\d+-\d+/\d+", txt):
                day = txt
                break
        text = _t(tbody)
        venues.append({
            "jcd": jcd,
            "title": _t(a),
            "grade": grade,
            "timezone": timezone,
            "day": day,
            "cancelled": "中止" in text,
        })
    return venues


# ---------------------------------------------------------------- 締切予定時刻（出走表・直前情報共通）
def parse_deadlines(html_or_soup) -> dict[int, str]:
    soup = html_or_soup if isinstance(html_or_soup, BeautifulSoup) else _soup(html_or_soup)
    for tr in soup.select(".table1 table tr"):
        tds = tr.find_all("td")
        if tds and "締切予定時刻" in _t(tds[0]):
            times = [_t(td) for td in tds[1:]]
            return {i + 1: t for i, t in enumerate(times) if re.match(r"\d{1,2}:\d{2}", t)}
    return {}


# ---------------------------------------------------------------- 出走表
def parse_racelist(html: str) -> dict:
    soup = _soup(html)
    race = {"deadlines": parse_deadlines(soup)}
    h = soup.select_one(".title16_titleDetail__add2020")
    race["race_name"] = _t(h)
    labels = soup.select_one(".title16_titleLabels__add2020")
    race["labels"] = _t(labels)
    race["fixed_entry"] = "進入固定" in race["labels"]
    title = soup.select_one(".heading2_titleName")
    race["title"] = _t(title)

    boats = []
    tables = soup.select(".table1 table")
    target = None
    for tb in tables:
        if len(tb.select("tbody.is-fs12")) == 6:
            target = tb
            break
    if target is None:
        return race | {"boats": []}
    for tbody in target.select("tbody.is-fs12"):
        tds = tbody.find("tr").find_all("td", recursive=False)
        frame = int(_num(_t(tds[0])))
        info = tds[2]
        divs = info.find_all("div")
        head = _t(divs[0]) if divs else ""  # "4872 / B1"
        toban = re.search(r"\d{4}", head)
        klass = re.search(r"\b(A1|A2|B1|B2)\b", head)
        name = _t(info.select_one(".is-fs18"))
        prof = _lines(divs[2]) if len(divs) > 2 else []
        branch = prof[0] if prof else ""
        age = weight = None
        if len(prof) > 1:
            m = re.search(r"(\d+)歳/([\d.]+)kg", prof[1])
            if m:
                age, weight = int(m.group(1)), float(m.group(2))
        fl = _lines(tds[3])
        f_count = int(_num(fl[0]) or 0) if fl else 0
        l_count = int(_num(fl[1]) or 0) if len(fl) > 1 else 0
        avg_st = _num(fl[2]) if len(fl) > 2 else None

        def trio(td):
            v = [_num(x) for x in _lines(td)]
            return (v + [None, None, None])[:3]

        nat = trio(tds[4])
        loc = trio(tds[5])
        mot = trio(tds[6])
        bt = trio(tds[7])
        boats.append({
            "frame": frame,
            "toban": toban.group() if toban else "",
            "name": name,
            "class": klass.group() if klass else "",
            "branch": branch,
            "age": age,
            "weight": weight,
            "f": f_count,
            "l": l_count,
            "avg_st": avg_st,
            "nat_win": nat[0], "nat_2": nat[1], "nat_3": nat[2],
            "loc_win": loc[0], "loc_2": loc[1], "loc_3": loc[2],
            "motor_no": int(mot[0]) if mot[0] is not None else None, "motor_2": mot[1], "motor_3": mot[2],
            "boat_no": int(bt[0]) if bt[0] is not None else None, "boat_2": bt[1], "boat_3": bt[2],
        })
    race["boats"] = boats
    return race


# ---------------------------------------------------------------- 直前情報
def _st_value(s: str) -> tuple[Optional[float], str]:
    """'.16' → (0.16, ''), 'F.08' → (-0.08, 'F'), 'L' → (None, 'L')"""
    s = (s or "").strip()
    flag = ""
    if s.startswith("F"):
        flag = "F"
        s = s[1:]
    elif s.startswith("L"):
        return None, "L"
    v = _num(s)
    if v is None:
        return None, flag
    if flag == "F":
        v = -v
    return v, flag


def parse_beforeinfo(html: str) -> dict:
    soup = _soup(html)
    out = {"deadlines": parse_deadlines(soup)}

    # 各艇の展示データ
    boats = []
    tb = soup.select_one("table.is-w748")
    if tb:
        for tbody in tb.find_all("tbody"):
            trs = tbody.find_all("tr")
            tds = trs[0].find_all("td", recursive=False)
            if len(tds) < 8:
                continue
            frame = int(_num(_t(tds[0])))
            ex = _num(_t(tds[4]))
            tilt = _num(_t(tds[5]))
            prop = _t(tds[6])
            parts = [_t(x) for x in tds[7].select("li")] or ([_t(tds[7])] if _t(tds[7]) else [])
            adj = None
            if len(trs) > 2:
                t2 = trs[2].find_all("td")
                if t2:
                    adj = _num(_t(t2[0]))
            boats.append({
                "frame": frame,
                "name": _t(tds[2]),
                "weight": _num(_t(tds[3])),
                "adjust_weight": adj,
                "exhibit_time": ex if ex and ex > 0 else None,
                "tilt": tilt,
                "propeller": prop,
                "parts": [p for p in parts if p],
            })
    out["boats"] = boats

    # スタート展示（上から 1 コース）
    st = []
    for i, div in enumerate(soup.select(".table1_boatImage1"), 1):
        num = _num(_t(div.select_one(".table1_boatImage1Number")))
        v, flag = _st_value(_t(div.select_one(".table1_boatImage1Time")))
        if num is None:
            continue
        st.append({"course": i, "frame": int(num), "st": v, "flag": flag})
    out["start_exhibition"] = st

    # 水面気象
    w = soup.select_one(".weather1")
    weather = {}
    if w:
        title = _t(w.select_one(".weather1_title"))
        m = re.search(r"(\d{1,2}:\d{2})", title)
        weather["as_of"] = m.group(1) if m else ""

        def unit(cls):
            return w.select_one(f".weather1_bodyUnit.{cls}")

        def data(cls):
            u = unit(cls)
            return _t(u.select_one(".weather1_bodyUnitLabelData")) if u else ""

        weather["air_temp"] = _num(data("is-direction"))
        u = unit("is-weather")
        weather["weather"] = _t(u.select_one(".weather1_bodyUnitLabelTitle")) if u else ""
        weather["wind_speed"] = _num(data("is-wind"))
        weather["water_temp"] = _num(data("is-waterTemperature"))
        weather["wave_cm"] = _num(data("is-wave"))
        wd = None
        u = unit("is-windDirection")
        if u:
            img = u.select_one(".weather1_bodyUnitImage")
            for c in (img.get("class") if img else []) or []:
                mm = re.match(r"is-wind(\d+)$", c)
                if mm:
                    wd = int(mm.group(1))
        weather["wind_dir"] = wd
    out["weather"] = weather
    out["exhibition_done"] = bool(boats) and all(b["exhibit_time"] for b in boats)
    return out


# ---------------------------------------------------------------- 結果
def parse_result(html: str) -> dict:
    soup = _soup(html)
    res = {"trifecta": None, "trifecta_payout": None, "exacta": None, "exacta_payout": None, "win": None, "win_payout": None,
           "refunded": [], "kimarite": ""}
    for table in soup.select("table"):
        if "勝式" not in _t(table.find("thead") or table.find("tr")):
            continue
        for tbody in table.find_all("tbody"):
            first = tbody.find("tr")
            if not first:
                continue
            tds = first.find_all("td")
            if not tds:
                continue
            kind = _t(tds[0])
            nums = [_t(s) for s in first.select(".numberSet1_number")]
            pay = _num(_t(first.select_one(".is-payout1")).replace(",", "")) if first.select_one(".is-payout1") else None
            combo = "-".join(nums) if nums else None
            if kind == "3連単" and combo:
                res["trifecta"], res["trifecta_payout"] = combo, int(pay) if pay else None
            elif kind == "2連単" and combo:
                res["exacta"], res["exacta_payout"] = combo, int(pay) if pay else None
            elif kind == "単勝" and combo:
                res["win"], res["win_payout"] = int(combo), int(pay) if pay else None
    for table in soup.select("table"):
        head = _t(table.find("tr"))
        if head.startswith("決まり手"):
            tds = table.find_all("td")
            if tds:
                res["kimarite"] = _t(tds[0])
        if head.startswith("返還"):
            res["refunded"] = [_t(s) for s in table.select(".numberSet1_number")]
    res["finished"] = res["trifecta"] is not None
    return res
