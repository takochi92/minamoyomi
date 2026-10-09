from copy import deepcopy
from datetime import datetime,timedelta

from scraper.research_ledger import audit,settle,summarize
from scraper.research_snapshot import JST,capture,mark_fetched,archive,archived_records
from tools.research_review import standardized,completed_source
from tools.motor_research import analyze
from test_player_research import race
from test_exhibition_research import sample


def verified_row():
    r=sample();result=r.pop('result');result.update(trifecta='1-2-3',trifecta_payout=1000,refunded=[])
    r['prediction']={'version':'test','stage':'直前','bets':{'main':[{'combo':'1-2-3'}],'sub':[{'combo':'4-5-6'}]}}
    r['odds_pre']={'v':[100.]*120}
    dl=datetime(2026,10,1,12,tzinfo=JST);at=dl-timedelta(seconds=10)
    for f in ('racelist','before','prediction','odds_pre'):mark_fetched(r,f,at)
    assert capture(r,at,dl)
    snap=r['research_snapshot']
    return {**snap['inputs'],'decision':snap['decision'],'captured_at':snap['captured_at'],
            'deadline_at':snap['deadline_at'],'fetched_at':snap['fetched_at'],
            'provenance':'timestamped_pre_deadline','result':result}


def test_settlement_refunds_only_official_refund_boats():
    tickets=[{'combo':'1-2-3','amount':100},{'combo':'4-5-6','amount':100}]
    res={'finished':True,'refunded':['6'],'trifecta':'1-2-3','trifecta_payout':1000}
    assert settle(tickets,res)=={'status':'settled','invested':200,'refund':100,'payout':1000.,'hit':True}
    res['refunded']=[];res['order']=[{'frame':6,'place':'転'}]
    assert settle(tickets,res)['refund']==0
    assert settle(tickets,{'finished':True})['status']=='unsettled'
    assert settle(tickets,{'finished':True,'refunded':['1','4']})['refund']==200


def test_audit_requires_pre_deadline_and_fresh_complete_odds():
    row=verified_row();assert audit(row)==[]
    stale=deepcopy(row);stale['fetched_at']['odds_pre']='2026-10-01T11:50:00+09:00'
    assert 'stale_odds' in audit(stale)
    post=deepcopy(row);post['captured_at']=post['deadline_at']
    assert 'invalid_capture_time' in audit(post)
    wrong=deepcopy(row);wrong['deadline_at']='2026-10-01T12:30:00+09:00'
    assert 'deadline_mismatch' in audit(wrong)
    old=deepcopy(row);old['fetched_at']['prediction']='2026-10-01T11:00:00+09:00'
    assert 'prediction_older_than_exhibition' in audit(old)
    row['odds_pre']['v'][0]=None
    assert 'incomplete_odds' in audit(row)


def test_summary_does_not_upgrade_legacy_and_reports_both_roi():
    row=verified_row();row['result']['refunded']=['6']
    d=summarize([row]);assert d['gross_roi']==5.5 and d['net_roi']==10.0
    assert d['by_model_and_month'][0]['model_version']=='test'
    assert d['by_model_and_month'][0]['month']=='202610'
    wrong=deepcopy(row);wrong['decision']['stage']='事前'
    assert 'missing_exhibition_model_decision' in audit(wrong)
    legacy=deepcopy(row);legacy['provenance']='legacy_unverified'
    d=summarize([legacy]);assert d['races']==0 and d['gross_roi'] is None


def test_snapshot_preserves_fixed_decisions_and_invalid_time_is_legacy(tmp_path):
    import json
    row=verified_row();r=sample();r['research_snapshot']={'schema':2,'captured_at':row['captured_at'],'deadline_at':row['deadline_at'],
                  'fetched_at':row['fetched_at'],'inputs':{k:row[k] for k in ('date','jcd','rno','deadline','before','odds_pre','racelist')},'decision':deepcopy(row['decision'])}
    p=tmp_path/'site/data/races/20261001/0101.json';p.parent.mkdir(parents=True);p.write_text(json.dumps(r))
    archive(tmp_path);saved=list(archived_records(tmp_path).values())[0]
    assert saved['decision']==row['decision'] and saved['fetched_at']==row['fetched_at']
    r['research_snapshot']['decision']['tickets']=[];p.write_text(json.dumps(r));archive(tmp_path)
    assert list(archived_records(tmp_path).values())[0]['decision']==row['decision']
    r['rno']=2;r['research_snapshot']['captured_at']='bad';p=p.with_name('0102.json');p.write_text(json.dumps(r));archive(tmp_path)
    assert next(v for v in archived_records(tmp_path).values() if v['rno']==2)['provenance']=='legacy_unverified'


def test_standardization_adjusts_composition_and_exposes_coverage():
    # 生率では対象群が低いが、各区分内は同率。構成調整で差0。
    cells={('low',):[{'n':90,'win':9,'top3':45},{'n':10,'win':1,'top3':5}],
           ('high',):[{'n':10,'win':9,'top3':10},{'n':90,'win':81,'top3':90}],
           ('unsupported',):[{'n':20,'win':10,'top3':15},{'n':1,'win':1,'top3':1}]}
    d=standardized(cells);assert abs(d['win_rate_difference'])<1e-10
    assert d['matched_treatment_n']==100 and d['treatment_n']==120
    assert standardized({})['status']=='insufficient_common_support'


def test_short_source_has_same_cutoff_as_official_history():
    rows=[{'date':'20261008'},{'date':'20261009'}]
    assert completed_source(rows,'20261008')==rows[:1]


def test_snapshot_cannot_verify_a_wrong_deadline_or_race_identity():
    from scraper.research_snapshot import valid_snapshot
    r=sample();r.pop('result')
    dl=datetime(2026,10,1,12,tzinfo=JST)
    assert not capture(r,dl-timedelta(minutes=1),dl+timedelta(minutes=30))
    assert capture(r,dl-timedelta(minutes=1),dl)
    wrong=deepcopy(r);wrong['rno']=2
    assert not valid_snapshot(r['research_snapshot'],wrong)


def test_motor_prior_day_baseline_and_title_boundary():
    rows=[]
    for day in ('20260901','20260902'):
        for i in range(5):
            r=race(day,zero=day=='20260901');r[2]=i+1;rows.append(r)
    meta=[{'date':'20260901','jcd':'01','racelist':{'title':'first'}},
          {'date':'20260902','jcd':'01','racelist':{'title':'second'}}]
    out=analyze(rows,meta);assert out['recent_changes']
    assert any(b['reason']=='saved_official_title_change' for b in out['boundaries'])
    before=deepcopy(out['recent_changes'][0]['previous'])
    future=deepcopy(rows)
    for r in future:
        if r[0]=='20260902':
            r[11][0][5],r[11][5][5]=6,1
    assert analyze(future,meta)['recent_changes'][0]['previous']==before
    assert all(abs(x['previous']['expected_top2_prior_days']-1/3)<1e-10 for x in out['recent_changes'])
    assert all(not x['official_renewal_verified'] for x in out['recent_changes'])


def test_motor_serialization_is_reproducible_across_hash_seeds():
    import os,subprocess,sys
    code='''
import sys,json
sys.path.insert(0,'tests')
from test_player_research import race
from tools.motor_research import analyze
rows=[]
for day in ('20260901','20260905'):
 for j in ('01','02','03','04'):
  for i in range(5):
   r=race(day,zero=day=='20260901');r[1]=j;r[2]=i+1;rows.append(r)
print(json.dumps(analyze(rows,[]),ensure_ascii=False))
'''
    outputs=[subprocess.check_output([sys.executable,'-c',code],env={**os.environ,'PYTHONHASHSEED':seed}) for seed in ('1','2')]
    assert outputs[0]==outputs[1]
