import pytest
from scraper import season_watch as sw


def sources(events=()):
    return [{'year': 2026, 'category': c, 'events': list(events) if c == '01' else [],
             'source': 'https://www.boatrace.jp/test', 'checked_at': '2026-10-25'} for c in ('01', '02')]


def race(day='20261008', place=1, name='予選', rno=1):
    e = [1, '4001', 1, 15, 'F' if place == 'F' else '', place, 680, None, 71, 12, '確認 選手']
    return [day, '03', rno, '逃げ', '', 0, 0, 0, None, None, None, [e], {'race_name': name}]


@pytest.mark.parametrize('day,start,end,label', [
    ('20260101', '20251101', '20260430', '2026年後期'),
    ('20260430', '20251101', '20260430', '2026年後期'),
    ('20260501', '20260501', '20261031', '2027年前期'),
    ('20261031', '20260501', '20261031', '2027年前期'),
    ('20261101', '20261101', '20270430', '2027年後期')])
def test_review_period_is_not_class_application_period(day, start, end, label):
    assert sw.period(day) | {'from': start, 'through': end, 'label': label} == sw.period(day)


def test_calendar_grade_and_finals_points_and_non_responsible_exclusions():
    ev = {'from': '20261001', 'through': '20261031', 'jcd': '03', 'grade': 'SG'}
    rows = [race(place=1, name='優勝戦'), race(place=4, name='優勝戦', rno=2),
            race(place='S0', rno=3), race(place='K0', rno=4), race(place='L0', rno=5)]
    p = sw.aggregate(rows, sources([ev]), '20260501', '20261031')['4001']
    assert p['n'] == 2 and p['points'] == 13 + 8
    assert sw.aggregate([race(name='準優勝戦')], sources(), '20260501', '20261031')['4001']['points'] == 10
    assert sw.aggregate([race(name='優勝戦')], sources(), '20260501', '20261031')['4001']['points'] == 11


def test_repeated_f_points_reset_at_period_boundary_and_final_is_not_semifinal():
    rows = [race('20260430', 'F'), race('20260501', 'F'),
            race('20260502', 'F', '準優勝戦'), race('20260503', 'F', '優勝戦')]
    p = sw.aggregate(rows, sources(), '20260501', '20261031')['4001']
    assert p['accident_min'] == 20 + 30 + 50
    assert len(p['f']) == 3 and p['n'] == 3


def test_missing_calendar_and_mixed_programme_remain_unconfirmed():
    row = race()
    assert sw.aggregate([row], [], '20260501', '20261031')['4001']['unknown'] == 1
    events = [{'from': '20261001', 'through': '20261031', 'jcd': '03', 'grade': g} for g in ('SG', 'G2')]
    assert sw.race_grade(row, sources(events)) is None
    assert sw.aggregate([race(name='団体・優勝戦')], sources(), '20260501', '20261031')['4001']['unknown'] == 1


def test_provisional_quotas_require_starts_ratios_without_dropping_unknown_top_scorers():
    def p(win, n=100, unknown=0):
        return {'n': n, 'top2': 50, 'top3': 70, 'accident_min': 0, 'unknown': unknown, 'win': win}
    players = {'1': p(8), '2': p(7), '3': p(6, 80), '4': p(5.5), '5': p(9, 20), '6': p(9, unknown=1)}
    out = sw.provisional_borders(players, 10)
    assert out['A1']['win'] == 8 and out['A2']['win'] == 6
    assert out['A1']['quota'] == 2


def term(year, half, begin, end, grade):
    return {'id': f'{year}-{half}', 'year': year, 'half': half, 'from': begin, 'through': end,
            'source': 'https://www.boatrace.jp/official',
            'players': {'4001': {'name': '確認 選手', 'class': grade, 'win': 6.0}}}


def test_rollover_f0_requires_new_programme_and_future_grade_is_not_current():
    terms = [term(2026, 2, '20251101', '20260430', 'A1'), term(2027, 1, '20260501', '20261031', 'A2')]
    rows = [race('20261031', 'F'), race('20261101', 1)]
    old = {'4001': {'date': '20261031', 'jcd': '03', 'rno': 2, 'f': 0}}
    p = sw.build_report('20261102', rows, sources(), terms, old)
    assert p['players'][0]['class'] == 'A1'
    assert p['current_class_period'] == '2026-2'
    assert p['f_players'][0]['programme'] is None and not p['f_players'][0]['f0']
    old['4001']['date'] = '20261101'
    p = sw.build_report('20261102', rows, sources(), terms, old)
    assert p['f_players'][0]['f0'] and p['f_players'][0]['leave_status'] == 'unverified'
    rows[-1] = race('20261101', 'F')
    assert not sw.build_report('20261102', rows, sources(), terms, old)['f_players'][0]['f0']


def test_preparing_rollover_does_not_relabel_current_f0_as_next_period():
    p = sw.build_report('20261025', [race(place='F')], sources(), [],
                        {'4001': {'date': '20261025', 'jcd': '03', 'rno': 1, 'f': 0}})
    assert p['f_preparing'] and p['new_start'] == '20261101'
    assert p['f_players'][0]['programme'] is None


def test_calendar_rejects_wrong_heading_even_if_year_in_navigation():
    html = '<a>2026年</a><h3>2027年</h3>'
    with pytest.raises(ValueError, match='year'):
        sw.parse_calendar(html, 2026, '01')


def test_mixed_programme_does_not_publish_a_cut_line_from_incomplete_rankings():
    events = [{'from': '20261001', 'through': '20261031', 'jcd': '03', 'grade': g} for g in ('G1', 'G3')]
    p = sw.build_report('20261025', [race()], sources(events), [], {})
    assert p['grade_unresolved_races'] == 1
    assert p['borders']['A1']['win'] is None and p['borders']['A2']['win'] is None


def test_display_keeps_provisional_and_unserved_leave_limits_explicit():
    from scraper.season_views import render
    from scraper.sitegen import Page
    p = sw.build_report('20261025', [race(place='F')], sources(), [], {})
    p['players'][0]['name'] = '</script><script>alert(1)</script>'
    text = render(Page('database/season.html'), p)
    assert '公式確定ではありません' in text
    assert 'sw-sort' in text and '勝率の高い順' in text
    assert all(f'id="{name}"' in text for name in ('sw-mode','sw-remaining','sw-kind','sw-final'))
    assert 'season.js?v=' in text
    assert 'f-check' not in text and 'f_players' not in text and 'fl_leave' not in text
    import re, json
    payload = json.loads(re.search(r'<script id="sw-data" type="application/json">(.*?)</script>', text).group(1))
    assert not any('f' in row for row in payload['players'])
    assert '</script><script>alert(1)</script>' not in text
    assert '\\u003c/script>' in text


def test_missing_f_cell_is_never_verified_as_f0():
    from scraper import parse
    from tests import fixtures
    html = fixtures.racelist_html()
    good = parse.parse_racelist(html)['boats'][0]
    assert good['f_known'] is True
    bad = parse.parse_racelist(html.replace('F1', '不明'))['boats'][0]
    assert bad['f_known'] is False


def test_old_untagged_f0_snapshots_are_not_promoted(tmp_path, monkeypatch):
    import json
    monkeypatch.setattr(sw, 'ROOT', tmp_path)
    folder = tmp_path / 'site/data/races/20261101'
    folder.mkdir(parents=True)
    race_data = {'date': '20261101', 'jcd': '03', 'rno': 1, 'racelist': {'boats': [{'toban': '4001', 'f': 0}]}}
    path = folder / '0301.json'
    path.write_text(json.dumps(race_data), encoding='utf-8')
    assert not sw.programme_snapshots('20261101')
    race_data['racelist']['boats'][0]['f_known'] = True
    path.write_text(json.dumps(race_data), encoding='utf-8')
    assert sw.programme_snapshots('20261101')['4001']['f'] == 0


def test_official_cut_line_is_not_inferred_from_roster_minimum():
    known = term(2026, 2, '20251101', '20260430', 'A1')
    known['players']['4001']['win'] = 0
    p = sw.build_report('20261025', [race()], sources(), [known], {})
    assert p['borders']['A1']['previous_official'] == 6.27
    future = term(2027, 1, '20260501', '20261031', 'A1')
    p = sw.build_report('20261102', [race('20261101')], sources(), [known, future], {})
    assert p['borders']['A1']['previous_official'] is None
