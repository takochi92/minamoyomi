from copy import deepcopy
from scraper.ana_evaluation import shadow_decision,COMBOS
from scraper.prediction_context import evidence
from tools.forward_ana_review import review,shadow_audit
from test_research_review import verified_row


def race_for_shadow():
    return {'prediction':{'version':31,'stage':'直前','model_revision':'fixed-test',
        'entry':[1,2,3,4,5,6],'boats':[{'frame':4,'course':4,'parts':{'乗り手補正の機力展示':.1}}],
        'p3':[1/120]*120},'odds_pre':{'v':[200.]*120}}


def test_shadow_selects_only_supported_outer_and_does_not_use_result():
    r=race_for_shadow();r['prediction']['p3']=[.01]*80+[.005]*40
    s=shadow_decision(r);assert len(s['tickets'])==4
    assert all(t['combo'].startswith('4-') for t in s['tickets'])
    assert r['prediction'].get('bets') is None
    r['result']={'trifecta':'1-2-3','trifecta_payout':999999}
    assert shadow_decision(r)==s
    r['prediction']['boats'][0]['course']=1
    assert not shadow_decision(r)['tickets']


def test_shadow_excludes_incomplete_or_unfingerprinted_inputs():
    r=race_for_shadow();assert not shadow_decision(r)['tickets'] # .0083 < .01
    r['prediction']['p3']=[.01]*80+[.005]*40
    r['odds_pre']['v'][0]=None
    assert not shadow_decision(r)['tickets']
    r['odds_pre']['v'][0]=200.;r['prediction']['model_revision']=None
    assert not shadow_decision(r)['tickets']


def test_shadow_ledger_preserves_fixed_tickets_and_legacy_exclusion():
    r=race_for_shadow();r['prediction']['p3']=[.01]*80+[.005]*40
    row=verified_row();row['odds_pre']=r['odds_pre'];row['decision'].update(model_revision='fixed-test',model_version=31,entry=[1,2,3,4,5,6],p3=r['prediction']['p3'],ana_shadow=shadow_decision(r))
    assert not shadow_audit(row)
    ticket=row['decision']['ana_shadow']['tickets'][0]['combo'];row['result']['trifecta']=ticket
    out=review([row]);assert out['shadow']['races']==1 and out['shadow']['payout']==1000
    row['decision']['ana_shadow']['tickets'][0]['combo']='1-2-3'
    assert 'fixed_shadow_tickets_mismatch' in shadow_audit(row)
    old=verified_row();assert review([old])['shadow']['races']==0
    old['provenance']='legacy_unverified';assert review([old])['baseline_all']['races']==0


def test_evidence_handles_missing_exhibition_and_100_race_gate():
    boats=[{'frame':f,'toban':str(f),'motor_no':f} for f in range(1,7)]
    refs={str(f):{'n':99,'top1':1,'dev_sum':0.} for f in range(1,7)}
    before={'boats':[{'frame':f,'exhibit_time':6.5+f/100} for f in range(1,7)]}
    x=evidence(boats,before,refs,{},'20261010');assert not x['1']['personal_ready']
    refs['1']['n']=100;x=evidence(boats,before,refs,{},'20261010')
    assert x['1']['personal_change_seconds']==-.025
    assert not evidence(boats,None,refs,{},'20261010')['1']['personal_ready']
