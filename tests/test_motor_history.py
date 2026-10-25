from scraper.motor import build


def race(date, rider="5327", rno=1, zero=False):
    entries = [[f, rider if f == 1 else str(4000 + f), f, 15, "", f,
                680 + f, ["B1", 5, 30, 5, 30, 0 if zero else 40],
                71 if f == 1 else f, f] for f in range(1, 7)]
    return [date, "03", rno, "逃げ", 0, 0, 0, 0, None, None, None, entries]


def test_history_keeps_old_periods_and_october_8_without_changing_model_inputs():
    rows = [race("20260511", rno=i, zero=True) for i in range(1, 5)]
    rows += [race("20260401"), race("20260525", "5082"),
             race("20261008"), race("20261016", "4925"), race("20261022", "4925")]
    m = build(rows, [])["03"]["71"]
    dates = [r["date"] for p in m["history"] for r in p["races"]]
    assert "20261008" in dates and "20260525" in dates
    assert "20260401" not in dates
    assert len(m["history"]) > 2 and len(m["meets"]) == 2
    assert m["history_n"] == m["n"] == 8
    assert m["history_first"] == "20260511"
    assert m["history_last"] == "20261022"
    assert m["history_boundary_source"] == "official_confirmed"
    assert m["history"][0]["from"] == "20261022"


def test_partial_motor_numbers_and_same_period_rider_change_are_preserved():
    a = race("20261008", rno=1)
    a[11][1][8] = None
    b = race("20261008", "4925", rno=5)
    m = build([b, a], [])["03"]["71"]
    assert m["history_n"] == 2
    assert [x["toban"] for x in m["history"]] == ["4925", "5327"]
    assert m["history_unknown_motor"] == 1
    assert m["history_boundary_source"] == "unknown"
    assert m["history_boundary"] is None


def test_new_generation_does_not_inherit_old_official_verification():
    rows = [race("20270511", rno=i, zero=True) for i in range(1, 5)]
    rows.append(race("20261008"))
    m = build(rows, [])["03"]["71"]
    assert m["history_boundary"] == "20270511"
    assert m["history_boundary_source"] == "zero_rate_inferred"
    assert "history_boundary_url" not in m


def test_display_denominator_excludes_non_responsible_incidents_but_keeps_f():
    rows = [race('20261008', rno=i) for i in range(1, 6)]
    for r, place in zip(rows, [1, 'S0', 'L0', 'K0', 'F']):
        r[11][0][5] = place
    m = build(rows, [])["03"]["71"]
    assert m['history_n'] == m['n'] == 5
    assert m['history_stats'] == {'n': 2, 'top2': 1, 'top3': 1}
