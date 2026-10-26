from tools.actor_track_review import overlap


def test_only_spatially_overlapping_actor_boxes_can_match():
    assert overlap([10,10,100,40],[10,10,100,40])==1
    assert overlap([10,10,100,40],[200,10,100,40])==0
    assert 0<overlap([10,10,100,40],[50,10,100,40])<1
