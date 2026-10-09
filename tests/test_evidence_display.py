from copy import deepcopy
from scraper.sitegen import Site,Page


def test_old_prediction_display_uses_saved_facts_without_backfilling():
    p={'boats':[{'frame':3,'course':3,'name':'<選手>','p_win':.1}],
       'research_signals':[{'frame':3,'facts':['本人比：普段の展示1位率5% → 今回は単独1位']}],
       'bets':{'ana_reason':'<根拠>'}}
    race={'jcd':'01','racelist':{'boats':[{'frame':3,'motor_no':7}]}}
    original=deepcopy(p)
    result=Site.evidence_block(Page('race/20261010/kiryu-1.html'),race,p)
    assert p==original and '本人参照の数値は未保存' in result
    assert '今回は単独1位' in result and '&lt;根拠&gt;' in result and '<根拠>' not in result
    assert 'href="../../venue/kiryu-motor.html#m7"' in result


def test_evidence_neutral_motor_is_not_displayed_as_strong():
    p={'boats':[{'frame':1,'course':1,'name':'選手','p_win':.5}],
       'evidence':{'1':{'motor_ready':False,'motor_ex_seconds':None,'personal_ready':False,'reference_n':99}}}
    race={'jcd':'01','racelist':{'boats':[{'frame':1,'motor_no':1}]}}
    result=Site.evidence_block(Page('index.html'),race,p)
    assert '補正機力は中立' in result and '本人比は中立' in result
    assert '穴の購入根拠を満たす買い目がありません' in result
