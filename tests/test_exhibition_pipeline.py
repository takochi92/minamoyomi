import hashlib,json
from pathlib import Path
import pytest
from tools.exhibition_pipeline import run,exclusive,research_analyzer


def setting(day):
    return {'races':{f'{r:02}':{'race_number':f'{r:02}','ref_id':f'mix-04heiwajima-exhibition-{day}-{r:02}',
                              'source_type':'mix'} for r in (1,2)}}


def capture(day,race,target):
    target.mkdir();video=target/'replay.ts';video.write_bytes(f'{day}-{race}'.encode())
    return video,{'date':day,'jcd':'04','rno':race,'source_sha256':hashlib.sha256(video.read_bytes()).hexdigest()}


def analyze(video):
    return {'source_sha256':hashlib.sha256(video.read_bytes()).hexdigest(),'publication_ready':False,
            'prediction_used':False,'model_fingerprint':'frozen-test-model','results':[]}


def test_worker_is_bounded_and_never_recaptures_completed_races(tmp_path):
    args={'source_loader':setting,'capturer':capture,'analyzer':analyze,'limit':1}
    first=run('20261026',tmp_path,**args)
    assert first['processed']==first['candidate_races']==1 and not first['publication_performed']
    assert run('20261026',tmp_path,**args)['candidate_races']==2
    assert run('20261026',tmp_path,**args)['processed']==0
    assert run('20261027',tmp_path,**args)['processed']==1
    assert not (tmp_path/'20261026'/'race-01-attempt-2').exists()


def test_denial_halts_remaining_races_and_future_scheduled_runs(tmp_path):
    calls=[]
    def denied(day,race,target):
        calls.append(race);error=ValueError('official_master_not_observed')
        error.safe_diagnostics={'http_statuses':{'playback.api.streaks.jp':[403]}}
        raise error
    args={'source_loader':setting,'capturer':denied,'analyzer':analyze}
    assert run('20261026',tmp_path,**args)['state']=='blocked_access'
    assert run('20261027',tmp_path,**args)['processed']==0 and calls==[1]


def test_captured_video_is_reused_after_analysis_failure(tmp_path):
    def failed(_):raise ValueError('first_lap_scene_not_unique')
    args={'source_loader':setting,'capturer':capture,'limit':1}
    run('20261026',tmp_path,analyzer=failed,**args)
    state_path=tmp_path/'20261026'/'state.json';state=json.loads(state_path.read_text())
    state['races']['1']['retry_after']=0;state_path.write_text(json.dumps(state))
    def should_not_capture(*_):raise AssertionError('repeated capture')
    result=run('20261026',tmp_path,source_loader=setting,capturer=should_not_capture,analyzer=analyze,limit=1)
    assert result['candidate_races']==1


def test_changed_media_cannot_be_used_for_analysis(tmp_path):
    def corrupt(day,race,target):
        video,receipt=capture(day,race,target);video.write_bytes(b'changed');return video,receipt
    run('20261026',tmp_path,source_loader=setting,capturer=corrupt,analyzer=analyze,limit=1)
    state=json.loads((tmp_path/'20261026'/'state.json').read_text())
    assert state['races']['1']['error']=='capture_fingerprint_changed'
    assert not (tmp_path/'20261026'/'race-01-candidates.json').exists()


def test_worker_lock_rejects_concurrent_execution_and_releases(tmp_path):
    lock=tmp_path/'worker.lock'
    with exclusive(lock):
        with pytest.raises(OSError):
            with exclusive(lock):pass
    with exclusive(lock):pass


def test_private_v2_requires_all_models_before_runner_can_capture(tmp_path):
    with pytest.raises(ValueError,match='private_research_models_required'):research_analyzer(tmp_path,tmp_path)


def test_private_v2_connects_local_stages_without_enabling_publication(tmp_path,monkeypatch):
    from tools import automatic_turn_v2
    for name in ('yolox-s.onnx','colour-v2.json','bow-v2.npz','pilot-v1.npz','bow-heatmap-bound-v1.pt'):
        (tmp_path/name).write_bytes(b'test')
    calls=[]
    def local(*args,**kwargs):
        calls.append((args,kwargs))
        return {'publication_ready':False,'prediction_used':False,'results':[],
                'learned_bow_review':{'publication_ready':False,'results':[]}}
    monkeypatch.setattr(automatic_turn_v2,'analyze_video',local)
    result=research_analyzer(tmp_path,tmp_path)(tmp_path/'test.ts')
    assert len(calls)==1 and calls[0][1]['keypoint_weights']==tmp_path/'bow-heatmap-bound-v1.pt'
    assert result['analysis_mode']=='integrated_private_research_v2' and not result['publication_ready']
    assert len(result['model_fingerprint'])==64 and len(result['model_recipe']['models'])==5
    analyzer=research_analyzer(tmp_path,tmp_path)
    (tmp_path/'bow-heatmap-bound-v1.pt').write_bytes(b'changed')
    with pytest.raises(ValueError,match='private_research_models_changed'):analyzer(tmp_path/'test.ts')
    assert len(calls)==1
