"""公式「競走成績」テキスト（Kファイル）のパーサ。

1ファイル＝1日分・全場。各レースについて 着順・艇番・登番・進入コース・ST・
1着艇の決まり手・風向（方位）・風速・波高 が取れる。
"""
from __future__ import annotations

import re
import unicodedata

RE_VENUE = re.compile(r"^(\d{2})KBGN")
RE_DATE = re.compile(r"第\s*\d+日\s+(\d{4})/\s*(\d{1,2})/\s*(\d{1,2})")
RE_HEAD = re.compile(r"^\s*(\d{1,2})R\s+(.*?)\s*H(\d{4})m\s+(\S+)\s+風\s+([^\d\s]+)\s*(\d+)m\s+波\s+(\d+)cm")
RE_ENTRY = re.compile(r"^\s+(\S{1,2})\s+([1-6])\s+(\d{4})\s(.+?)\s+(\d+)\s+(\d+)\s+(.*)$")
RE_TRI = re.compile(r"３連単\s+(\d-\d-\d)\s+(\d+)\s+人気\s+(\d+)")
KIMARITE = {"逃げ": "逃げ", "差し": "差し", "まくり": "まくり", "まくり差し": "まくり差し", "抜き": "抜き", "恵まれ": "恵まれ"}


def _norm(s: str) -> str:
    return unicodedata.normalize("NFKC", s).replace(" ", "").strip()


def parse_k(text: str) -> list[dict]:
    races = []
    jcd = date = None
    lines = text.replace("\r\n", "\n").split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        m = RE_VENUE.match(line)
        if m:
            jcd, date = m.group(1), None
            i += 1
            continue
        m = RE_DATE.search(line)
        if m and jcd:
            date = f"{m.group(1)}{int(m.group(2)):02d}{int(m.group(3)):02d}"
        m = RE_HEAD.match(line)
        if m and jcd and date:
            race = {
                "date": date, "jcd": jcd, "rno": int(m.group(1)),
                "fixed": "進入固定" in m.group(2), "distance": int(m.group(3)),
                "weather": _norm(m.group(4)), "wind_dir": _norm(m.group(5)), "wind_speed": int(m.group(6)),
                "wave": int(m.group(7)), "kimarite": "", "entries": [],
            }
            label = lines[i + 1] if i + 1 < len(lines) else ""
            if "ﾚｰｽﾀｲﾑ" in label:
                k = _norm(label.split("ﾚｰｽﾀｲﾑ", 1)[1])
                race["kimarite"] = KIMARITE.get(k, k)
            j = i + 3
            while j < len(lines):
                em = RE_ENTRY.match(lines[j])
                if not em:
                    break
                race["entries"].append(_entry(em))
                j += 1
            race["trifecta"] = race["trifecta_payout"] = race["trifecta_ninki"] = None
            for q in range(j, min(j + 16, len(lines))):
                tm = RE_TRI.search(lines[q])
                if tm:
                    race["trifecta"], race["trifecta_payout"], race["trifecta_ninki"] = tm.group(1), int(tm.group(2)), int(tm.group(3))
                    break
                if RE_HEAD.match(lines[q]):
                    break
            if len(race["entries"]) >= 2:
                races.append(race)
            i = j
            continue
        i += 1
    return races


def _entry(m) -> dict:
    code = m.group(1)
    rest = m.group(7).split()
    course = int(rest[1]) if len(rest) > 1 and rest[1].isdigit() else None
    ex = float(rest[0]) if rest and re.fullmatch(r"\d\.\d\d", rest[0]) else None
    st, flag = None, ""
    if len(rest) > 2:
        s = rest[2]
        if s.startswith("F"):
            flag = "F"
        elif s.startswith("L"):
            flag = "L"
        mm = re.search(r"\d*\.\d+", s)
        if mm and course is not None:
            st = float(mm.group())
    return {
        "place": int(code) if code.isdigit() else None,
        "code": "" if code.isdigit() else code,
        "frame": int(m.group(2)),
        "toban": m.group(3),
        "name": re.sub(r"[\s　]+", " ", m.group(4)).strip(),
        "course": course,
        "st": st,
        "st_flag": flag,
        "exhibit_time": ex,
    }
