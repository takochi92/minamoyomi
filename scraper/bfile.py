"""公式「番組表」テキスト（Bファイル）のパーサ。各艇の級別・全国/当地勝率・モーター/ボート2連率。"""
from __future__ import annotations

import re
import unicodedata

RE_VENUE = re.compile(r"^(\d{2})BBGN")
RE_RACE = re.compile(r"^\s*(\d{1,2})R\s.*H\d{4}m")
RE_BOAT = re.compile(r"^([1-6]) (\d{4})(.{4})(\d{2})(.{2})(\d{2})(A1|A2|B1|B2)(.*)$")
RE_NUMS = re.compile(r"(\d+\.\d{2})\s+(\d+\.\d{2})\s+(\d+\.\d{2})\s+(\d+\.\d{2})\s+(\d+)\s+(\d+\.\d{2})\s*(\d+)\s+(\d+\.\d{2})")


def parse_b(text: str) -> dict:
    """{(jcd, rno, frame): [class, nat_win, nat_2, loc_win, loc_2, motor_2, boat_2, age, weight]}"""
    out = {}
    jcd = rno = None
    for line in text.replace("\r\n", "\n").split("\n"):
        m = RE_VENUE.match(line)
        if m:
            jcd, rno = m.group(1), None
            continue
        m = RE_RACE.match(unicodedata.normalize("NFKC", line))
        if m:
            rno = int(m.group(1))
            continue
        m = RE_BOAT.match(line)
        if m and jcd and rno:
            q = RE_NUMS.search(m.group(8))
            if q:
                out[(jcd, rno, int(m.group(1)))] = [m.group(7), float(q.group(1)), float(q.group(2)), float(q.group(3)),
                                                    float(q.group(4)), float(q.group(6)), float(q.group(8)), int(m.group(4)), int(m.group(6))]
    return out
