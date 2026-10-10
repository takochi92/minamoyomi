from copy import deepcopy
from datetime import datetime
from scraper.primary_slip import prepare, tickets, JST
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
