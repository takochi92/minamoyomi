import base64
import io
import json
import re
from PIL import Image

import pytest

from tools.build_turn_watch import build, make_bundle
from scraper.turn_measurement import digest


def bundle():
    return {'source_clock': 'decoded_pts', 'source_details': {'sha256': 'a'*64, 'time_base': [1, 100]},
            'date': '2026-10-26', 'race': 1, 'venue': 'heiwajima', 'size': [100, 100], 'gates': {},
            'clips': [{'boat': 1, 'frames': [{'index': i, 'pts': i*10, 'time': i/10} for i in range(3)]}],
            'events': [{'boat': 1, 'gate': 'A', 'frames': [{'index': 0}, {'index': 1}]}],
            'images': {str(i): 'unused' for i in range(3)}}


def test_watch_bundle_has_no_measurement_state_and_unreviewed_anchors_stay_empty():
    b = bundle()
    b.update(initial_review={'labels': {'private': 'data'}}, results=[{'time': 1}])
    result = make_bundle(b)
    assert result['anchors'] == {}
    assert 'initial_review' not in result and 'results' not in result
    assert result['clips'][0]['frames'] == b['clips'][0]['frames']
    assert result['publication_ready'] is False and result['prediction_used'] is False


@pytest.mark.parametrize('change', ['pts', 'gap', 'index', 'clock'])
def test_invalid_clocks_and_nonconsecutive_frames_are_rejected(change):
    b = bundle()
    if change == 'pts': b['clips'][0]['frames'][0]['pts'] = 999
    if change == 'gap': b['clips'][0]['frames'][2].update(time=1, pts=100)
    if change == 'index': b['clips'][0]['frames'][2]['index'] = 0
    if change == 'clock': b['source_clock'] = 'capture'
    with pytest.raises(ValueError): make_bundle(b)


def test_source_mismatch_is_rejected_before_review_can_supply_anchors():
    b = bundle()
    manifest = {'source': {'sha256': 'b'*64}}
    with pytest.raises(ValueError, match='mismatch'):
        make_bundle(b, (manifest, {}, []))


def test_same_container_but_different_frame_export_cannot_supply_sync(monkeypatch):
    import tools.build_turn_watch as watch
    b = bundle()
    b['method'] = 'heiwajima-bow-gates-v2'
    manifest = {'source': b['source_details'], 'image_size': b['size']}
    config = {**b}
    def report(*args):
        return {'results': [{'boat': 1, 'status': 'repeated_ai_video_measurement',
                'events': {'A': {'mean_time': .1, 'reviews': [{'frames': [{'index': 1, 'pts': 999}]}]}}}]}
    monkeypatch.setattr(watch, 'compare', report)
    with pytest.raises(ValueError, match='frame_export_mismatch'):
        make_bundle(b, (manifest, config, []))


def test_catalog_watch_asset_obeys_existing_rights_gate():
    from scraper.exhibition_views import catalog
    row = {'date': '20261026', 'jcd': '04', 'rno': 1, 'asset': 'data/exhibition/review.html',
           'watch_asset': 'data/exhibition/watch/index.html'}
    assert catalog({'records': [row]}) == []
    approved = {**row, 'publish': True, 'rights_verified': True}
    assert catalog({'records': [approved]})[0]['watch_asset'] == row['watch_asset']
    for asset in ('https://example.com/watch.html', 'data/exhibition/../watch.html'):
        assert 'watch_asset' not in catalog({'records': [{**approved, 'watch_asset': asset}]})[0]


def test_export_checks_every_image_digest_and_keeps_media_separate(tmp_path):
    b = bundle()
    buffer = io.BytesIO()
    Image.new('RGB', (100, 100), 'navy').save(buffer, format='WEBP')
    data = 'data:image/webp;base64,' + base64.b64encode(buffer.getvalue()).decode()
    b['images'] = {str(i): data for i in range(3)}
    b['image_digests'] = {str(i): digest(data) for i in range(3)}
    source = tmp_path/'review.html'
    source.write_text('<script type="application/json" id="bundle">'+json.dumps(b)+'</script>', encoding='utf-8')
    result = build(source, tmp_path/'watch')
    assert result['images'] == 1 and result['anchors'] == 0
    text = (tmp_path/'watch/index.html').read_text(encoding='utf-8')
    assert 'data:image' not in text and 'id="reviewer"' not in text
    assert len(list((tmp_path/'watch/frames').glob('*.webp'))) == 1
    b['image_digests']['1'] = 'wrong'
    source.write_text('<script type="application/json" id="bundle">'+json.dumps(b)+'</script>', encoding='utf-8')
    with pytest.raises(ValueError, match='fingerprint_changed'):
        build(source, tmp_path/'wrong')
    assert not (tmp_path/'wrong').exists()


def test_achromatic_regions_never_invent_identity_from_partial_or_conflicting_evidence():
    from tools.audit_achromatic_regions import region_consensus
    assert region_consensus({'boat': 1}, {'boat': 1}, 1) == 1
    assert region_consensus({'boat': 2}, {'boat': 2}, 2) == 2
    assert region_consensus({'boat': 1}, {'boat': 2}, 1) is None
    assert region_consensus({'boat': 1}, {'boat': None}, 1) is None
    assert region_consensus({'boat': 1}, {'boat': 1}, 2) is None
    assert region_consensus({'boat': 3}, {'boat': 3}, 3) is None
