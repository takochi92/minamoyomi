import copy
import hashlib

import pytest

from scraper.turn_measurement import BOW_METHOD
from tools.compare_bow_reviews import compare


def fixture():
    config = {'method': BOW_METHOD, 'venue': 'heiwajima', 'turn': '1-mark',
              'image_size': [100, 100], 'gates': {g: {'axis':'x', 'value':50,
              'direction':1, 'segment':[0,99]} for g in 'ABC'}}
    manifest = {'source': {'clock':'decoded_pts', 'sha256':'a'*64, 'time_base':[1,90000]},
                'image_size':[100,100], 'frames':{}, 'windows':[]}
    review = {'reviewer':'one', 'method':BOW_METHOD, 'source_sha256':'a'*64,
              'size':[100,100], 'labels':{}, 'pairs':{}}
    for boat in range(1,7):
        for g, gate in enumerate('ABC'):
            a = boat*100+g*30
            manifest['windows'].append({'boat':boat,'gate':gate,'indices':[a,a+1]})
            review['pairs'][f'{boat}:{gate}']={'before':a,'after':a+1}
            for index, x in [(a,40),(a+1,60)]:
                manifest['frames'][str(index)]={'pts':index*3000,'file':'frame.png',
                                                'sha256':hashlib.sha256(b'image').hexdigest()}
                review['labels'][f'{boat}:{index}']={'bow':[x,50]}
    other=copy.deepcopy(review); other['reviewer']='two'
    return manifest, config, [review,other]


def test_two_reviews_recompute_pts_without_enabling_publication():
    manifest, config, reviews=fixture()
    result=compare(manifest,config,reviews)
    assert result['valid_gate_pairs']==18
    assert result['max_review_time_difference_seconds']==0
    assert all(r['entry_video_seconds']==r['exit_video_seconds']==1 for r in result['results'])
    assert not any(result[k] for k in ('publication_ready','real_time_scale_verified','predeadline_verified','prediction_used','images_fingerprint_verified'))


def test_unseen_bow_and_wrong_direction_are_not_given_times():
    manifest, config, reviews=fixture()
    reviews[0]['labels']['1:100']['obstructed']=True
    reviews[1]['labels']['2:200']['bow']=[70,50]
    result=compare(manifest,config,reviews)
    assert all(r['status']=='needs_remeasurement' for r in result['results'][:2])
    assert 'entry_video_seconds' not in result['results'][0]
    assert result['results'][2]['entry_video_seconds']==1


def test_review_disagreement_is_not_averaged_into_valid_result():
    manifest, config, reviews=fixture()
    reviews[1]['labels']['1:100']['bow']=[49,50]
    result=compare(manifest,config,reviews,tolerance_seconds=.001)
    assert result['paired_gate_count']==18 and result['valid_gate_pairs']==17
    assert result['results'][0]['status']=='needs_remeasurement'
    assert any('disagreement' in r for r in result['results'][0]['reasons'])


@pytest.mark.parametrize('change',['reviewer','method','source'])
def test_reused_reviewer_or_mismatched_evidence_rejected(change):
    manifest, config, reviews=fixture()
    if change=='reviewer': reviews[1]['reviewer']='one'
    if change=='method': reviews[1]['method']='heiwajima-hull-gates-v1'
    if change=='source': reviews[1]['source_sha256']='b'*64
    with pytest.raises(ValueError): compare(manifest,config,reviews)


def test_modified_frame_is_rejected(tmp_path):
    manifest, config, reviews=fixture()
    (tmp_path/'frame.png').write_bytes(b'changed')
    result=compare(manifest,config,reviews,frames_dir=tmp_path)
    assert not result['images_fingerprint_verified']
    assert all(r['status']=='needs_remeasurement' for r in result['results'])
    assert any('fingerprint' in reason for reason in result['results'][0]['reasons'])


def test_selected_images_can_be_verified(tmp_path):
    manifest, config, reviews=fixture()
    (tmp_path/'frame.png').write_bytes(b'image')
    assert compare(manifest,config,reviews,frames_dir=tmp_path)['images_fingerprint_verified']
