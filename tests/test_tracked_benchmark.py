from copy import deepcopy
import pytest
from tools.benchmark_tracked_bows import compare, compare_by_pts_and_sha
from tools.frame_binding import frame_binding


def inputs():
    manifest={'schema':2,'source':{'clock':'decoded_pts','time_base':[1,30],'sha256':'a'*64},
              'frames':[{'pts':i,'sha256':str(i)*64} for i in range(3)]}
    auto={'frame_binding':frame_binding(manifest),'results':[{'boat':b,'status':'rejected','reasons':['missing_C'],
          'events':{'A':{'time':1.2}}} for b in range(1,7)]}
    ref={'source_sha256':'a'*64,'results':[{'boat':b,'events':{g:{'mean_time':1} for g in 'ABC'}} for b in range(1,7)]}
    selected={'source':deepcopy(manifest['source']),'frames':{'0':deepcopy(manifest['frames'][0])}}
    return manifest,auto,ref,selected


def test_failed_boats_remain_in_denominator_and_bad_errors_are_visible():
    args=inputs();args[1]['results'][0]['events']['A']['time']=10
    report=compare(*args)
    assert report['boats_total']==6 and report['complete_candidates']==0
    assert report['detected_gates']==6 and report['max_gate_error_seconds']==9
    assert not report['publication_ready'] and not report['heldout']


def test_reviews_from_another_export_cannot_be_used_as_reference():
    args=deepcopy(inputs());args[3]['frames']['0']['pts']=9
    with pytest.raises(ValueError,match='reference_export_mismatch'):compare(*args)


def test_explicit_rebinding_uses_pts_and_image_sha_not_old_index():
    args=inputs()
    args[3]['frames']={'99':deepcopy(args[0]['frames'][1])}
    result=compare_by_pts_and_sha(*args)
    assert result['review_frame_mapping']==[{'review_index':99,'current_index':1,'pts':1,'sha256':'1'*64}]
    assert result['boats_total']==6 and result['heldout'] is False
    assert '99' in args[3]['frames']  # Original review evidence is never rewritten.
    args[3]['frames']['99']['sha256']='f'*64
    with pytest.raises(ValueError,match='reference_pts_or_image_mismatch'):
        compare_by_pts_and_sha(*args)


def test_rebinding_cannot_drop_review_frames_outside_the_new_crop():
    args=inputs();args[3]['frames']['99']={'pts':999,'sha256':'f'*64}
    with pytest.raises(ValueError,match='reference_pts_or_image_mismatch'):
        compare_by_pts_and_sha(*args)
