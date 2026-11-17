from scraper.premium_coverage import coverage, markdown


def test_counts_motors_per_venue_and_item_without_grades():
    snap = {'through': '20261116', 'venues': {
        '12': {'motors': {'1': {'exhibition': {'grade': 'A'}, 'straight': {'grade': 'B', 'source': 'lap_minus_turn'}},
                          '2': {'exhibition': {'grade': 'C'}}},
               'pairings': {'1': {'4001': {'turn': {'grade': 'A'}, 'overall': {'grade': 'B'}}}}}}}
    report = coverage(snap)
    row = report['venues']['12']
    assert row['motors'] == 2 and row['exhibition']['motors'] == 2
    assert row['straight'] == {'motors': 1, 'source': '算'}
    assert row['turn']['motors'] == 1 and row['acceleration']['motors'] == 0
    assert report['venues']['03']['motors'] == 0 and report['filled']['exhibition'] == 1
    text = markdown(report)
    assert '| 12 住之江 | 2 | 2 | 1算 | 1 | — | 1 |' in text and 'grade' not in text and ' A ' not in text
