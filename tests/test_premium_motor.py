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
