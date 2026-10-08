"""レースごとのシェア画像（OGP・1200×630）。X などにレースのリンクを貼ったときに出る。

選手名は入れない（めずらしい字が出ないことがあるため）。艇番・本線・1着確率・見込みの強さだけ。
フォントは IPAexゴシック（scraper/fonts/、IPAフォントライセンスv1.0。ライセンス文を同梱）。
"""
from __future__ import annotations

import io
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT = Path(__file__).parent / "fonts" / "ipaexg.ttf"
W, H = 1200, 630
BG, INK, INK2, ACC, LINE = "#0B1116", "#FFFFFF", "#9FB0C2", "#FF6B35", "#24344A"
BOAT = {1: ("#FFFFFF", "#111111"), 2: ("#1B1B1B", "#FFFFFF"), 3: ("#D8342C", "#FFFFFF"),
        4: ("#1E5FBF", "#FFFFFF"), 5: ("#F2D231", "#111111"), 6: ("#2E9D4E", "#FFFFFF")}


@lru_cache(maxsize=16)
def font(size):
    return ImageFont.truetype(str(FONT), size)


def _boat(d, x, y, n, s):
    bg, fg = BOAT[n]
    d.rounded_rectangle((x, y, x + s, y + s), radius=s // 7, fill=bg, outline="#3A4A5E" if n == 2 else None, width=2)
    f = font(int(s * 0.7))
    tw = d.textlength(str(n), font=f)
    d.text((x + (s - tw) / 2, y + s * 0.13), str(n), font=f, fill=fg)


def _combo(d, x, y, combo, s):
    for i, n in enumerate(combo.split("-")):
        _boat(d, x, y, int(n), s)
        x += s
        if i < 2:
            d.text((x + 6, y + s * 0.18), "-", font=font(int(s * 0.5)), fill=INK2)
            x += 30
    return x


def race_image(venue: str, rno: int, date_label: str, deadline: str, grade: str,
               main: list[str], top: tuple[int, float] | None, conf: str) -> bytes:
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, W, 10), fill=ACC)
    d.text((64, 52), "艇ろぐ", font=font(40), fill=ACC)
    d.text((210, 64), "AIのボートレース予想", font=font(26), fill=INK2)
    d.text((64, 120), f"{venue} {rno}R", font=font(104), fill=INK)
    sub = "・".join(x for x in (date_label, f"締切 {deadline}" if deadline else "", grade) if x)
    d.text((70, 250), sub, font=font(32), fill=INK2)
    y = 320
    if main:
        d.text((64, y), "本線", font=font(34), fill=ACC)
        x = 170
        for c in main[:2]:
            x = _combo(d, x, y - 6, c, 58) + 48
    if top:
        d.text((64, y + 96), "1着の本命", font=font(34), fill=INK)
        _boat(d, 240, y + 88, top[0], 52)
        d.text((312, y + 96), f"AI予想 {top[1] * 100:.0f}%", font=font(34), fill=INK)
    if conf:
        f = font(30)
        tw = d.textlength(conf, font=f)
        d.rounded_rectangle((W - 64 - tw - 40, 64, W - 64, 116), radius=26, outline=ACC, width=3)
        d.text((W - 64 - tw - 20, 73), conf, font=f, fill=ACC)
    d.line((64, H - 92, W - 64, H - 92), fill=LINE, width=2)
    d.text((64, H - 70), "teilog.pages.dev", font=font(30), fill=INK)
    note = "予想は的中を保証しません ※20歳未満は購入できません"
    d.text((W - 64 - d.textlength(note, font=font(24)), H - 64), note, font=font(24), fill=INK2)
    buf = io.BytesIO()
    im.quantize(colors=64).save(buf, "PNG", optimize=True)
    return buf.getvalue()
