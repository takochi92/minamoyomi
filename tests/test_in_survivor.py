from scraper.in_survivor import COMBOS, decision, select
from tools.in_survivor_forward import review


def fixture_race():
    probabilities = [0.008277310924369747] * 119 + [0.015]
    prices = [50.0] * 120
    idx = COMBOS.index("1-3-5")
    probabilities[idx] = 0.015
    probabilities[-1] = 0.008277310924369747 if idx == 119 else probabilities[-1]
    if idx != 119:
        probabilities[0] += 1 - sum(probabilities)
    prices[idx] = 120.0
    return {"prediction": {"stage": "直前", "version": 31, "model_revision": "test",
                           "boats": [{"course": 1, "frame": 1, "p_win": .68},
                                     {"course": 3, "frame": 3, "p_win": .16}],
                           "course_stats": {"boats": {"1": {"starts": 40, "win": .70},
                                                       "3": {"starts": 30, "win": .20, "kimarite": {"まくり": 3}}}},
                           "p3": probabilities}, "odds_pre": {"v": prices}}


def test_inside_survivor_is_separate_and_fixed_from_saved_inputs():
    race = fixture_race()
    saved = decision(race)
    assert [x["combo"] for x in saved["tickets"]] == ["1-3-5"]
    assert saved["tickets"] == select(saved["evidence"], race["prediction"]["p3"], race["odds_pre"]["v"])
    race["prediction"]["course_stats"]["boats"]["3"]["win"] = .10
    assert decision(race)["tickets"] == []


def test_old_records_are_not_promoted_to_forward_performance():
    race = fixture_race()
    row = {"date": "20261009", "jcd": "01", "rno": 1,
           "prediction": race["prediction"], "odds_pre": race["odds_pre"],
           "result": {"finished": True, "trifecta": "1-3-5", "trifecta_payout": 12000, "refunded": []}}
    report = review([row])
    assert report["shadow"]["races"] == 0
    assert report["shadow"]["gross_roi"] is None
