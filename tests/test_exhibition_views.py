import json
import re
import shutil
import subprocess

import pytest

from scraper.exhibition_views import catalog, render, research_catalog
from scraper.sitegen import Page, Site, SLUG
from scraper.predict import VENUES
from tools.extract_turn_frames import extract


def test_catalog_requires_explicit_publication_and_rights_and_rejects_unsafe_assets():
    row = {'date': '20261026', 'jcd': '04', 'rno': 1, 'asset': 'data/exhibition/20261026/04-1.html'}
    assert catalog({'records': [row]}) == []
    assert len(catalog({'records': [row]}, preview=True)) == 1
    approved = {**row, 'publish': True, 'rights_verified': True}
    assert len(catalog({'records': [approved, approved]})) == 1
    for change in [{'date': '20260230'}, {'rno': 13}, {'jcd': '99'}, {'asset': 'https://other/page.html'}, {'asset': 'data/exhibition/../evil.html'}]:
        assert catalog({'records': [{**approved, **change}]}) == []


def test_retired_page_never_embeds_media_or_research_data():
    s = Site.__new__(Site); s.files = {}; s.exhibition_records = []; s.idx = {'date': '20261026'}
    from datetime import datetime
    s.now = datetime(2026, 10, 26)
    s.exhibition_page()
    page = s.files['exhibition.html']
    assert '公開を休止しました' in page
    assert 'ev-config' not in page and '<iframe' not in page
    assert 'exhibition.js' not in page and 'ev-source' not in page
    assert '20歳未満' in page and 'のめり込み' in page
    assert 'content="noindex"' in page
    assert 'data:image' not in page


def test_race_page_preserves_official_exhibition_without_retired_video_links():
    s = Site.__new__(Site)
    s.oriten_block = lambda *_: '<table>既存の展示表</table>'
    s.slit_block = lambda *_: '<section>既存のスリット</section>'
    race = {'racelist': {'boats': []}, 'before': {}}
    s.exhibition_records = []
    before = s.ex_tab('20261026', '04', 1, race, {})
    assert '展示映像を別ページ' not in before
    s.exhibition_records = [{'date': '20261026', 'jcd': '04', 'rno': 1}]
    after = s.ex_tab('20261026', '04', 1, race, {})
    assert 'exhibition.html' not in after
    assert '<iframe' not in after and '<canvas' not in after
    assert after.count('既存の展示表') == 1


def test_registry_json_cannot_break_out_of_page_script():
    venues = {j: {**v, 'slug': SLUG[j]} for j, v in VENUES.items()}
    page = render(Page('exhibition.html'), venues, '20261026', [{'status': '</script><script>alert(1)</script>'}], preview=True)
    assert '</script><script>alert' not in page
    config = re.search(r'id="ev-config">(.*?)</script>', page, re.S).group(1)
    assert json.loads(config)['records'][0]['status'].startswith('</script>')


def test_public_research_is_explicitly_distinct_from_approved_media():
    from pathlib import Path
    raw=json.loads((Path(__file__).resolve().parents[1]/'site/data/exhibition/research.json').read_text(encoding='utf-8'))
    rows=[r for r in research_catalog(raw) if r['date']=='20261026' and r['jcd']=='04']
    assert len(rows)==12 and [r['rno'] for r in rows]==list(range(1,13))
    assert [r['rno'] for r in rows if 'reference' in r]==[1,2,3]
    assert len(rows[0]['reference']['boats'])==6
    assert catalog(raw)==[]  # Public numeric samples never approve source media.
    bad={**raw['records'][0], 'official_url':raw['records'][1]['official_url']}
    assert research_catalog({'records':[bad]})==[]
    for change in [{'publication_ready':True},{'prediction_used':True},{'review_count':1},
                   {'max_review_difference_seconds':float('nan')},{'boats':[None]}]:
        candidate={**raw['records'][0], 'reference':{**raw['records'][0]['reference'],**change}}
        assert 'reference' not in research_catalog({'records':[candidate]})[0]


def test_navigation_replaces_exhibition_with_player_information():
    page=Page('stats.html').render('test','test','')
    nav=re.search(r'<nav class="nav">(.*?)</nav>',page,re.S)[1]
    assert re.findall(r'href="([^"]+)"',nav)==['index.html','targets.html','players.html','racer/index.html','stats.html','mynote.html']
    assert '実績と根拠' in nav and 'logic.html' not in nav
    assert 'data-k="stats" aria-current=page' in nav


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='offline video decoder not installed')
def test_decode_uses_true_variable_frame_pts_and_never_rewrites_original(tmp_path):
    video = tmp_path/'synthetic-variable.mkv'
    subprocess.run([shutil.which('ffmpeg'), '-v', 'error', '-f', 'lavfi', '-i', 'testsrc=size=64x64:rate=10:duration=1',
                    '-vf', r'setpts=if(lt(N\,5)\,N\,N+3)/(10*TB)', '-fps_mode', 'passthrough', '-c:v', 'ffv1', str(video)],
                   check=True, capture_output=True, timeout=30)
    before = video.read_bytes()
    result = extract(video, tmp_path/'decoded', 0, 1.3)
    base = result['source']['time_base']; times = [r['pts']*base[0]/base[1] for r in result['frames']]
    assert times == pytest.approx([0, .1, .2, .3, .4, .8, .9, 1, 1.1, 1.2])
    assert video.read_bytes() == before
    assert len(list((tmp_path/'decoded').glob('*.png'))) == 10
    assert result['source']['clock'] == 'decoded_pts' and not result['source']['origin_verified']
    assert not result['publication_ready']
    partial = extract(video, tmp_path/'decoded-partial', .8, 1.3)
    assert [r['pts']*base[0]/base[1] for r in partial['frames']] == pytest.approx([.8, .9, 1, 1.1, 1.2])
    with pytest.raises(FileExistsError): extract(video, tmp_path/'decoded', 0, 1.3)


def test_decoder_rejects_remote_or_playlist_and_unbounded_intervals(tmp_path):
    with pytest.raises(ValueError): extract('https://example.com/video.mp4', tmp_path/'out', 0, 1)
    playlist = tmp_path/'remote.m3u8'; playlist.write_text('https://example.com/media.ts')
    with pytest.raises(ValueError): extract(playlist, tmp_path/'out', 0, 1)


def test_real_native_example_uses_pts_and_hull_labels_but_is_not_promoted():
    from pathlib import Path
    from scraper.turn_measurement import crossing
    data = json.loads((Path(__file__).resolve().parents[1]/'research/exhibition-video/heiwajima-20261026-1R/native-boat3-example.json').read_text(encoding='utf-8'))
    events = {}
    base = data['source']['time_base']
    for gate, definition in data['gates'].items():
        pair = data['pairs']['3:'+gate]
        points = []
        for side in ('before', 'after'):
            index = pair[side]; annotation = data['labels']['3:'+str(index)]
            points.append({'x': (annotation['bow'][0]+annotation['stern'][0])/2,
                           'y': (annotation['bow'][1]+annotation['stern'][1])/2,
                           'time': data['frames'][str(index)]['pts']*base[0]/base[1]})
        assert 0 < points[1]['time']-points[0]['time'] <= .12
        events[gate] = crossing(*points, definition)
        assert events[gate] is not None
    assert round(events['B']-events['A'], 1) == data['result']['entry_seconds'] == 1.8
    assert round(events['C']-events['B'], 1) == data['result']['exit_seconds'] == 2.0
    assert data['result']['review_count'] == 1 and not data['publication_ready']
