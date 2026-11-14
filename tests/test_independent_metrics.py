import json
import random
from collections import defaultdict

import pytest

from scraper import independent_metrics as im


def row(date, race, boat, motor, rider, seconds, metric="turn", venue="03", parts=()):
    return {"date": date, "venue": venue, "race": race, "boat": boat, "motor": motor, "rider": rider,
            "metric": metric, "source": "video", "seconds": seconds, "profile": "03-first-turn-v1", "parts": list(parts)}


def fleet(dates_by_meet, *, good_motor=7, rider_effect=None, seed=3, venue="03", first_motor=1):
    """Twelve motors, a new rider on each motor every meeting, two races a day."""
    rng = random.Random(seed)
    rows = []
    for meet, dates in enumerate(dates_by_meet):
        for d in dates:
            for race in (1, 2):
                for boat in range(1, 7):
                    motor = first_motor + (boat - 1) + 6 * (race - 1)
                    rider = f"{1000 + 100 * meet + motor}"
                    value = 6.0 + rng.gauss(0, .01) + (-.06 if motor == good_motor else 0)
                    value += (rider_effect or {}).get(rider, 0)
                    rows.append(row(d, race, boat, motor, rider, value, venue=venue))
    return rows


MEETS = [["20261001", "20261002", "20261003"], ["20261010", "20261011", "20261012"], ["20261020", "20261021", "20261022"]]


def test_robust_crossing_ignores_spray_frames_and_refuses_bad_tracks():
    clean = [(10 + i / 30, 100 + 9.0 * i) for i in range(16)]
    exact = im.robust_crossing(clean, 160, 1)
    assert abs(exact["seconds"] - (10 + (60 / 9) / 30)) < 1e-9 and exact["rejected"] == 0
    spray = list(clean)
    spray[5] = (spray[5][0], spray[5][1] + 60)               # one frame tracked on spray
    spray[11] = (spray[11][0], spray[11][1] - 45)
    fitted = im.robust_crossing(spray, 160, 1)
    assert fitted["rejected"] == 2 and abs(fitted["seconds"] - exact["seconds"]) < 1e-6
    assert im.robust_crossing(clean[:4], 160, 1) is None                     # too few frames
    assert im.robust_crossing(clean, 160, -1) is None                        # moving the other way
    assert im.robust_crossing(clean, 400, 1) is None                         # gate never reached
    rng = random.Random(1)
    assert im.robust_crossing([(t, x + rng.gauss(0, 30)) for t, x in clean], 160, 1) is None   # too noisy


def test_rows_need_a_complete_identity():
    good = row("20261001", 1, 1, 7, "4321", 6.01)
    assert im.clean_row(good)["seconds"] == 6.01
    for key, bad in (("venue", "25"), ("race", 13), ("boat", 0), ("motor", 0), ("rider", "12"), ("metric", "speed"),
                     ("seconds", float("nan")), ("seconds", 0), ("source", "guess"), ("profile", ""), ("date", "2026-10-01")):
        with pytest.raises(ValueError):
            im.clean_row({**good, key: bad})


def test_store_is_idempotent_and_keeps_valid_rows_when_some_are_invalid(tmp_path):
    store = im.Store(tmp_path / "private")
    rows = fleet(MEETS[:1])
    assert store.upsert(rows + [{"date": "bad"}]) == {"added": len(rows), "replaced": 0, "unchanged": 0, "invalid": 1}
    before = (tmp_path / "private" / "03" / "202610.jsonl").read_bytes()
    assert store.upsert(rows)["unchanged"] == len(rows)
    assert (tmp_path / "private" / "03" / "202610.jsonl").read_bytes() == before
    fixed = {**rows[0], "seconds": rows[0]["seconds"] + .2}
    assert store.upsert([fixed]) == {"added": 0, "replaced": 1, "unchanged": 0, "invalid": 0}
    assert len(store.rows()) == len(rows)
    assert len(store.rows(since="20261002", through="20261002")) == 12
    assert all(json.loads(line) for line in (tmp_path / "private" / "03" / "202610.jsonl").read_text().splitlines())


def test_values_are_compared_inside_one_race_only():
    rows = [row("20261001", 1, b, b, f"{1000 + b}", 6.0 + .01 * b) for b in range(1, 7)]
    rows += [row("20261001", 2, 1, 11, "2001", 9.0)]                                       # one boat measured: no comparison
    devs = im.race_deviations(rows)
    assert len(devs) == 6 and abs(sum(d["delta"] for d in devs)) < 1e-9
    assert min(devs, key=lambda d: d["delta"])["boat"] == 1


def test_good_motor_is_found_and_never_filled_without_enough_evidence():
    rows = fleet(MEETS)
    ratings = im.venue_ratings(rows, "03", "20261023", "20260901")
    turn = ratings["turn"]
    assert set(ratings) == {"turn"}                              # only the measured metric appears
    assert turn["7"]["grade"] in ("S", "A") and turn["7"]["riders"] == 3 and turn["7"]["meetings"] == 3
    assert turn["7"]["source"] == "video" and turn["7"]["rider_adjusted"] is True
    assert len(turn) == 12 and all(v["field"] == 12 for v in turn.values())
    assert im.venue_ratings(fleet(MEETS[:1]), "03", "20261004", "20260901") == {}         # one rider per motor
    assert im.venue_ratings(rows, "03", "20261023", None) == {}                            # unknown fleet start
    assert im.venue_ratings(rows, "04", "20261023", "20260901") == {}                      # another venue


def test_rider_is_subtracted_and_never_added():
    """Motor 3 always draws riders who are quick everywhere. Its rating must not benefit from them."""
    rows = fleet(MEETS)
    stars = {f"{1000 + 100 * meet + 3}" for meet in range(3)}
    flattered = fleet(MEETS, rider_effect={r: -.05 for r in stars})
    elsewhere = []                                               # the same riders at another venue, on ordinary motors
    for n in range(30):
        d = f"202609{1 + n % 28:02d}"
        for k, star in enumerate(sorted(stars)):                 # one of them per race, against average riders
            elsewhere += [row(d, 1 + k + 3 * (n // 28), boat, 40 + boat, star if boat == 1 else f"{9000 + boat}",
                              6.0 + (-.05 if boat == 1 else 0), venue="12") for boat in range(1, 7)]
    plain = im.venue_ratings(rows, "03", "20261023", "20260901")["turn"]
    naive = im.venue_ratings(flattered, "03", "20261023", "20260901", baselines={})["turn"]
    fair = im.venue_ratings(flattered, "03", "20261023", "20260901", all_rows=flattered + elsewhere)["turn"]
    assert naive["3"]["grade"] in ("S", "A")                     # without the adjustment the riders flatter motor 3
    assert fair["3"]["delta"] > naive["3"]["delta"] + .02        # the adjustment takes most of that away
    assert fair["7"]["grade"] in ("S", "A")                      # the genuinely good motor is still found
    assert abs(fair["3"]["delta"] - plain["3"]["delta"]) < .03


def test_old_fleet_with_the_same_motor_number_is_never_inherited():
    old = fleet([["20260801", "20260802", "20260803"], ["20260810", "20260811", "20260812"]], good_motor=2, seed=9)
    new = fleet(MEETS, good_motor=7)
    ratings = im.venue_ratings(old + new, "03", "20261023", "20260925")["turn"]
    assert ratings["7"]["grade"] in ("S", "A")
    assert ratings["2"]["grade"] not in ("S", "A") and ratings["2"]["through"] >= "20260925"
    assert all(v["meetings"] <= 3 and v["runs"] <= 18 for v in ratings.values())
    # the day the new motors arrive: nothing from the old fleet may be shown
    assert im.venue_ratings(old, "03", "20260925", "20260925") == {}
    assert im.venue_ratings(old + new, "03", "20261002", "20260925") == {}                # one meeting, one rider so far


def test_only_the_latest_three_finished_meetings_count():
    four = MEETS + [["20261101", "20261102", "20261103"]]
    rows = fleet(four)
    ratings = im.venue_ratings(rows, "03", "20261104", "20260901")["turn"]
    assert all(v["meetings"] == 3 and v["through"] >= "20261101" for v in ratings.values())
    schedule = [(m[0], m[-1]) for m in four[:3]] + [("20261101", "20261106")]             # the fourth is still running
    running = im.venue_ratings(rows, "03", "20261104", "20260901", schedule=schedule)["turn"]
    assert all(v["through"] <= "20261022" for v in running.values())


def test_parts_change_is_reported_with_the_rating():
    rows = fleet(MEETS)
    for r in rows:
        if r["motor"] == 5 and r["date"] == "20261011":
            r["parts"] = ["ピストン", "リング"]
    rating = im.venue_ratings(rows, "03", "20261023", "20260901")["turn"]
    assert rating["5"]["parts_changed"] == "20261011" and rating["5"]["runs_since_parts_change"] == 4
    assert rating["7"]["parts_changed"] is None and rating["7"]["runs_since_parts_change"] is None


def test_official_numbers_win_and_independent_fills_only_the_gaps():
    independent = im.by_motor(im.venue_ratings(fleet(MEETS), "03", "20261023", "20260901"))
    official = {"7": {"exhibition": {"grade": "B", "runs": 9}}, "8": {"turn": {"grade": "C", "runs": 8}}}
    cells = im.fill_columns(official, independent)
    assert cells["7"]["exhibition"]["source"] == "official" and cells["7"]["turn"]["source"] == "video"
    assert cells["8"]["turn"] == {"source": "official", "grade": "C", "runs": 8}           # not replaced by video
    assert "straight" not in cells["7"] and "acceleration" not in cells["7"]              # nothing invented


def test_carry_over_separates_a_motor_metric_from_a_rider_metric():
    motor_like = fleet(MEETS + [["20261101", "20261102", "20261103"]], seed=5)
    devs = im.race_deviations(motor_like)
    n, r = im.carry_over(devs, {"03": "20260901"}, min_previous=6, min_next=3)["turn"]
    assert n >= 12 and r > .5                                    # the good motor repeats under new riders
    rng = random.Random(8)
    noise = [{**x, "seconds": 6.0 + rng.gauss(0, .02)} for x in motor_like]
    assert abs(im.carry_over(im.race_deviations(noise), {"03": "20260901"})["turn"][1]) < .35
    assert im.carry_over(devs, {"03": "20261030"}).get("turn", (0, None))[0] < n         # old fleet is not used here either


def test_nightly_rating_skips_pending_or_unknown_fleets(tmp_path):
    from tools.independent_metrics import rate
    store = im.Store(tmp_path / "m")
    store.upsert(fleet(MEETS) + fleet(MEETS, venue="12", good_motor=3, seed=4))
    result = rate(store, "20261023", {"03": "20260901"}, {})                 # venue 12: fleet start unknown
    assert list(result["venues"]) == ["03"] and result["venues"]["03"]["period"] == "20260901"
    assert result["venues"]["03"]["motors"]["7"]["turn"]["grade"] in ("S", "A")
    assert rate(store, "20261023", {}, {})["venues"] == {}


def test_robust_crossing_survives_one_sided_spray():
    """Spray is always behind the boat. A fifth of the frames on spray must not move or void the result."""
    rng = random.Random(4)
    errors, missing = [], 0
    for _ in range(200):
        points = []
        for i in range(-12, 13):
            if rng.random() < .3:
                continue                                           # dropped frame
            x = 357 - 183 * i / 30
            points.append((268.2 + i / 30, x + (rng.uniform(8, 40) if rng.random() < .2 else rng.gauss(0, 3))))
        fitted = im.robust_crossing(points, 357, -1)
        if fitted is None:
            missing += 1
        else:
            errors.append(fitted["seconds"] - 268.2)
    assert missing <= 40                                           # at most a fifth is voided (13% here); the rest must be accurate
    assert abs(sum(errors) / len(errors)) < .004                   # no bias toward the spray side
    assert (sum(e * e for e in errors) / len(errors)) ** .5 < .012


def thin(rows, keep, seed):
    rng = random.Random(seed)
    return [r for r in rows if rng.random() < keep]


def test_partly_measured_races_still_find_the_good_motor():
    """Half of the runs are lost at random. Stacking the meetings must still rank the good motor on top."""
    meets = [[f"202610{d:02d}" for d in range(s, s + 7)] for s in (1, 10, 19)]
    rows = thin(fleet(meets), .5, seed=11)
    assert len(rows) < .56 * len(fleet(meets))
    ratings = im.venue_ratings(rows, "03", "20261026", "20260901")["turn"]
    assert len(ratings) >= 12 and ratings["7"]["grade"] in ("S", "A")
    assert min(ratings, key=lambda m: ratings[m]["delta"]) == "7"


def test_incomplete_race_does_not_punish_a_motor_for_its_company():
    """Motor 1 is average but is only ever measured together with the two quick motors."""
    rng = random.Random(2)
    speed = {m: (-.08 if m in (2, 3) else 0.0) for m in range(1, 13)}
    rows = []
    for n in range(12):
        d = f"202610{1 + n:02d}"
        full = [row(d, 1, b, 6 + b, f"{3000 + b}", 6.0 + speed[6 + b] + rng.gauss(0, .004)) for b in range(1, 7)]
        mixed = [row(d, 2, b, m, f"{4000 + m}", 6.0 + speed[m] + rng.gauss(0, .004))
                 for b, m in ((1, 1), (2, 2), (3, 3), (4, 4), (5, 5), (6, 6))]
        rows += full + (mixed if n % 3 == 0 else mixed[:3])       # usually only motors 1, 2, 3 are measured
    level = defaultdict(list)
    for d in im.race_deviations(rows):
        level[d["motor"]].append(d["delta"])
    mean = {m: sum(v) / len(v) for m, v in level.items()}
    assert abs(mean[1] - mean[4]) < .02                           # the same as other average motors
    assert mean[2] < mean[1] - .05 and mean[3] < mean[1] - .05
    naive = [r["seconds"] - sum(x["seconds"] for x in rows if (x["date"], x["race"]) == (r["date"], r["race"]))
             / sum(1 for x in rows if (x["date"], x["race"]) == (r["date"], r["race"])) for r in rows if r["motor"] == 1]
    assert sum(naive) / len(naive) > .03                          # a plain race mean would call motor 1 slow


def test_motor_measured_on_too_few_of_its_starts_is_not_rated():
    rows = fleet(MEETS)
    starts = {m: 18 for m in range(1, 13)}
    assert "5" in im.venue_ratings(rows, "03", "20261023", "20260901", starts=starts)["turn"]
    few = [r for r in rows if r["motor"] != 5 or r["date"] not in ("20261003", "20261012", "20261022")]   # 6 of its runs
    rated = im.venue_ratings(few, "03", "20261023", "20260901", starts=starts)
    assert "5" not in rated.get("turn", {})                       # 6 of 18 starts: a third
    assert im.venue_ratings(few, "03", "20261023", "20260901")["turn"]["5"]["share_of_starts"] is None
