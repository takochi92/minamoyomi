from copy import deepcopy
from datetime import datetime, timezone, timedelta
import gzip
import json

from scraper.exhibition_profile import baseline, observations, previous_terms, profiles, surprise, term_info
from tools.exhibition_surprise import analyze


def race(day,top=False):
    es=[]
    for f in range(1,7):
        ex=665 if top and f==3 else 670+f
        es.append([f,str(4000+f),f,15,'',f,ex,['B1',5.0,30,5,30,30,30]])
    return [day,'01',1,'逃げ','北',2,0,0,'1-2-3',1000,5,es]


def test_terms_keep_assessment_separate_from_application():
    assert term_info('20260430')['key']=='2026後期'
    assert term_info('20260501')['key']=='2027前期'
    assert term_info('20261031')['key']=='2027前期'
    assert term_info('20261101')['key']=='2027後期'
    assert term_info('20261101')['from']=='20261101'
    assert term_info('20261101')['to']=='20270430'
    assert previous_terms('20260501')==['2026後期','2026前期']


def test_ties_and_missing_six_boats():
    r=race('20251001');r[11][1][6]=r[11][0][6]
    obs=observations(r)
    assert sum(o['top1'] for o in obs)==2
    assert sum(o['solo1'] for o in obs)==0
    assert abs(sum(o['dev'] for o in obs))<1e-10
    r[11][-1][6]=None
    assert observations(r)==[]


def test_future_and_current_term_never_change_reference():
    old=[race('20260101') for _ in range(100)]
    d=profiles(old);past=baseline(d,'20260901','4003')
    assert past['n']==100 and past['top1']==0
    future=[race('20261001',True) for _ in range(100)]+[race('20270101',True) for _ in range(100)]
    assert baseline(profiles(old+future),'20260901','4003')==past
    o=observations(race('20260901',True))[2]
    s=surprise(o,past)
    assert s['rare_solo1'] and s['rare_solo1_improved']
    o['win']=not o['win'];o['top3']=not o['top3']
    assert surprise(o,past)==s


def test_small_samples_and_tied_first_do_not_trigger():
    past=baseline(profiles([race('20260101') for _ in range(99)]),'20260901','4003')
    o=observations(race('20260901',True))[2]
    assert not surprise(o,past)['rare_solo1']
    past['n']=100;o['solo1']=False
    assert not surprise(o,past)['rare_solo1']


def test_existing_exstats_reader_is_compatible(tmp_path,monkeypatch):
    from scraper import history
    records=[race('20250101'),race('20260901'),race('20270101')]
    monkeypatch.setattr(history,'load_all',lambda since='': [r for r in records if r[0]>=since])
    monkeypatch.setattr(history,'EXSTATS_PATH',tmp_path/'exstats.json.gz')
    history.build_exstats(datetime(2026,10,9,tzinfo=timezone(timedelta(hours=9))))
    data=json.load(gzip.open(history.EXSTATS_PATH,'rt'))
    assert history.load_exstats()==data['r']
    assert data['term_profiles']['eligible_races']==2
    assert '2027後期' not in data['term_profiles']['terms']


def test_surprise_analysis_has_consistent_denominators():
    rs=[race('20260101') for _ in range(100)]+[race('20260901',True)]
    d=analyze(rs)
    assert len(d['rare_solo1_events'])==1
    for a in d['groups']:
        assert 0<=a['win']<=a['top3']<=a['n']
