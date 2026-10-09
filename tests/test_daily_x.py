import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from make_daily_x import build, x_len  # noqa: E402


def test_daily_x_fits_and_keeps_notice():
    races = [{"rno": i, "deadline": f"1{i}:00", "confidence": "鉄板"} for i in range(1, 13)]
    venues = [{"name": f"場{i}", "grade": "SG" if i < 3 else "一般", "races": races} for i in range(24)]
    history = {"20261009": {"races": 143, "hits_main": 32,
                            "best": [{"venue": "常滑", "rno": 2, "combo": "5-3-4", "payout": 6480}]}}
    date, text = build({"date": "20261010", "venues": venues}, history)
    assert date == "2026-10-10"
    assert x_len(text) <= 280
    assert "20歳未満は購入不可" in text and "のめり込み" in text
    assert "143レース中 32的中" in text
    assert "必ず" not in text
