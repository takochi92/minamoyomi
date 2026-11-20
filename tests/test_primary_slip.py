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


def ai(r, p_in=0.30, head=4):
    """AIの1着確率：インは p_in、外は head がいちばん高い"""
    from itertools import permutations
    pw = {f: (p_in if f == 1 else 0.3 if f == head else 0.1) for f in range(1, 7)}
    r['prediction']['boats'] = [{'frame': f, 'course': f, 'p_win': pw[f]} for f in range(1, 7)]
    r['prediction']['p3'] = [pw[a] * pw[b] for a, b, c in permutations(range(1, 7), 3)]
    return r


def test_arechu_race_without_pick_keeps_the_standard_slip():
    """荒れ注意でも、インA1かつAIのイン40%未満でなければ本線・押さえのまま（総評は条件に使わない）"""
    for r in (ai(arechu_race(), p_in=0.45), ai(arechu_race(), p_in=0.40), arechu_race()):
        assert prepare(r, datetime(2026, 10, 10, 11, 55, tzinfo=JST), field({1: 'D'}))
        assert r['primary_slip']['kind'] == 'standard' and 'arechu_pick' not in r
    r = ai(arechu_race())
    r['racelist']['boats'][0]['class'] = 'A2'
    prepare(r, datetime(2026, 10, 10, 11, 55, tzinfo=JST), field({}))
    assert 'arechu_pick' not in r


def test_arechu_pick_when_an_a1_in_is_weak_for_the_ai():
    r = ai(arechu_race(), p_in=0.29)
    assert prepare(r, datetime(2026, 10, 10, 11, 55, tzinfo=JST), field({}))
    assert r['primary_slip']['source'] == 'arechu' and len(r['primary_slip']['tickets']) == 12
    assert r['arechu_pick'] == {'head': 4, 'reasons': [{'frame': 1, 'name': '', 'class': 'A1', 'p_win': 0.29, 'role': 'in'}]}
    # プレミアムの総評はあれば参考に付ける（別の節の評価は付けない）
    r = ai(arechu_race(), p_in=0.29)
    prepare(r, datetime(2026, 10, 10, 11, 55, tzinfo=JST), field({1: 'D'}))
    assert r['arechu_pick']['reasons'][0]['grade'] == 'D'
    r = ai(arechu_race(), p_in=0.29)
    prepare(r, datetime(2026, 10, 10, 11, 55, tzinfo=JST), field({1: 'D'}, title='前の節'))
    assert 'grade' not in r['arechu_pick']['reasons'][0]


def test_arechu_race_uses_ana_slip_and_counts_in_normal_totals():
    r = ai(arechu_race())
    assert prepare(r, datetime(2026, 10, 10, 11, 55, tzinfo=JST), field({}))
    s = r['primary_slip']
    assert s['kind'] == 'ana' and s['source'] == 'arechu' and len(s['tickets']) == 12
    assert all(t.startswith('4-') and len(set(t.split('-'))) == 3 for t in s['tickets'])
    assert '4-2-3' in s['tickets']
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
    r['prediction']['boats'][0]['p_win'] = 0.3          # インA1で40%未満 → 厳選
    assert prepare(r, datetime(2026, 10, 10, 11, 55, tzinfo=JST), field({}))
    s = r['primary_slip']
    assert s['source'] == 'arechu' and len(s['tickets']) == 12 and all(t.startswith('3-') for t in s['tickets'])
    assert s['tickets'][0] in ('3-1-2', '3-1-4', '3-1-5', '3-1-6')


def test_ledger_keeps_finished_picks(tmp_path):
    import json
    from scraper import arechu_pick
    r = ai(arechu_race())
    prepare(r, datetime(2026, 10, 10, 11, 55, tzinfo=JST), field({}))
    r.update({'venue': '鳴門', 'rno': 8, 'result': {'finished': True, 'trifecta': '4-2-3', 'trifecta_payout': 15000}})
    judge(r)
    (tmp_path / 'races' / '20261010').mkdir(parents=True)
    (tmp_path / 'races' / '20261010' / '1408.json').write_text(json.dumps(r, ensure_ascii=False), encoding='utf-8')
    book = arechu_pick.update_ledger(tmp_path, ['20261010', '20261009'])
    t = arechu_pick.totals(book)
    assert t == {'races': 1, 'hits': 1, 'invest': 1200, 'return': 15000, 'roi': 12.5, 'since': '20261010'}
    assert json.loads((tmp_path / 'arechu_pick.json').read_text(encoding='utf-8')) == book
