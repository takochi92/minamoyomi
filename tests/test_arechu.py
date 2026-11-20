from scraper import arechu


def boats(c1="A1", nat=(7.0, 4.0, 4.0, 4.0, 4.0, 4.0)):
    return [{"frame": i + 1, "class": c1 if i == 0 else "B1", "nat_win": n} for i, n in enumerate(nat)]


def test_only_a_class_first_boat():
    assert arechu.score(boats("B1")) is None
    assert arechu.score(boats()[:5]) is None
    assert arechu.score(boats("A2")) is not None


def test_closer_rivals_and_slow_exhibition_raise_score():
    strong = arechu.score(boats(nat=(8.0, 3, 3, 3, 3, 3)))
    close = arechu.score(boats(nat=(6.0, 5.5, 5.5, 5, 5, 5)))
    assert close > strong
    fast = arechu.score(boats(), {1: 6.70, 2: 6.75, 3: 6.75, 4: 6.75, 5: 6.75, 6: 6.75})
    slow = arechu.score(boats(), {1: 6.85, 2: 6.75, 3: 6.75, 4: 6.75, 5: 6.75, 6: 6.75})
    assert slow > fast
    assert 0 < strong < 1


def tokuyama10():
    """2026-11-19 徳山10R の形：外で全国勝率1位は2号艇、AIの1着確率は3号艇が外で1位"""
    from itertools import permutations
    nat = (6.0, 7.34, 6.94, 5.96, 7.16, 4.71)
    pw = (0.501, 0.140, 0.238, 0.058, 0.062, 0.002)
    return {"racelist": {"boats": [{"frame": f, "class": "A2", "nat_win": nat[f - 1]} for f in range(1, 7)]},
            "before": {"weather": {"wave_cm": 4, "wind_speed": 4},
                       "boats": [{"frame": f, "exhibit_time": t} for f, t in zip(range(1, 7), (6.94, 6.88, 6.82, 6.89, 6.88, 6.94))]},
            "prediction": {"boats": [{"frame": f, "course": f, "p_win": pw[f - 1]} for f in range(1, 7)],
                           "p3": [pw[a - 1] * pw[b - 1] * pw[c - 1] for a, b, c in permutations(range(1, 7), 3)]}}


def test_head_is_the_outer_boat_the_ai_likes_most():
    ar = arechu.from_race(tokuyama10())
    assert ar["head"] == 3 and ar["basis"] == "ai" and ar["p_win"] == 0.238
    assert len(ar["tickets"]) == 12 and all(t.startswith("3-") for t in ar["tickets"])
    assert ar["tickets"][0] == "3-1-2"                   # AIの確率の高い順
    assert "まくり40%" in ar["tenkai"]["kimarite"] and sum(len(g["tickets"]) for g in ar["tenkai"]["groups"]) == 12


def test_head_follows_the_course_after_entry_change():
    # 2号艇が1コースに入ったら、外は1号艇も含めて見る
    pred = {"boats": [{"frame": 1, "course": 2, "p_win": 0.3}, {"frame": 2, "course": 1, "p_win": 0.5},
                      {"frame": 3, "course": 3, "p_win": 0.2}]}
    assert arechu.head_of([], pred) == (1, "ai")
    tk = arechu.tenkai(1, [(1, 2, 3)], None, course=2)
    assert "1号艇は、2コースから差し59%" in tk["kimarite"]


def test_no_prediction_falls_back_to_the_old_scenario_table():
    r = tokuyama10()
    r["prediction"] = {}
    ar = arechu.from_race(r)
    assert ar["head"] == 2 and ar["basis"] == "nat_win" and ar["tickets"][0] == "2-1-3" and len(ar["tickets"]) == 12


def test_fixed_slip_is_what_the_block_shows():
    r = tokuyama10()
    r["primary_slip"] = {"policy": "single_slip_v1", "source": "arechu", "tickets": ["2-1-3", "2-1-4"]}
    ar = arechu.from_race(r)
    assert ar["head"] == 2 and ar["basis"] == "legacy" and ar["tickets"] == ["2-1-3", "2-1-4"]
