from copy import deepcopy
import pytest
from tools.frame_binding import frame_binding,require_frame_binding


def manifest():
    return {'schema':2,'source':{'clock':'decoded_pts','time_base':[1,90000],'sha256':'a'*64},
            'frames':[{'pts':90000+i*3000,'sha256':str(i)*64} for i in range(3)]}


def test_same_video_different_export_cannot_share_indices():
    m=manifest();result={'frame_binding':frame_binding(m)}
    assert require_frame_binding(m,result)['frame_count']==3
    changed=deepcopy(m);changed['frames']=changed['frames'][1:]
    with pytest.raises(ValueError,match='frame_export_mismatch'):require_frame_binding(changed,result)
    changed=deepcopy(m);changed['frames'][0]['sha256']='f'*64
    with pytest.raises(ValueError,match='frame_export_mismatch'):require_frame_binding(changed,result)
    with pytest.raises(ValueError,match='frame_export_mismatch'):require_frame_binding(m,{})


@pytest.mark.parametrize('pts',[90000,80000,110000,True])
def test_invalid_decoded_clock_rejected(pts):
    m=manifest();m['frames'][1]['pts']=pts
    with pytest.raises(ValueError):frame_binding(m)
