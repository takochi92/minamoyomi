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


def test_daily_publish_accepts_races_that_can_never_finish(tmp_path):
    """3連単不成立・直前情報なし・結果の取得をあきらめたレースで、毎晩止まらないこと。"""
    import json
    import pytest
    from scraper.premium_motor import check_publish_inputs

    cutoff = "20261112"
    folder = tmp_path / cutoff
    folder.mkdir()
    rows = {(cutoff, "04", rno): {"result": {"finished": True}} for rno in range(1, 9)}
    raw = {
        9: {"result": {"finished": False, "trifecta": None, "order": [6, 4], "refunded": [1, 2, 3, 5]}},  # 集団フライング
        10: {"result": {"finished": True}, "before": None},      # 直前情報が取れず保存先に無い
        11: {"result": {"finished": False, "order": [], "refunded": []}, "result_tries": 12},  # 取得をあきらめた
        12: {"result": {"finished": False, "order": [], "refunded": []}, "result_tries": 3},   # まだ取得中
    }
    for rno in range(1, 13):
        (folder / f"04{rno:02}.json").write_text(json.dumps(raw.get(rno, {})), encoding="utf-8")
    with pytest.raises(ValueError, match="incomplete official archive.*04"):
        check_publish_inputs(rows, cutoff, date(2026, 11, 13), tmp_path)
    raw[12]["result_tries"] = 12
    (folder / "0412.json").write_text(json.dumps(raw[12]), encoding="utf-8")
    check_publish_inputs(rows, cutoff, date(2026, 11, 13), tmp_path)


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


def test_rider_baseline_weights_recent_terms_and_shrinks_small_samples():
    from scraper.premium_motor import rider_baselines
    profiles = {"terms": {
        "old": {"available_from": "20250501", "players": {"1000": {"n": 100, "dev_sum": 10.0}, "2000": {"n": 2, "dev_sum": -0.2}}},
        "new": {"available_from": "20260501", "players": {"1000": {"n": 100, "dev_sum": -10.0}}},
        "future": {"available_from": "20270101", "players": {"1000": {"n": 1000, "dev_sum": 500.0}}},
    }}
    base = rider_baselines(profiles, "20261112")
    assert base["1000"] < 0                                   # the newer term decides the sign
    assert abs(base["1000"] - (-10 + .5 * 10) / (150 + 8)) < 1e-12
    assert abs(base["2000"]) < .03                            # two runs barely move the value
    assert "1000" in rider_baselines(profiles, "20250601") and rider_baselines(profiles, "20250601")["1000"] > 0


def test_adjusted_rating_removes_the_rider_from_the_motor(monkeypatch):
    from scraper import premium_motor
    riders = {m: [f"{1000 + m}", f"{2000 + m}", f"{3000 + m}"] for m in range(1, 13)}
    quick = {riders[1][0], riders[1][1], riders[1][2]}       # motor 1 always gets riders who are .10s quick
    def observations(race, venue=None):
        for motor in range(1, 13):
            rider = riders[motor][race["meet"]]
            true_motor = -.04 if motor == 2 else 0.0          # motor 2 is the genuinely quick one
            yield "exhibition", str(motor), rider, true_motor + (-.10 if rider in quick else 0.0)
    monkeypatch.setattr(premium_motor, "observations", observations)
    records = {}
    for meet, start in enumerate((20261012, 20261020, 20261028)):
        for offset in range(3):
            d = str(start + offset)
            records[d, "04", 1] = {"racelist": {"title": f"meet{meet}"}, "meet": meet}
    history = {"04": {"1": {"history_boundary": "20260618"}}}
    profiles = {"terms": {"t": {"available_from": "20260501", "players": {r: {"n": 400, "dev_sum": -40.0} for r in quick}}}}
    plain = premium_motor.build(records, history, "20261105")["venues"]["04"]["motors"]
    assert "adjusted" not in plain["1"] and plain["1"]["exhibition"]["grade"] in "SA"
    out = premium_motor.build(records, history, "20261105", rider_profiles=profiles)["venues"]["04"]["motors"]
    assert out["2"]["adjusted"]["grade"] in "SA" and out["2"]["adjusted"]["riders"] == 3
    assert abs(out["1"]["adjusted"]["delta"]) < .01           # the quick riders no longer flatter motor 1
    assert plain["1"]["exhibition"]["delta"] < -.09
    assert out["1"]["adjusted"]["delta"] > out["2"]["adjusted"]["delta"]
    assert out["1"]["exhibition"] == plain["1"]["exhibition"]   # the existing ratings are untouched
