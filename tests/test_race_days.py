import gzip
import json
from datetime import datetime, timezone, timedelta

import pytest

from scraper import race_days, day_browser, run, sitegen


@pytest.mark.parametrize('today,first', [('20261029','20260929'),('20260331','20260228'),
    ('20240331','20240229'),('20260131','20251231'),('20260228','20260128')])
def test_one_calendar_month_includes_boundary_and_handles_short_months(today, first):
    assert race_days.bounds(today) == (first,today)
    choices=list(race_days.days(today))
    assert choices[0]==first and choices[-1]==today and len(set(choices))==len(choices)


def record(date='20261010'):
    return {'date':date,'jcd':'04','rno':1,'deadline':'13:00',
            'racelist':{'title':'当時の開催','boats':[{'frame':1,'name':'保存 選手','class':'A1'}]},
            'prediction':{'original_version':'saved-v1','p3':[.5,.2]},
            'odds_pre':{'at':'12:55','v':[12.3]},'result':{'finished':True,'trifecta':'1-2-3','trifecta_payout':1230}}


def test_archive_is_written_before_raw_pruning_and_prediction_is_not_rebuilt(tmp_path,monkeypatch):
    data=tmp_path/'data';folder=data/'races/20261010';folder.mkdir(parents=True)
    original=record();(folder/'0401.json').write_text(json.dumps(original),encoding='utf-8')
    (data/'races/backup').mkdir();research=tmp_path/'history';research.mkdir();(research/'keep').write_text('long term')
    monkeypatch.setattr(run,'DATA',data);run.prune('20261029')
    assert not folder.exists() and (data/'races/backup').exists()
    assert race_days.load_details(data,'20261029')['20261010']==[original]
    assert (research/'keep').read_text()=='long term'
    assert not (data/'race-days/20261029.json.gz').exists()


def test_bad_source_aborts_pruning_instead_of_losing_the_only_copy(tmp_path,monkeypatch):
    data=tmp_path/'data';folder=data/'races/20261010';folder.mkdir(parents=True)
    path=folder/'0401.json';path.write_text('{invalid')
    monkeypatch.setattr(run,'DATA',data)
    with pytest.raises(json.JSONDecodeError):run.prune('20261029')
    assert path.exists()


def test_raw_correction_overrides_archive_and_month_expiry_does_not_touch_history(tmp_path):
    original=record('20260929');race_days.save_packet(tmp_path,'20260929',[original])
    old=record('20260928');race_days.save_packet(tmp_path,'20260928',[old])
    folder=tmp_path/'races/20260929';folder.mkdir(parents=True)
    corrected={**original,'result':{**original['result'],'trifecta_payout':5000}}
    (folder/'0401.json').write_text(json.dumps(corrected),encoding='utf-8')
    assert race_days.load_details(tmp_path,'20261029')['20260929'][0]['result']['trifecta_payout']==5000
    race_days.retain_completed(tmp_path,'20261029')
    assert not (tmp_path/'race-days/20260928.json.gz').exists()
    assert '20260929' not in race_days.load_details(tmp_path,'20261030')


def test_generated_expiry_only_removes_known_date_paths(tmp_path):
    for folder in ('race/20260928','race/20260929','race/manual'):
        p=tmp_path/folder;p.mkdir(parents=True);(p/'test.html').write_text('generated')
    (tmp_path/'races').mkdir();(tmp_path/'races/20260928.html').write_text('old')
    (tmp_path/'races/keep.json').write_text('keep')
    race_days.prune_generated(tmp_path,'20261029')
    assert not (tmp_path/'race/20260928').exists() and not (tmp_path/'races/20260928.html').exists()
    assert (tmp_path/'race/20260929/test.html').exists() and (tmp_path/'race/manual/test.html').exists()
    assert (tmp_path/'races/keep.json').exists()


def test_dated_pages_merge_saved_details_with_results_without_inventing_predictions(tmp_path,monkeypatch):
    data=tmp_path/'site/data';data.mkdir(parents=True);monkeypatch.setattr(sitegen,'DATA',data)
    hist=tmp_path/'history';hist.mkdir()
    def k(date):return [date,'04',1,'逃げ','北',2,2,0,'1-2-3',1230,1,
        [[f,str(4000+f),f,15,'',f,680+f,['A1',6,40,6,40,30,40,30,52],20+f] for f in range(1,7)]]
    (hist/'202609.jsonl.gz').write_bytes(gzip.compress(('\n'.join(json.dumps(k(d)) for d in ('20260928','20260929'))+'\n').encode()))
    class Stub:
        idx={'date':'20261029'};now=datetime(2026,10,29,5,tzinfo=timezone(timedelta(hours=9)))
        def __init__(self):self.files={};self.day_races={'20261028':[record('20261028')]}
        def put(self,path,html):self.files[path]=html
        def racer_name(self,toban,default=''):return default
        def race_link(self,page,date,jcd,no):return page.u(f'race/{date}/{sitegen.SLUG[jcd]}-{no}.html')
        def finished(self,r):return sitegen.Site.finished(self,r)
        def race_cards(self,*args):return sitegen.Site.race_cards(self,*args)
    s=Stub();day_browser.build(s)
    assert 'races/20260929.html' in s.files and 'races/20260928.html' not in s.files
    assert 'race/20260929/heiwajima-1.html' in s.files and 'race/20260928/heiwajima-1.html' not in s.files
    assert '当時の予想・オッズ・詳細展示は未保存' in s.files['race/20260929/heiwajima-1.html']
    assert 'window.__RACE__' not in s.files['race/20260929/heiwajima-1.html']
    html=s.files['races/20261028.html']
    assert '結果 ' in html and '結果未保存' not in html  # Finished yesterday even at 05:00 today.
    assert 'min="2026-09-29" max="2026-10-29"' in html
    assert 'races/20261029.html' not in s.files
    assert s.day_races['20261028'][0]['prediction']==record()['prediction']
