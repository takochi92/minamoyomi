import json
import hashlib

import pytest
from PIL import Image

from scraper.turn_measurement import digest
from tools.build_turn_review import build


def source(tmp_path):
    # Synthetic images test packaging and time continuity, not tracking accuracy.
    Image.new('RGB', (100, 100), 'navy').save(tmp_path / 'frame.png')
    frames = [{"file": "frame.png", "before": i / 30, "after": i / 30 + .002} for i in range(150)]
    (tmp_path / 'frames.json').write_text(json.dumps(frames), encoding='utf-8')
    config = {"venue": "heiwajima", "turn": "1-mark", "date": "2026-10-26", "race": 1,
              "image_size": [100, 100], "gates": {}, "source": "official-replay"}
    tracks = [{"boat": i, "points": []} for i in range(1, 7)]
    report = {"date": config["date"], "race": 1, "venue": config["venue"],
              "results": [{"boat": i, "events": {"A": .5, "B": 2.5, "C": 4.5}} for i in range(1, 7)]}
    return frames, config, tracks, report


def test_continuous_turn_contains_all_intermediate_frames_and_preserves_old_drafts(tmp_path):
    frames, config, tracks, report = source(tmp_path)
    page, bundle = build(tmp_path, config, tracks, report)
    assert len(bundle['events']) == 18 and len(bundle['clips']) == 6
    for clip in bundle['clips']:
        ids = [f['index'] for f in clip['frames']]
        assert ids == list(range(3, 148))
        for frame in clip['frames']:
            assert frame['time'] == (frames[frame['index']]['before'] + frames[frame['index']]['after']) / 2
    legacy = {key: value for key, value in bundle.items() if key not in ('digest', 'images', 'clips', 'compatible_digests')}
    old_indices = {frame['index'] for event in bundle['events'] for frame in event['frames']}
    legacy['image_digests'] = {i: digest(bundle['images'][i]) for i in old_indices}
    assert bundle['compatible_digests'] == [digest(legacy)]
    assert bundle['source_clock'] == 'browser_capture_clock_unverified'
    assert 'id="play"' in page and 'id="scene"' in page and '__RACE_LABEL__' not in page


def test_real_gap_is_rejected_instead_of_filling_with_interpolated_frames(tmp_path):
    frames, config, tracks, report = source(tmp_path)
    frames[50]['before'] += 1; frames[50]['after'] += 1
    (tmp_path / 'frames.json').write_text(json.dumps(frames), encoding='utf-8')
    with pytest.raises(ValueError, match='missing or reversed'):
        build(tmp_path, config, tracks, report)


def test_different_race_is_not_silently_relabelled(tmp_path):
    _, config, tracks, report = source(tmp_path)
    with pytest.raises(ValueError, match='different race'):
        build(tmp_path, {**config, 'race': 2}, tracks, report)


def test_decoded_pts_stay_exact_and_tampered_image_is_rejected(tmp_path):
    frames, config, tracks, report = source(tmp_path)
    sha = hashlib.sha256((tmp_path/'frame.png').read_bytes()).hexdigest()
    native = {'schema': 2, 'image_size': [100, 100], 'source': {'clock': 'decoded_pts', 'time_base': [1, 1000],
              'sha256': 'a'*64, 'origin_verified': False, 'editing_speed_verified': False},
              'frames': [{'file': f['file'], 'pts': i*33, 'sha256': sha} for i, f in enumerate(frames)]}
    (tmp_path/'frames.json').write_text(json.dumps(native), encoding='utf-8')
    _, bundle = build(tmp_path, config, tracks, report)
    assert bundle['source_clock'] == 'decoded_pts'
    assert not bundle['source_details']['origin_verified']
    for frame in bundle['clips'][0]['frames']:
        assert frame['pts'] == frame['index']*33
        assert frame['time'] == frame['pts']/1000
    (tmp_path/'frame.png').write_bytes(b'changed')
    with pytest.raises(ValueError, match='fingerprint changed'):
        build(tmp_path, config, tracks, report)
