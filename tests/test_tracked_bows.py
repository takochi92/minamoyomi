from tools.measure_tracked_bows import gate_candidates
from tools.bow_keypoint import usable_prediction

GATE={'axis':'x','value':100,'direction':1,'segment':[0,200]}


def point(frame,x):return {'frame':frame,'pts':frame*3000,'time':frame/30,'point':[x,100]}


def test_crossing_uses_original_pts_and_requires_tracking_agreement():
    rows=[point(10,99),point(11,101)]
    assert abs(gate_candidates(rows,GATE,flow_check=lambda a,b:True)[0]['time']-.35)<1e-10
    assert not gate_candidates(rows,GATE,flow_check=lambda a,b:False)


def test_missing_frames_and_jumps_cannot_create_measurements():
    assert not gate_candidates([point(10,99),point(12,101)],GATE,flow_check=lambda a,b:True)
    assert not gate_candidates([point(10,0),point(11,200)],GATE,flow_check=lambda a,b:True)
    assert len(gate_candidates([point(10,99),point(11,101),point(12,99),point(13,101)],GATE,flow_check=lambda a,b:True))==2


def test_keypoint_confidence_rejects_nonfinite_or_inconsistent_crops():
    result={'point':[1,2],'crop_spread_pixels':2,'mean_peak_mass':.2}
    assert usable_prediction(result)
    for change in ({'point':[float('nan'),2]},{'point':[True,2]},{'point':['1',2]},
                   {'crop_spread_pixels':9},{'mean_peak_mass':.001},{'point':None}):
        assert not usable_prediction({**result,**change})
