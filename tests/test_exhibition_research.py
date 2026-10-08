from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

from scraper.research_snapshot import archive, archived_records, capture
from tools.exhibition_research import analyze, external_candidates, features, market_win, ranks


def sample():
    return {'date':'20261001','jcd':'01','rno':1,'deadline':'12:00',
            'racelist':{'boats':[{'frame':f,'class':'B1','nat_win':5.5} for f in range(1,7)]},
            'before':{'exhibition_done':True,
                      'boats':[{'frame':f,'exhibit_time':6.8+(0 if f==3 else .02*f)} for f in range(1,7)],
                      'start_exhibition':[{'course':f,'frame':f,'st':.10 if f==3 else .15,'flag':''} for f in range(1,7)]},
            'oriten':{'items':['直線','一周','まわり足'],
                      'rows':{str(f):[7.0+(.0 if f==5 else .02*f),36+(.0 if f==5 else .02*f),6+(.0 if f==5 else .02*f)] for f in range(1,7)}},
            'result':{'finished':True,'order':[{'frame':f,'place':str(f)} for f in range(1,7)]}}


def test_ranks_require_six_valid_values_and_keep_ties():
    assert ranks({1:1,2:1,3:2,4:3,5:4,6:5})[2]==1
    assert ranks({1:1,2:2})=={}
    assert ranks({1:1,2:2,3:3,4:4,5:5,6:float('nan')})=={}


def test_external_conditions_are_pre_race_and_exclude_f():
    r=sample();f=features(r);v=external_candidates(f)
    assert any(x[0]==3 and x[1]==5 for x in v)
    r['result']['order'].reverse()
    assert external_candidates(features(r))==v
    r['before']['start_exhibition'][0]['flag']='F'
    assert external_candidates(features(r))==[]


def test_snapshot_boundary_and_deep_copy():
    r=sample();r.pop('result');tz=timezone(timedelta(hours=9))
    dl=datetime(2026,10,1,12,tzinfo=tz);now=dl-timedelta(seconds=1)
    assert capture(r,now,dl)
    snap=deepcopy(r['research_snapshot'])
    assert 'result' not in snap['inputs']
    r['before']['boats'][0]['exhibit_time']=99
    assert r['research_snapshot']==snap
    assert not capture(r,dl,dl)
    assert r['research_snapshot']==snap
    assert not capture(r,now-timedelta(seconds=1),dl)


def test_archive_preserves_verified_input_and_updates_results(tmp_path):
    r=sample();result=r.pop('result');tz=timezone(timedelta(hours=9))
    dl=datetime(2026,10,1,12,tzinfo=tz)
    capture(r,dl-timedelta(minutes=1),dl);r['result']=result
    p=tmp_path/'site/data/races/20261001/0101.json';p.parent.mkdir(parents=True)
    p.write_text(json.dumps(r))
    assert archive(tmp_path)['timestamped']==1
    assert archive(tmp_path)['added_or_updated']==0
    r.pop('research_snapshot');r['before']['boats'][0]['exhibit_time']=99
    r['result']['correction']='official';p.write_text(json.dumps(r));archive(tmp_path)
    saved=list(archived_records(tmp_path).values())[0]
    assert saved['provenance']=='timestamped_pre_deadline'
    assert saved['before']['boats'][0]['exhibit_time']!=99
    assert saved['result']['correction']=='official'


def test_legacy_never_becomes_verified_and_market_needs_complete_odds(tmp_path):
    r=sample();p=tmp_path/'site/data/races/20261001/0101.json';p.parent.mkdir(parents=True)
    p.write_text(json.dumps(r));assert archive(tmp_path)['timestamped']==0
    assert list(archived_records(tmp_path).values())[0]['provenance']=='legacy_unverified'
    r['odds_pre']={'v':[100]*120}
    assert all(abs(p-1/6)<1e-9 for p in market_win(r).values())
    r['odds_pre']['v'][0]=None
    assert market_win(r)=={}


def test_analysis_uses_exhibition_course_not_result_course():
    r=sample();r['before']['start_exhibition'][2]['frame']=5;r['before']['start_exhibition'][4]['frame']=3
    out=analyze([r],[],'20261003')
    row=next(x for x in out['groups'] if x['course']==3 and x['rule']=='直線＋一周')
    assert row['n']==1 and row['top3']==0  # 枠5が展示3コース、結果5着
