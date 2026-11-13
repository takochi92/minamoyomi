from scraper.premium_motor import profile, rank_field, observations
from datetime import date

def test_standout_needs_repeat_observations_with_multiple_riders():
    base = date(2026, 11, 9)
    rows = [(base.replace(day=3+i), "one", "r1", -.1) for i in range(3)]
    rows += [(base.replace(day=6+i), "two", "r2", -.1) for i in range(3)]
    middle = {str(i): ({"delta":0}, []) for i in range(20)}
    result = rank_field({**middle, "fast":profile(rows, base)}, .03)
    assert result["fast"]["grade"] == "S"
    same = [(day, meet, "r1", delta) for day, meet, _, delta in rows]
    assert rank_field({**middle, "fast":profile(same, base)}, .03)["fast"]["grade"] == "A"
    incidental = [(*row[:2], "r2" if i == 5 else "r1", row[3]) for i, row in enumerate(rows)]
    assert rank_field({**middle, "fast":profile(incidental, base)}, .03)["fast"]["grade"] == "A"
    assert profile(rows[:5], base) is None
    assert rank_field({"fast":profile(rows, base)}, .03) == {}


def test_reject_incomplete_six_boat_measurement():
    boats = [{"frame":i,"motor_no":i,"toban":str(i+1000)} for i in range(1,7)]
    times = [{"frame":i,"exhibit_time":6.7} for i in range(1,6)]
    assert not list(observations({"racelist":{"boats":boats},"before":{"boats":times}}))
    times.append({"frame":6,"exhibit_time":6.58})
    observed = list(observations({"racelist":{"boats":boats},"before":{"boats":times}}))
    assert len(observed) == 6
    assert abs(sum(value for _, _, _, value in observed)) < 1e-10
    assert observed[-1][-1] < 0


def test_daily_publish_rejects_partial_archive(tmp_path):
    import pytest
    from scraper.premium_motor import check_publish_inputs

    cutoff = "20261112"
    folder = tmp_path / cutoff
    folder.mkdir()
    for rno in range(1, 13):
        (folder / f"04{rno:02}.json").touch()
    rows = {(cutoff, "04", rno): {"result": {"finished": True}} for rno in range(1, 3)}
    with pytest.raises(ValueError, match="incomplete official archive.*04"):
        check_publish_inputs(rows, cutoff, date(2026, 11, 13), tmp_path)
    rows.update({(cutoff, "04", rno): {"result": {"finished": True}} for rno in range(3, 12)})
    check_publish_inputs(rows, cutoff, date(2026, 11, 13), tmp_path)
    with pytest.raises(ValueError, match="stale"):
        check_publish_inputs(rows, cutoff, date(2026, 11, 16), tmp_path)


def test_publish_retries_transient_errors_and_rejects_redirects():
    import io
    import pytest
    from urllib.error import HTTPError
    from scraper.premium_motor import publish_snapshot

    failures = iter([503, 429, None])
    sleeps = []
    def opener(req, timeout):
        status = next(failures)
        if status:
            raise HTTPError(req.full_url, status, "simulated", {}, None)
        return io.BytesIO(b'{"stored":true}')

    url = "https://example.supabase.co/functions/v1/premium"
    publish_snapshot("{}", url, "a" * 64, opener, sleeps.append)
    assert sleeps == [1, 2]
    def redirect(req, timeout):
        raise HTTPError(req.full_url, 307, "redirect", {}, None)
    with pytest.raises(RuntimeError, match="HTTP 307"):
        publish_snapshot("{}", url, "a" * 64, redirect)
    with pytest.raises(ValueError, match="invalid premium function URL"):
        publish_snapshot("{}", "https://elsewhere.example/a.supabase.co/functions/v1/premium", "a" * 64, opener)


def test_pairing_requires_same_meeting_and_multiple_dates(monkeypatch):
    from scraper import premium_motor

    def observations(race, venue):
        for motor in range(1, 13):
            yield "turn", str(motor), "1234", -motor / 100

    monkeypatch.setattr(premium_motor, "observations", observations)
    one_day = [("20261111", "Test", {})] * 3
    assert premium_motor.pairing_ratings([one_day], "04") == {}
    two_days = one_day[:2] + [("20261112", "Test", {})]
    ratings = premium_motor.pairing_ratings([two_days], "04")
    top = ratings["12"]["1234"]["turn"]
    assert top["grade"] == "A"
    assert top["runs"] == 3 and top["through"] == "20261112"
    assert top["title"] == "Test"
    next_meeting = [("20261114", "Test", {})]
    assert premium_motor.pairing_ratings([two_days, next_meeting], "04") == {}
