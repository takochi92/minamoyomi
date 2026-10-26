import copy,json,math,shutil
import pytest
from tools.automatic_turn import load_model,combine_candidates,scene_intervals


def synthetic():
    from tools.automatic_turn import MODEL
    config=json.loads((MODEL/'pilot-v1.json').read_text())
    frames=[{'index':1000+i,'time':i/30,'pts':i*3000} for i in range(150)]
    tracks={g:[] for g in 'ABC'}
    for gate,event in zip('ABC',[1,2,3]):
        rule=config['gates'][gate]
        for frame in frames:
            t=frame['time'];d=t-event
            point=[rule['value']+rule['direction']*d*100,800] if rule['axis']=='x' else [1200,rule['value']+rule['direction']*d*100]
            if gate=='C':point[1]=350
            tracks[gate].append({'score':.1+.85*math.exp(-(d/.2)**2),'point':point,'boat':3 if abs(d)<.4 else None})
    return config,frames,tracks


def test_identity_does_not_come_from_passage_order_and_no_formal_publication():
    config,frames,tracks=synthetic();report=combine_candidates(frames,tracks,config)
    accepted=[r for r in report['results'] if r['status']=='automatic_candidate']
    assert [r['boat'] for r in accepted]==[3]
    assert accepted[0]['entry_video_seconds']==accepted[0]['exit_video_seconds']==1
    assert not report['publication_ready'] and not report['prediction_used']
    assert not report['identity_assumed_from_passage_order']


def test_missing_or_changed_identity_never_gets_invented_times():
    config,frames,tracks=synthetic()
    for p in tracks['B']:p['boat']=None
    row=combine_candidates(frames,tracks,config)['results'][2]
    assert row['status']=='rejected' and 'missing_B' in row['reasons']
    assert 'entry_video_seconds' not in row


def test_distinct_crossings_of_same_colour_are_ambiguous():
    config,frames,tracks=synthetic()
    for i in range(71,78):
        tracks['C'][i]={'score':.82,'point':[750-(i-74)*4,350],'boat':3}
    row=combine_candidates(frames,tracks,config)['results'][2]
    assert row['status']=='rejected' and 'ambiguous_C' in row['reasons']
    assert 'exit_video_seconds' not in row


def test_clock_reversal_and_incomplete_tracks_are_rejected():
    config,frames,tracks=synthetic();frames[30]['time']=frames[29]['time']
    with pytest.raises(ValueError,match='clock'):combine_candidates(frames,tracks,config)
    config,frames,tracks=synthetic();tracks['B'].pop()
    with pytest.raises(ValueError,match='clock'):combine_candidates(frames,tracks,config)


def test_scene_selection_is_unique_only_when_exactly_one_caption_interval_exists():
    samples=[(i,.95 if 20<=i<52 else 0) for i in range(120)]
    assert scene_intervals(samples)==[(20,52)]
    samples=[(i,.95 if 5<=i<28 or 60<=i<90 else 0) for i in range(120)]
    assert len(scene_intervals(samples))==2  # caller must reject ambiguous selection


def test_model_tampering_is_not_silently_accepted(tmp_path):
    from tools.automatic_turn import MODEL
    import numpy as np,hashlib
    # Integrity checks use synthetic arrays; original-image templates are private.
    np.savez_compressed(tmp_path/'pilot-v1.npz',**{**{'templates_'+g:np.zeros((6,73,73),dtype=np.uint8) for g in 'ABC'},'caption_blue':np.ones((130,820),dtype=bool)})
    config=json.loads((MODEL/'pilot-v1.json').read_text())
    config['templates_sha256']=hashlib.sha256((tmp_path/'pilot-v1.npz').read_bytes()).hexdigest()
    body={k:v for k,v in config.items() if k!='model_fingerprint'}
    config['model_fingerprint']=hashlib.sha256(json.dumps(body,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    (tmp_path/'pilot-v1.json').write_text(json.dumps(config))
    load_model(tmp_path)
    config=json.loads((tmp_path/'pilot-v1.json').read_text())
    config['min_match_score']=.01
    (tmp_path/'pilot-v1.json').write_text(json.dumps(config))
    with pytest.raises(ValueError,match='settings_changed'):load_model(tmp_path)


@pytest.mark.parametrize('boat,bgr',[(1,[255,255,255]),(2,[0,0,0]),(3,[0,0,255]),(4,[255,0,0]),(5,[0,255,255]),(6,[0,160,0])])
def test_standard_boat_colour_mapping(boat,bgr):
    cv2=pytest.importorskip('cv2')
    if not hasattr(cv2,'cvtColor'):pytest.skip('optional OpenCV runtime unavailable')
    import numpy as np
    from tools.automatic_turn import identify_helmet
    from tools.automatic_turn import MODEL
    config=json.loads((MODEL/'pilot-v1.json').read_text())
    image=np.empty((600,600,3),dtype=np.uint8);image[:]=bgr
    assert identify_helmet(image,[200,200],'A',config)==boat
