import json
from urllib.error import HTTPError, URLError

import pytest

from tools.update_exhibition import parse_setting, merge_records, run, official_player, fetch_setting


def setting(day='20261026', races=(1,12)):
    return {'races':{f'{r:02}':{'race_number':f'{r:02}','ref_id':f'mix-04heiwajima-exhibition-{day}-{r:02}', 'source_type':'mix'} for r in races}}


def test_source_registration_is_not_an_analysis_result():
    records=parse_setting(setting(),'20261026')
    assert [r['rno'] for r in records]==[1,12]
    assert all(r['analysis_state']=='not_measured' and 'reference' not in r for r in records)
    assert 'raceNumber=12' in records[-1]['official_url']
    assert parse_setting(setting('20261025'),'20261026')==[]
    with pytest.raises(ValueError):parse_setting({'races':[]},'20261026')
    with pytest.raises(ValueError):official_player('20260230',1)
    with pytest.raises(ValueError):official_player('20261026',13)


def test_repeated_updates_preserve_original_review_and_never_reuse_across_days():
    old={'records':[{'date':'20261026','jcd':'04','rno':1,'official_url':official_player('20261026',1),
                     'reference':{'sentinel':'original_review'}}]}
    once=merge_records(old,parse_setting(setting(),'20261026'),'20261026')
    twice=merge_records(once,parse_setting(setting(),'20261026'),'20261026')
    assert once==twice
    assert twice['records'][0]['reference']==old['records'][0]['reference']
    next_day=merge_records(twice,parse_setting(setting('20261027'),'20261027'),'20261027')
    assert all('reference' not in r for r in next_day['records'] if r['date']=='20261027')
    assert 'source_state' not in old['records'][0] # Input was not mutated.


def test_disappearing_source_is_not_still_presented_as_confirmed():
    fresh=parse_setting(setting(),'20261026')
    result=merge_records({'records':fresh},[],'20261026')
    assert all(r['source_state']=='unavailable' for r in result['records'])


@pytest.mark.parametrize('error',[HTTPError('https://example',401,'auth',None,None),
                                  HTTPError('https://example',404,'missing',None,None),
                                  URLError('secret error text')])
def test_source_failure_preserves_registry_and_sanitizes_report(tmp_path,error):
    registry=tmp_path/'registry.json';status=tmp_path/'status.json'
    raw=json.dumps({'records':parse_setting(setting(),'20261026')})
    registry.write_text(raw,encoding='utf-8')
    def failure(day):raise error
    result=run('20261026',registry,status,fetcher=failure)
    assert registry.read_text(encoding='utf-8')==raw
    assert not result['automatic_video_analysis_enabled']
    assert result['automatic_video_analysis_state']=='not_implemented'
    assert 'secret' not in status.read_text(encoding='utf-8')
    assert result['source_state'] in ('waiting','fetch_error')


def test_job_changes_only_its_registry_and_status_files(tmp_path):
    race=tmp_path/'race.json';race.write_bytes(b'unchanged prediction')
    registry=tmp_path/'research.json';status=tmp_path/'status.json'
    result=run('20261026',registry,status,fetcher=lambda _:setting())
    assert result['source_registered_races']==2 and result['registry_changed']
    assert not result['prediction_used']
    assert race.read_bytes()==b'unchanged prediction'
    again=run('20261026',registry,status,fetcher=lambda _:setting())
    assert not again['registry_changed']


def test_setting_download_is_bounded_and_does_not_call_media_api():
    calls=[]
    class Response:
        def __enter__(self):return self
        def __exit__(self,*_):pass
        def geturl(self):return calls[-1]
        def read(self,n):return json.dumps(setting()).encode()
    def opener(request,timeout):
        calls.append(request.full_url)
        assert timeout==20
        return Response()
    assert fetch_setting('20261026',opener)['races']
    assert calls==['https://front.player.boatrace-cdn.jp/setting/vod/20261026/04heiwajima/exhibition/setting.json']
