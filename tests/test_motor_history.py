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
    assert m["history_boundary_source"] == "official_confirmed"
    assert m["history_boundary"] == "20260511"


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


def test_live_renewal_hides_stale_history_until_same_number_is_rebuilt(tmp_path, monkeypatch):
    import json
    from scraper import motor_generation

    monkeypatch.setattr(motor_generation, "NOTICES", tmp_path / "notices.json")
    previous = {"03": {"date": "20260511", "source": "zero_rate_inferred"}}
    old = {"03": {"71": {"history_boundary": "20260511", "history_n": 99}}}
    cutoff = "20261101"
    cards = tmp_path / "races" / cutoff
    cards.mkdir(parents=True)
    index = tmp_path / "day-index"
    index.mkdir()
    (index / f"{cutoff}.json").write_text(json.dumps({
        "date": cutoff, "venues": [{"jcd": "03", "day": "11/1-11/5 初日"}],
    }), encoding="utf-8")
    pending = motor_generation.live_periods(tmp_path, cutoff, {"03": "20260511"})
    assert pending["pending"] == {"03": cutoff}
    assert not motor_generation.for_display(old, pending).get("03")

    for rno in range(1, 5):
        boats = [{"motor_no": i, "motor_2": 0} for i in range(71, 77)]
        (cards / f"03{rno:02d}.json").write_text(json.dumps({
            "date": cutoff, "jcd": "03", "rno": rno, "racelist": {"boats": boats},
        }), encoding="utf-8")
    ledger = motor_generation.live_periods(tmp_path, cutoff, {"03": "20260511"})
    assert ledger["venues"]["03"] == {"date": cutoff, "source": "zero_rate_inferred"}
    assert ledger["pending"] == {}
    assert not motor_generation.for_display(old, ledger).get("03")
    normal_rates = [{"motor_no": i, "motor_2": 10} for i in range(71, 77)]
    assert not motor_generation.for_race(old, "03", "20261102", normal_rates, ledger)
    assert motor_generation.for_race(old, "03", "20261031", normal_rates,
                                     {"venues": previous}) == old["03"]
    rebuilt = build([race("20261031"), race(cutoff)], [], ledger["venues"])
    assert rebuilt["03"]["71"]["history_n"] == 1
    assert rebuilt["03"]["71"]["history_first"] == cutoff
    assert motor_generation.for_display(rebuilt, ledger) == rebuilt


def test_published_official_date_applies_without_zero_rates(tmp_path, monkeypatch):
    import json
    from scraper import motor_generation

    notices = tmp_path / "official.json"
    notices.write_text(json.dumps({"03": {"date": "20261101", "url": "https://example.com"}}))
    monkeypatch.setattr(motor_generation, "NOTICES", notices)
    history = build([race("20261031"), race("20261102")], [])
    result = history["03"]["71"]
    assert result["history_n"] == 1
    assert result["history_boundary"] == "20261101"
    assert result["history_boundary_source"] == "official_confirmed"


def test_first_day_with_four_normal_cards_keeps_the_active_history(tmp_path, monkeypatch):
    import json
    from scraper import motor_generation

    monkeypatch.setattr(motor_generation, "NOTICES", tmp_path / "notices.json")
    cutoff = "20261101"
    cards = tmp_path / "races" / cutoff
    cards.mkdir(parents=True)
    for rno in range(1, 5):
        boats = [{"motor_no": i, "motor_2": 0 if i == 71 else 20} for i in range(71, 77)]
        (cards / f"03{rno:02d}.json").write_text(json.dumps({
            "date": cutoff, "jcd": "03", "rno": rno, "racelist": {"boats": boats},
        }), encoding="utf-8")
    ledger = motor_generation.live_periods(tmp_path, cutoff, {"03": "20260511"})
    assert ledger["venues"]["03"]["date"] == "20260511"
    assert ledger["pending"] == {}
