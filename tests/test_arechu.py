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
