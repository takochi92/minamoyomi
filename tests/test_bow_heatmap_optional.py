"""Optional CPU research dependencies are not production requirements."""
import json
import pytest


def dependencies():
    torch=pytest.importorskip('torch')
    cv2=pytest.importorskip('cv2')
    if not hasattr(cv2,'warpAffine'):pytest.skip('OpenCV runtime unavailable')
    return torch


def test_heatmap_keeps_image_coordinates_and_rejects_uninformative_image():
    torch=dependencies()
    import numpy as np
    from tools.bow_keypoint import make_model,locate,usable_prediction
    model=make_model().eval()
    assert tuple(model(torch.zeros(2,4,64,64)).shape)==(2,1,64,64)
    # An untrained, uniform heatmap must not qualify merely because argmax exists.
    for parameter in model.parameters():parameter.data.zero_()
    result=locate(model,np.zeros((400,500,3),np.uint8),[250,200],'A')
    assert not usable_prediction(result)
    assert locate(model,np.zeros((100,100,3),np.uint8),[0,0],'A')['point'] is None


def test_training_refuses_heldout_labels_before_opening_dataset(tmp_path):
    dependencies()
    from tools.bow_keypoint import train
    meta=tmp_path/'meta.json';meta.write_text(json.dumps({'examples':[{'split':'train','race':3}]}))
    with pytest.raises(ValueError,match='training_race_leakage'):
        train(tmp_path/'absent.npz',meta,tmp_path/'weights.pt',steps=1)


def test_changed_private_weights_refused_before_deserializing(tmp_path):
    dependencies()
    from tools.bow_keypoint import load_model
    weights=tmp_path/'bad.pt';weights.write_bytes(b'changed')
    weights.with_suffix('.json').write_text(json.dumps({'weights_sha256':'0'*64}))
    with pytest.raises(ValueError,match='keypoint_weights_changed'):load_model(weights)
