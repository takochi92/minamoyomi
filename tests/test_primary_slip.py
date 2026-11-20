from copy import deepcopy
from datetime import datetime
from scraper.primary_slip import standard_tickets, prepare, tickets, JST
from scraper.run import judge
from scraper.probability_view import explain, soft


def race():
    return {'date':'20261010','deadline':'12:00', 'prediction':{'stage':'直前','version':31,
            'bets':{'main':[{'combo':'1-2-3'}], 'sub':[{'combo':'1-2-3'},{'combo':'1-3-2'}]},
            'tsuke_pick':{'bets':['4-5-6','4-5-6','4-6-5']}},
            'tsuke':{'active':True,'final':True}}


def test_selected_ana_replaces_standard_and_settles_cost_and_hit():
    r = race()
    assert prepare(r,datetime(2026,10,10,11,55,tzinfo=JST))
    assert tickets(r) == ['4-5-6','4-6-5']
    r['result']={'finished':True,'trifecta':'4-5-6','trifecta_payout':2500}
    judge(r)
    assert r['hit'] and r['invest'] == 200 and r['return'] == 2500


def test_standard_winner_is_not_added_to_ana_after_result():
    r = race()
    prepare(r,datetime(2026,10,10,11,55,tzinfo=JST))
    saved = deepcopy(r['primary_slip'])
    r['result']={'finished':True,'trifecta':'1-2-3','trifecta_payout':800}
    assert not prepare(r,datetime(2026,10,10,12,1,tzinfo=JST))
    judge(r)
    assert not r['hit'] and r['return'] == 0 and r['primary_slip'] == saved


def test_inactive_ana_keeps_standard_and_old_history_stays_standard():
    r = race(); r['tsuke']['active'] = False
    prepare(r,datetime(2026,10,10,11,55,tzinfo=JST))
    assert tickets(r) == ['1-2-3','1-3-2']
    old = race()
    assert not prepare(old,datetime(2026,10,10,12,0,tzinfo=JST))
    old['result']={'finished':True,'trifecta':'4-5-6','trifecta_payout':2500}
    judge(old)
    assert not old['hit'] and 'primary_slip' not in old


def test_probability_steps_reconstruct_scores_and_include_opponent_changes():
    bs=[{'frame':i+1,'parts':{'場のコース別1着率':-i/2,'モーター':1 if i==3 else 0,'展示タイム':-.4 if i==1 else 0}} for i in range(6)]
    ex = explain(bs)
    expected = soft([sum(b['parts'].values()) for b in bs])
    for i,b in enumerate(bs):
        row = ex[str(b['frame'])]
        assert abs(row['baseline'] + sum(x['delta'] for x in row['changes']) - expected[i]) < 1e-12
    assert ex['4']['changes'][1]['delta'] > 0
    assert ex['1']['changes'][1]['delta'] < 0
    assert explain([{'frame':1}]) == {}


def arechu_race():
    r = race()
    r['jcd'] = '14'
    r['racelist'] = {'title': '一般戦', 'boats': [{'frame': f, 'class': 'A1' if f == 1 else 'B1', 'nat_win': 6.0 if f == 1 else 5.5 + (0.3 if f == 4 else 0),
                                               'motor_no': 10 + f, 'toban': str(4000 + f)} for f in range(1, 7)]}
    r['before'] = {'weather': {'wave_cm': 5, 'wind_speed': 4}, 'boats': [{'frame': f, 'exhibit_time': 6.95 if f == 1 else 6.75} for f in range(1, 7)]}
    r['tsuke']['active'] = False
    return r


def field(grades, title='一般戦', through='20261009'):
    """プレミアム評価（{場: field}）：grades={枠: 総評}"""
    return {'14': {'pairings': {str(10 + f): {str(4000 + f): {'overall': {'grade': g, 'title': title, 'through': through}}}
                                for f, g in grades.items()}}}


def test_arechu_race_without_pick_keeps_the_standard_slip():
    """荒れ注意でも、総評の条件に当てはまらなければ本線・押さえのまま"""
    for grades in ({}, {1: 'A', 4: 'B'}, {2: 'D'}):
        r = arechu_race()
        assert prepare(r, datetime(2026, 10, 10, 11, 55, tzinfo=JST), field(grades))
        assert r['primary_slip']['kind'] == 'standard' and 'arechu_pick' not in r
    # 別の節の評価は使わない
    r = arechu_race()
    prepare(r, datetime(2026, 10, 10, 11, 55, tzinfo=JST), field({1: 'D'}, title='前の節'))
    assert 'arechu_pick' not in r


def test_arechu_pick_when_the_in_is_weak_or_the_head_is_strong():
    for grades, roles in (({1: 'D'}, ['in']), ({4: 'S'}, ['head']), ({1: 'C', 4: 'A'}, ['in', 'head'])):
        r = arechu_race()
        assert prepare(r, datetime(2026, 10, 10, 11, 55, tzinfo=JST), field(grades))
        assert r['primary_slip']['source'] == 'arechu'
        assert [x['role'] for x in r['arechu_pick']['reasons']] == roles and r['arechu_pick']['head'] == 4


def test_arechu_race_uses_ana_slip_and_counts_in_normal_totals():
    r = arechu_race()
    assert prepare(r, datetime(2026, 10, 10, 11, 55, tzinfo=JST), field({1: 'D'}))
    s = r['primary_slip']
    assert s['kind'] == 'ana' and s['source'] == 'arechu' and len(s['tickets']) == 12
    assert all(t.startswith('4-') and len(set(t.split('-'))) == 3 for t in s['tickets'])
    r['result'] = {'finished': True, 'trifecta': '4-2-3', 'trifecta_payout': 15000}
    judge(r)
    assert r['hit'] and r['invest'] == 1200 and r['return'] == 15000
    assert r['hit_main'] and r['invest_main'] == 1200


def test_arechu_slip_follows_the_ai_head_and_is_rebuilt_before_the_deadline():
    """2026-11-19 徳山10R：頭は外の艇でAIの1着確率1位。前の決め方で固定した券は締切前なら作り直す"""
    from itertools import permutations
    r = arechu_race()
    pw = {1: 0.5, 2: 0.14, 3: 0.24, 4: 0.06, 5: 0.06, 6: 0.0}
    r['prediction']['boats'] = [{'frame': f, 'course': f, 'p_win': pw[f]} for f in range(1, 7)]
    r['prediction']['p3'] = [pw[a] * (7 - b) / 100 for a, b, c in permutations(range(1, 7), 3)]
    r['primary_slip'] = {'policy': 'single_slip_v1', 'source': 'arechu', 'tickets': ['4-1-2']}
    assert prepare(r, datetime(2026, 10, 10, 11, 55, tzinfo=JST), field({3: 'A'}))
    s = r['primary_slip']
    assert s['source'] == 'arechu' and len(s['tickets']) == 12 and all(t.startswith('3-') for t in s['tickets'])
    assert s['tickets'][0] in ('3-1-2', '3-1-4', '3-1-5', '3-1-6')


def test_ledger_keeps_finished_picks(tmp_path):
    import json
    from scraper import arechu_pick
    r = arechu_race()
    prepare(r, datetime(2026, 10, 10, 11, 55, tzinfo=JST), field({1: 'D'}))
    r.update({'venue': '鳴門', 'rno': 8, 'result': {'finished': True, 'trifecta': '4-2-3', 'trifecta_payout': 15000}})
    judge(r)
    (tmp_path / 'races' / '20261010').mkdir(parents=True)
    (tmp_path / 'races' / '20261010' / '1408.json').write_text(json.dumps(r, ensure_ascii=False), encoding='utf-8')
    book = arechu_pick.update_ledger(tmp_path, ['20261010', '20261009'])
    t = arechu_pick.totals(book)
    assert t == {'races': 1, 'hits': 1, 'invest': 1200, 'return': 15000, 'roi': 12.5, 'since': '20261010'}
    assert json.loads((tmp_path / 'arechu_pick.json').read_text(encoding='utf-8')) == book
