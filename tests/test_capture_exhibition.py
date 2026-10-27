import pytest
import sys
from types import SimpleNamespace
from tools.capture_exhibition import media_url,choose_variant,selected_segments,fetch,denial_summary
from tools.capture_exhibition import official_movie_page, observed_official_frame


def test_official_entry_uses_public_wrapper_and_accepts_only_matching_observed_frame():
    assert official_movie_page('20261026',1)=='https://www.heiwajima.gr.jp/replay/replay_movie/race/2026102601.htm?type=1'
    frame='https://front.player.boatrace-cdn.jp/player/vod?service=jyohp&stadium=04heiwajima&raceType=exhibition&raceDate=20261026&raceNumber=01&autoplay=1'
    assert observed_official_frame(frame,'20261026',1)
    for changed in (frame.replace('jyohp','boatcast'),frame.replace('20261026','20261025'),
                    frame.replace('raceNumber=01','raceNumber=02'),frame.replace('https://','http://'),
                    frame.replace('front.player.boatrace-cdn.jp','evil.test')):
        assert not observed_official_frame(changed,'20261026',1)
    with pytest.raises(ValueError):official_movie_page('20260230',1)


def test_public_route_mapping_records_jyohp_without_fetching_or_leaking_credentials():
    from tools.audit_exhibition_routes import classify
    page='https://www.heiwajima.gr.jp/asp/heiwajima/replay/replay_movie_player.php'
    body='<iframe src="https://front.player.boatrace-cdn.jp/player/vod?service=jyohp&amp;stadium=04heiwajima&amp;raceType=exhibition&amp;token=secret"></iframe>'
    result=classify(page,body)
    assert any(r['service']=='jyohp' for r in result)
    assert 'secret' not in str(result) and 'token' not in str(result)


def test_official_denial_stops_before_click_and_blocks_sdk_retry(monkeypatch):
    from tools.capture_exhibition import discover_master
    seen={}
    class Response:
        url='https://playback.api.streaks.jp/private-endpoint?token=secret'
        status=403
        headers={'content-type':'application/json'}
        def body(self):return b'{"errors":[{"id":124,"code":"REQUEST_FAILED","token":"secret"}]}'
    class Route:
        def abort(self):seen['retry_aborted']=True
        def continue_(self):raise AssertionError('A denied playback API must not be retried')
    class Page:
        frames=[]
        def on(self,event,callback):self.callback=callback
        def route(self,pattern,callback):self.guard=callback
        def goto(self,url,**kwargs):
            seen['url']=url;self.callback(Response());self.guard(Route())
        def get_by_role(self,*args,**kwargs):raise AssertionError('Must stop before clicking after denial')
    class Browser:
        def new_context(self):return self
        def new_page(self):return Page()
        def close(self):seen['closed']=True
    class Runtime:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        @property
        def chromium(self):return self
        def launch(self,**kwargs):return Browser()
    monkeypatch.setitem(sys.modules,'playwright.sync_api',SimpleNamespace(sync_playwright=Runtime))
    with pytest.raises(ValueError,match='official_playback_denied_stop') as error:
        discover_master('20261026',1,entry_route='official')
    assert seen['url']==official_movie_page('20261026',1)
    assert seen['retry_aborted'] and seen['closed']
    assert error.value.safe_diagnostics['blocked_sdk_retries']==1
    assert 'secret' not in str(error.value.safe_diagnostics)


@pytest.mark.parametrize('failure_stage',['launch_browser','open_official_player','click_play_video'])
def test_timeout_records_exact_stage_without_private_exception_text(monkeypatch,failure_stage):
    from tools.capture_exhibition import discover_master
    class Page:
        def on(self,*args):pass
        def goto(self,*args,**kwargs):
            if failure_stage=='open_official_player':raise TimeoutError('private signed URL')
        def get_by_role(self,*args,**kwargs):return self
        def click(self,**kwargs):raise TimeoutError('private signed URL')
    class Browser:
        def new_context(self):return self
        def new_page(self):return Page()
        def close(self):pass
    class Runtime:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        @property
        def chromium(self):return self
        def launch(self,**kwargs):
            if failure_stage=='launch_browser':raise TimeoutError('private signed URL')
            return Browser()
    monkeypatch.setitem(sys.modules,'playwright.sync_api',SimpleNamespace(sync_playwright=Runtime))
    with pytest.raises(TimeoutError) as error:discover_master('20261026',2)
    assert error.value.safe_diagnostics['stage']==failure_stage
    assert 'private' not in str(error.value.safe_diagnostics)


def test_denial_diagnostics_keep_only_known_enums_and_numeric_ids():
    payload={'errors':[{'id':126,'code':'REQUEST_FAILED','message':'private URL https://secret.test',
                        'token':'secret','error_subcode':'CLIENT_GEO'},
                       {'code':'secret-key','id':'secret','request_url':'https://secret.test'}]}
    result=denial_summary(payload)
    assert result=={'json_error':True,'codes':['CLIENT_GEO','REQUEST_FAILED'],'error_ids':[126]}
    assert 'secret' not in str(result)
    assert denial_summary('untrusted body')=={'json_error':False,'codes':[],'error_ids':[]}


def test_capture_accepts_only_observed_service_https_hosts():
    assert media_url('https://manifest.streaks.jp/public/manifest.m3u8')
    for value in ['http://manifest.streaks.jp/x','https://streaks.jp.evil.test/x','https://127.0.0.1/x',
                  'https://name:password@manifest.streaks.jp/x','https://manifest.streaks.jp:8443/x']:
        assert not media_url(value)


def test_choose_supported_video_quality_and_reject_no_variant():
    text='#EXTM3U\n#EXT-X-STREAM-INF:RESOLUTION=854x480\nlow.m3u8\n#EXT-X-STREAM-INF:RESOLUTION=1920x1080\nhigh.m3u8\n#EXT-X-STREAM-INF:RESOLUTION=3840x2160\n4k.m3u8'
    assert choose_variant('https://variants.streaks.jp/v/master.m3u8',text)==(1080,'https://variants.streaks.jp/v/high.m3u8')
    with pytest.raises(ValueError):choose_variant('https://variants.streaks.jp/v/master.m3u8','#EXTM3U\n')


def test_only_bounded_late_video_interval_is_selected():
    text='#EXTM3U\n#EXT-X-MEDIA-SEQUENCE:100\n'+''.join(f'#EXTINF:6,\nsegment-{i}.ts\n' for i in range(58))
    duration,segments=selected_segments('https://variants.streaks.jp/v/index.m3u8',text)
    assert duration==348 and len(segments)==20
    assert segments[0][0]==133 and segments[0][1]==198
    assert sum(s[2] for s in segments)==120


def test_time_prior_only_narrows_download_and_does_not_assign_boats_or_times():
    text='#EXTM3U\n#EXT-X-MEDIA-SEQUENCE:100\n'+''.join(f'#EXTINF:6,\nsegment-{i}.ts\n' for i in range(58))
    duration,segments=selected_segments('https://variants.streaks.jp/v/index.m3u8',text,(225,310))
    assert duration==348 and segments[0][0]==137 and segments[0][1]==222
    assert sum(s[2] for s in segments)==90
    for window in [(0,200),(310,225),(225,float('nan')),(225,400)]:
        with pytest.raises(ValueError,match='preferred_time_window'):
            selected_segments('https://variants.streaks.jp/v/index.m3u8',text,window)


@pytest.mark.parametrize('line',['#EXT-X-KEY:METHOD=SAMPLE-AES,URI="key"',
                               '#EXT-X-KEY:METHOD=AES-128,KEYFORMAT="com.widevine",URI="key"',
                               '#EXT-X-MAP:URI="init.mp4"','#EXT-X-BYTERANGE:100@0'])
def test_protected_or_unsupported_media_is_rejected_without_fetching(line):
    with pytest.raises(ValueError):selected_segments('https://variants.streaks.jp/v/index.m3u8','#EXTM3U\n'+line+'\n')


def test_download_limits_and_redirect_hosts_are_checked():
    class Response:
        def __enter__(self):return self
        def __exit__(self,*_):pass
        def geturl(self):return 'https://variants.streaks.jp/v/data'
        def read(self,n):return b'x'*n
    with pytest.raises(ValueError,match='size_limit'):
        fetch('https://variants.streaks.jp/v/data',32,opener=lambda *a,**k:Response())
