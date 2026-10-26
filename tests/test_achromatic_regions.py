import hashlib
import json

import pytest

from tools.audit_achromatic_regions import audit_frames
from tools.frame_binding import frame_binding


@pytest.mark.parametrize('vest_colour,expected', [('white', 1), ('black', None)])
def test_observed_helmet_and_vest_require_agreement_across_bound_frames(tmp_path, vest_colour, expected):
    cv2 = pytest.importorskip('cv2')
    if not hasattr(cv2, 'imread'):
        pytest.skip('optional OpenCV unavailable')
    from PIL import Image
    image = Image.new('RGB', (100, 100), 'white')
    image.paste(vest_colour, (0, 35, 100, 70))
    image.save(tmp_path/'frame.png')
    sha = hashlib.sha256((tmp_path/'frame.png').read_bytes()).hexdigest()
    manifest = {'schema': 2, 'source': {'clock': 'decoded_pts', 'sha256': 'a'*64, 'time_base': [1, 100]},
                'image_size': [100, 100], 'frames': [{'file': 'frame.png', 'pts': i*10, 'sha256': sha} for i in range(4)]}
    (tmp_path/'frames.json').write_text(json.dumps(manifest), encoding='utf-8')
    config = {'prototypes': {str(b): [[int(j == feature) for j in range(6)]]
                            for b,feature in [(1,5),(2,4),(3,0),(4,1),(5,2),(6,3)]},
              'max_distance': .65, 'min_margin': .04}
    fingerprint = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    (tmp_path/'model.json').write_text(json.dumps({**config, 'fingerprint': fingerprint}), encoding='utf-8')
    observations = [{'frame': i, 'pts': i*10, 'identity': {'boat': 1}, 'point': [10+i, 20],
                     'rider_region': {'kind': 'person', 'box': [15, 0, 70, 40]},
                     'detections': [{'class': 0, 'score': .8, 'box': [0, 0, 100, 100]}]} for i in range(4)]
    result = {'frame_binding': frame_binding(manifest), 'colour_model_fingerprint': fingerprint,
              'identity_observations': [{'gate': 'A', 'peak_frame': 1, 'boat': 1, 'observations': observations}]}
    report = audit_frames(tmp_path, result, tmp_path/'model.json')
    assert report['gate_region_audit'][0]['regional_event_boat'] == expected
    assert report['changes_existing_candidates'] is False
    assert all(row['identity']['boat'] == 1 for row in result['identity_observations'][0]['observations'])
    # A changed raw frame cannot borrow the existing PTS/binding.
    (tmp_path/'frame.png').write_bytes(b'changed')
    with pytest.raises(ValueError, match='source_frame_changed'):
        audit_frames(tmp_path, result, tmp_path/'model.json')
