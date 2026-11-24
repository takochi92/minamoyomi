from datetime import datetime

from tools import boatcast_nightly as bn


def test_blank_venues_go_first_then_by_number():
    assert bn.order({"24", "04", "13", "03", "02"}) == ["03", "13", "02", "04", "24"]


def test_stop_time_is_the_next_morning():
    start = datetime(2026, 11, 15, 23, 19, tzinfo=bn.JST)
    assert bn.deadline(start, "0630") == datetime(2026, 11, 16, 6, 30, tzinfo=bn.JST)
    early = datetime(2026, 11, 16, 1, 0, tzinfo=bn.JST)
    assert bn.deadline(early, "0630") == datetime(2026, 11, 16, 6, 30, tzinfo=bn.JST)
