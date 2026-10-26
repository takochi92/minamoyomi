from tools.actor_track_review import overlap,entry_connected_track,choose_seeds,supporting_rider


def test_only_spatially_overlapping_actor_boxes_can_match():
    assert overlap([10,10,100,40],[10,10,100,40])==1
    assert overlap([10,10,100,40],[200,10,100,40])==0
    assert 0<overlap([10,10,100,40],[50,10,100,40])<1


def attempt(gate,start,end,x):
    return {'gate':gate,'frames':[{'frame':i,'box':[x,10,100,40]} for i in range(start,end)]}


def test_longer_wrong_boat_cannot_replace_physically_connected_entry_identity():
    a=attempt('A',0,30,10);b=attempt('B',15,55,12);wrong=attempt('C',0,100,400)
    primary,connected=entry_connected_track([a,b,wrong])
    assert primary is b and connected==[0,1]
    assert entry_connected_track([b,wrong])==(None,[])


def test_one_overlapping_frame_is_not_a_continuous_association():
    a=attempt('A',0,30,10);b=attempt('B',29,80,10)
    primary,connected=entry_connected_track([a,b])
    assert primary is a and connected==[0]


def test_separate_colour_candidates_survive_until_physical_association():
    options=[(.8,10,[], 'A',10,True),(.2,20,[], 'A',20,True),
             (.11,100,[], 'B',100,True),(.09,60,[], 'B',60,True),
             (.10,30,[], 'B',30,False),(.08,61,[], 'B',60,True)]
    selected=choose_seeds(options)
    assert [s[1] for s in selected]==[10,100,60]


def test_flow_support_requires_an_observed_rider_inside_the_tracked_actor():
    person={'class':0,'score':.7,'box':[50,35,20,30]}
    assert supporting_rider([person],[40,40,60,50])
    assert not supporting_rider([person],[200,40,60,50])
    assert not supporting_rider([{**person,'class':8}],[40,40,60,50])


def test_partial_tracks_may_join_only_at_adjacent_observed_frames():
    a=attempt('A',0,30,10);b=attempt('B',30,60,14)
    assert entry_connected_track([a,b])[1]==[0,1]
    assert entry_connected_track([a,attempt('B',31,60,14)])[1]==[0]
    assert entry_connected_track([a,attempt('B',30,60,400)])[1]==[0]
