from datetime import datetime, timezone, timedelta

import pytest

from scraper.start_timing import StartIndex, capture, meeting_start
from tools.review_start_timing import examples


def race(date, st, venue="01", course=1, flag="", rno=1):
    return [date, venue, rno, "逃げ", None, 0, 0, 0, None, None, None,
            [[1, "4000", course, round(st * 100), flag, 1, 680]]]


def test_prior_day_only_and_duplicate_records():
    past = [race("20261020", .1), race("20261021", .2), race("20261022", .3)]
    idx = StartIndex(past + [past[0], race("20261025", .9), race("20261026", .9)], "20261025")
    value = idx.estimate("4000", "01", 1)
    assert value["n"] == 3
    assert value["st"] == pytest.approx(.2)
    assert value["sd"] == pytest.approx((2 * .1 ** 2 / 3) ** .5)


def test_local_shrinkage_and_separate_meeting_reference():
    rs = [race("20261020", .1), race("20261021", .1), race("20261022", .3, "02"), race("20261023", .3, "02")]
    idx = StartIndex(rs, "20261025")
    v = idx.estimate("4000", "01", 1, "20261019")
    assert v["course_mean"] == pytest.approx(.2)
    assert v["local_mean"] == pytest.approx(.1)
    assert v["st"] == pytest.approx((.2 + 25 * .2) / 27)
    assert v["meeting_mean"] == pytest.approx(.1)
    assert v["meeting_n"] == 2
    assert idx.estimate("4000", "01", 1, "20261025")["st"] == v["st"]


def test_f_l_missing_and_sparse_not_faked():
    rs = [race("20261020", .1), race("20261021", .2), race("20261022", .01, flag="F"), race("20261023", .9, flag="L")]
    assert StartIndex(rs, "20261025").estimate("4000", "01", 1) is None


def test_official_meeting_range_year_boundary_and_invalid():
    assert meeting_start("20270102", "12/30-1/4 4日目") == "20261230"
    assert meeting_start("20261025", "10/22-10/27 4日目") == "20261022"
    assert meeting_start("20261025", "10/1-10/6 最終日") is None
    assert meeting_start("20261025", "開催中") is None


def test_capture_deadline_guard_and_entry_by_course():
    tz = timezone(timedelta(hours=9))
    now = datetime(2026, 10, 25, 12, 0, tzinfo=tz)
    r = {"date": "20261025", "jcd": "01", "deadline": "12:01",
         "racelist": {"boats": [{"frame": 1, "toban": "4000"}]},
         "before": {"start_exhibition": [{"frame": f, "course": 7 - f} for f in range(1, 7)]}}
    idx = StartIndex([race(f"2026102{d}", .1, course=6) for d in range(1, 4)], "20261025")
    value = capture(r, {"day": "10/21-10/26 5日目"}, now, idx)
    assert value["boats"]["1"]["course"] == 6
    assert value["boats"]["1"]["entry_assumption"] == "exhibition"
    assert value["data_fingerprint"] == idx.fingerprint
    assert capture(r, {}, now + timedelta(minutes=1), idx) is None
    assert capture(r, {}, now + timedelta(days=1), idx) is None


def test_review_does_not_learn_current_day_or_future():
    rs = [race("20251201", .1), race("20251202", .2), race("20251203", .3),
          race("20251204", .4), race("20251204", .9, rno=2)]
    before = {(r[0], r[1], r[2]): {"entry": [1], "st": [.1]} for r in rs}
    rows = examples(rs, before)
    assert len(rows) == 2
    assert rows[0][7] == rows[1][7] == pytest.approx(.2)
    assert rows[0][8] == rows[1][8] == pytest.approx(.2)
    later = race("20251205", .99)
    assert examples(rs + [later], before)[:2] == rows


def test_update_keeps_research_capture_separate_and_freezes_after_deadline(monkeypatch):
    from scraper import run, start_timing, research_snapshot, primary_slip
    from scraper.predict import PRED_VERSION
    tz = timezone(timedelta(hours=9))
    class Clock(datetime):
        @classmethod
        def now(cls, zone=None):
            return cls(2026, 10, 25, 12, tzinfo=tz)
    monkeypatch.setattr(run, 'datetime', Clock)
    r = {'date': '20261025', 'jcd': '01', 'deadline': '23:00', 'rno': 1,
         'racelist': {'boats': []}, 'prediction': {'version': PRED_VERSION}}
    monkeypatch.setattr(run, '_load', lambda p: r)
    monkeypatch.setattr(run, '_save', lambda *args: None)
    monkeypatch.setattr(primary_slip, 'prepare', lambda *args: False)
    calls = []
    monkeypatch.setattr(research_snapshot, 'capture', lambda race, now, deadline: calls.append((now, deadline)) or False)
    monkeypatch.setattr(start_timing, 'capture', lambda race, venue, now: {'boats': {}, 'captured_at': now.isoformat()})
    venue = {'jcd': '01', 'name': '桐生'}
    run.process_race(object(), '20261025', venue, {'rno': 1, 'deadline': '23:00'}, Clock.now())
    saved = r['start_timing'].copy()
    assert calls and isinstance(calls[0][1], datetime)
    # At the deadline neither ST nor research input is recaptured.
    run.process_race(object(), '20261025', venue, {'rno': 1, 'deadline': '23:00'}, Clock(2026, 10, 25, 23, tzinfo=tz))
    assert r['start_timing'] == saved and len(calls) == 1
