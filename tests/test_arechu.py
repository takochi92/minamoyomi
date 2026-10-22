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


def test_ana_follows_scenario_table():
    head, combos = arechu.ana(boats(nat=(6.0, 5.0, 6.5, 5.5, 4.0, 4.5)))
    assert head == 3 and len(combos) == 12
    assert combos[0] == (3, 1, 5)                     # 3号艇頭は、1号艇が2着に残る形がいちばん多い
    assert all(c[0] == 3 and len(set(c)) == 3 for c in combos)
    tk = arechu.tenkai(head, combos, {3: 2})
    assert "まくり40%" in tk["kimarite"] and "2位" in tk["kimarite"]
    assert tk["groups"][0]["second"] == 1 and sum(len(g["tickets"]) for g in tk["groups"]) == 12


def tenkai_race(sts, ext=None, rows=None):
    return {"before": {"start_exhibition": [{"course": c, "frame": c, "st": sts[c - 1], "flag": ""} for c in range(1, 7)],
                       "boats": [{"frame": f, "exhibit_time": (ext or [6.8] * 6)[f - 1]} for f in range(1, 7)]},
            "oriten": {"items": ["一周", "まわり足", "直線"], "rows": rows or {str(f): [37.5, 5.5, 7.0] for f in range(1, 7)}}}


def test_head_follows_speed_of_boat():
    rows = {str(f): [37.5, 5.5, 7.0] for f in range(1, 7)}
    rows["4"] = [36.5, 5.0, 6.8]                                 # 4号艇だけ一周・まわり足・直線が速い
    r = tenkai_race([0.15] * 6, ext=[6.8, 6.8, 6.8, 6.7, 6.8, 6.8], rows=rows)
    t = arechu.head_by_tenkai(r)
    assert t["head"] == 4 and t["info"]["lap"] == 1 and t["info"]["ext"] == 1
    r2 = tenkai_race([0.20, 0.15, 0.14, 0.15, 0.16, 0.18])
    assert arechu.head_by_tenkai(r2)["head"] in (2, 3)         # 差がなければ、枠のくせで内側寄り


def test_head_none_without_start_exhibition():
    assert arechu.head_by_tenkai({"before": {}, "oriten": {}}) is None
