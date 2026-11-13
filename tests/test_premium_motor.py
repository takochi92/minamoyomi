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
    rows[cutoff, "04", 12] = {"result": {"cancelled": True}}
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
            yield "overall", str(motor), "1234", -motor / 100

    monkeypatch.setattr(premium_motor, "observations", observations)
    one_day = [("20261111", "Test", {})] * 3
    assert premium_motor.pairing_ratings([one_day], "04") == {}
    two_days = one_day[:2] + [("20261112", "Test", {})]
    ratings = premium_motor.pairing_ratings([two_days], "04")
    top = ratings["12"]["1234"]["turn"]
    assert top["grade"] == "A"
    assert top["runs"] == 3 and top["through"] == "20261112"
    assert top["title"] == "Test"
    assert ratings["12"]["1234"]["overall"]["grade"] == "A"
    assert premium_motor.pairing_ratings([two_days], "22")["12"]["1234"]["overall"]["grade"] == "A"
    grades = {r["1234"]["turn"]["grade"] for r in premium_motor.pairing_ratings([two_days], "09").values()}
    assert grades == {"A", "B", "D"}
    next_meeting = [("20261114", "Test", {})]
    assert premium_motor.pairing_ratings([two_days, next_meeting], "04") == {}

def test_overall_uses_only_three_official_intervals():
    from scraper.premium_motor import observations

    boats = [{"frame": i, "motor_no": i, "toban": str(1000 + i)} for i in range(1, 7)]
    before = [{"frame": i, "exhibit_time": 6 + i / 100} for i in range(1, 7)]
    rows = {str(i): [5 + i / 100, 7 + i / 100] for i in range(1, 7)}
    race = {"racelist": {"boats": boats}, "before": {"boats": before},
            "oriten": {"items": ["まわり足", "直線"], "rows": rows}}
    overall = [v for k, _, _, v in observations(race, "22") if k == "overall"]
    assert overall == sorted(overall) and overall[0] == -.5 and overall[-1] == .5
    assert not any(k == "acceleration" for k, *_ in observations(race, "03"))
    assert any(k == "acceleration" for k, *_ in observations(race, "14"))
    race["oriten"] = {"items": ["まわり足"], "rows": {key: value[:1] for key, value in rows.items()}}
    assert any(k == "overall" for k, *_ in observations(race, "13"))
    assert not any(k == "overall" for k, *_ in observations(race, "22"))
    race["oriten"] = {"items": ["まわり足", "直線"], "rows": rows}
    rows["6"][0] = None
    assert not any(k == "overall" for k, *_ in observations(race, "22"))


def test_daily_publish_rejects_entire_missing_scheduled_venue(tmp_path):
    import json
    import pytest
    from scraper.premium_motor import check_publish_inputs

    cutoff = "20261112"
    races_dir = tmp_path / "races"
    (races_dir / cutoff).mkdir(parents=True)
    index = tmp_path / "day-index"
    index.mkdir()
    (index / f"{cutoff}.json").write_text(json.dumps({"date": cutoff, "venues": [
        {"jcd": "04"}, {"jcd": "07"}, {"jcd": "22", "cancelled": True},
    ]}), encoding="utf-8")
    rows = {}
    for rno in range(1, 13):
        (races_dir / cutoff / f"04{rno:02d}.json").touch()
        rows[cutoff, "04", rno] = {"result": {"finished": True}}
    with pytest.raises(ValueError, match="incomplete official archive.*07"):
        check_publish_inputs(rows, cutoff, date(2026, 11, 13), races_dir)


def test_official_cancellation_is_terminal_but_not_a_timing_sample(tmp_path):
    import json
    from scraper.parse import parse_result
    from scraper.research_snapshot import archive, archived_records

    result = parse_result("<h3>レース中止</h3>")
    assert result["cancelled"] is True and result["finished"] is False
    folder = tmp_path / "site" / "data" / "races" / "20261112"
    folder.mkdir(parents=True)
    (folder / "0401.json").write_text(json.dumps({
        "date": "20261112", "jcd": "04", "rno": 1, "result": result,
    }), encoding="utf-8")
    assert archive(tmp_path, ["20261112"])["added_or_updated"] == 1
    assert archived_records(tmp_path)["20261112", "04", 1]["result"]["cancelled"] is True
    assert archive(tmp_path, ["20261112"])["added_or_updated"] == 0
