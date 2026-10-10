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


def test_evening_lists_flyings_and_fits(tmp_path):
    import json
    from make_daily_x import build_evening
    day = tmp_path / "20261010"
    day.mkdir()
    for rno in range(1, 13):
        race = {"venue": "桐生", "rno": rno, "deadline": f"{10 + rno}:00",
                "racelist": {"boats": [{"frame": f, "name": f"選手 {rno}{f}"} for f in range(1, 7)]},
                "result": {"finished": True, "start": [{"frame": f, "flag": "F" if f <= 2 else ""} for f in range(1, 7)]}}
        (day / f"01{rno:02d}.json").write_text(json.dumps(race, ensure_ascii=False), encoding="utf-8")
    history = {"20261010": {"races": 150, "hits_main": 30, "best": [{"venue": "桐生", "rno": 1, "combo": "1-2-3", "payout": 9000}]}}
    date, text = build_evening({"date": "20261010"}, history, tmp_path)
    assert date == "2026-10-10" and x_len(text) <= 280
    assert "今日のフライング 24人" in text and "・桐生1R 選手 11" in text and "ほか" in text
    assert "150R中30的中" in text and "20歳未満は購入不可" in text and "必ず" not in text
    date, text = build_evening({"date": "20261011"}, history, tmp_path)
    assert "今日のフライングは0人でした" in text
