import math
import pytest
from tools.boat_tracking import rider_region,identify_colour,temporal_identity,flow_consistent,track_actor


def test_mark_misdetected_as_boat_cannot_be_a_rider_region():
    mark={'box':[1090,519,48,43],'class':8,'score':.99}
    boat={'box':[1150,535,110,45],'class':8,'score':.7}
    region=rider_region([mark,boat],[1155,550],'B')
    assert region and region['kind']=='boat' and region['box'][0]>1150
    assert rider_region([mark],[1155,550],'B') is None


def test_detected_person_is_preferred_to_hull_white_pixels():
    person={'box':[1190,520,60,50],'class':0,'score':.6}
    boat={'box':[1150,535,110,45],'class':8,'score':.9}
    assert rider_region([boat,person],[1155,550],'B')['kind']=='person'


def test_ambiguous_colour_does_not_inherit_passage_order():
    prototypes={str(boat):[[int(j==feature) for j in range(6)]] for boat,feature in [(1,5),(2,4),(3,0),(4,1),(5,2),(6,3)]}
    assert identify_colour([0,1,0,0,0,0],prototypes)['boat']==4
    assert identify_colour([0,0,0,0,0,0],prototypes)['boat'] is None
    assert identify_colour([float('nan')]*6,prototypes)['boat'] is None


def test_unknown_colour_observations_do_not_invent_votes_or_break_valid_motion():
    rows=[{'time':i*.1,'point':[100+i*10,200],'boat':5 if i<3 else None} for i in range(5)]
    assert temporal_identity(rows)==5
    rows[2]['boat']=None
    assert temporal_identity(rows) is None


def test_consistent_colours_require_a_continuous_physical_track():
    rows=[{'time':i*.1,'point':[100+i*10,200],'boat':4} for i in range(5)]
    assert temporal_identity(rows)==4
    assert temporal_identity(rows[:2]) is None
    rows[2]['point']=[1000,900]
    assert temporal_identity(rows) is None
    rows[2]['point']=[120,200];rows[2]['time']=float('nan')
    assert temporal_identity(rows) is None


def test_identity_changes_and_time_gaps_are_rejected():
    rows=[{'time':i*.1,'point':[100+i,200],'boat':3 if i<3 else 6} for i in range(5)]
    assert temporal_identity(rows) is None
    rows=[{'time':i,'point':[100+i,200],'boat':1} for i in range(3)]
    assert temporal_identity(rows) is None


def test_optical_flow_must_agree_with_proposed_bow_displacement():
    cv2=pytest.importorskip('cv2');np=pytest.importorskip('numpy')
    if not hasattr(cv2,'calcOpticalFlowPyrLK'):pytest.skip('optional OpenCV unavailable')
    rng=np.random.default_rng(41);a=rng.integers(0,256,(100,100),dtype=np.uint8)
    b=cv2.warpAffine(a,np.float32([[1,0,3],[0,1,1]]),(100,100))
    assert flow_consistent(a,b,[50,50],[53,51])
    assert not flow_consistent(a,b,[50,50],[65,51])


def test_actor_tracking_moves_in_both_directions_and_stops_when_features_disappear():
    cv2=pytest.importorskip('cv2');np=pytest.importorskip('numpy')
    if not hasattr(cv2,'calcOpticalFlowPyrLK'):pytest.skip('optional OpenCV unavailable')
    rng=np.random.default_rng(10);texture=rng.integers(20,240,(40,40),dtype=np.uint8)
    frames=[]
    for i in range(9):
        image=np.zeros((160,200,3),np.uint8)+60
        image[60:100,50+2*i:90+2*i]=texture[:,:,None]
        frames.append(image)
    rows=track_actor(lambda i:frames[i],4,[58,60,40,40],len(frames),max_steps=4)
    assert rows[0]['frame']<4<rows[-1]['frame']
    for row in rows:assert abs(row['box'][0]-(50+2*row['frame']))<3
    flat=np.zeros_like(frames[0])+60
    assert len(track_actor(lambda i:flat,4,[58,60,40,40],9,max_steps=4))==1
