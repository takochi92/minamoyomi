import pytest
from tools.capture_exhibition import media_url,choose_variant,selected_segments,fetch


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
