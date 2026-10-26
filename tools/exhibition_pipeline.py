"""One bounded worker run for an approved external execution environment.

No scheduler installation, publication, credential extraction or proxy routing.
The current model produces private candidates, never verified public timings.
"""
from __future__ import annotations
import argparse,contextlib,hashlib,json,os,re,time
from pathlib import Path
from scraper.exhibition_views import valid_date
from tools.update_exhibition import fetch_setting,parse_setting
from tools.capture_exhibition import capture


def write(path,value):
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    os.replace(temporary,path)


@contextlib.contextmanager
def exclusive(path):
    with path.open('a+b') as handle:
        handle.seek(0,2)
        if not handle.tell():handle.write(b'0');handle.flush()
        handle.seek(0)
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:yield
        finally:
            handle.seek(0)
            if os.name=='nt':msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(handle,fcntl.LOCK_UN)


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda:source.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def access_denied(error):
    statuses=getattr(error,'safe_diagnostics',{}).get('http_statuses',{})
    return any(code in (401,403) for values in statuses.values() for code in values)


def safe_error(error):
    code=str(error)
    return code if isinstance(error,ValueError) and re.fullmatch('[a-z_]{1,80}',code) else type(error).__name__


def research_analyzer(model_directory,private_root):
    """Explicit opt-in for an approved runner. Does not acquire or publish media."""
    models=Path(model_directory).resolve();root=Path(private_root).resolve()
    names=('yolox-s.onnx','colour-v2.json','bow-v2.npz','pilot-v1.npz','bow-heatmap-bound-v1.pt')
    if not all((models/name).is_file() for name in names):raise ValueError('private_research_models_required')
    repository=Path(__file__).resolve().parents[1]
    modules=('automatic_turn_v2','boat_tracking','actor_track_review','frame_binding','bow_keypoint','measure_tracked_bows')
    recipe={'models':{name:sha(models/name) for name in names},
            'code_lf':{name:hashlib.sha256((repository/f'tools/{name}.py').read_bytes().replace(b'\r\n',b'\n')).hexdigest() for name in modules},
            'gates_config':sha(repository/'scraper/exhibition_model/pilot-v1.json')}
    fingerprint=hashlib.sha256(json.dumps(recipe,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    def analyze_local(video):
        if {name:sha(models/name) for name in names}!=recipe['models']:
            raise ValueError('private_research_models_changed')
        from tools.automatic_turn_v2 import analyze_video
        result=analyze_video(video,root/'decoded-temporary',models/names[0],models/names[1],models/names[2],models/names[3],
                             keypoint_weights=models/names[4])
        result['analysis_mode']='integrated_private_research_v2'
        result['model_fingerprint']=fingerprint
        result['model_recipe']=recipe
        # Keep the gate-local and continuous-stage outcomes separately visible.
        # Neither one grants authority to publish a measured result.
        return result
    return analyze_local


def run(day,private_root,*,limit=2,source_loader=fetch_setting,capturer=capture,analyzer=None):
    if not valid_date(day) or type(limit) is not int or not 1<=limit<=12:raise ValueError('invalid_worker_arguments')
    root=Path(private_root).resolve()
    public=Path(__file__).resolve().parents[1]/'site'
    if root==public or public in root.parents:raise ValueError('private_storage_required')
    root.mkdir(parents=True,exist_ok=True)
    with exclusive(root/'worker.lock'):
        block=root/'access-block.json'
        if block.exists():return {'state':'blocked_access','date':day,'processed':0,'publication_performed':False}
        folder=root/day;folder.mkdir(exist_ok=True);state_path=folder/'state.json'
        state=json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {'schema':1,'date':day,'races':{}}
        if state.get('date')!=day or state.get('schema')!=1:raise ValueError('invalid_worker_state')
        if analyzer is None:
            from tools.automatic_turn import analyze
            analyzer=analyze
        available=parse_setting(source_loader(day),day)
        processed=0
        for source in available:
            race=source['rno'];key=str(race);previous=state['races'].get(key,{})
            if previous.get('state')=='analyzed_candidate':continue
            if previous.get('attempts',0)>=3 or time.time()<previous.get('retry_after',0):continue
            if processed>=limit:break
            processed+=1;item={'state':'pending','attempts':previous.get('attempts',0)+1}
            state['races'][key]=item
            # Each attempt has its own folder: interrupted/failed imports never get overwritten.
            destination=folder/f'race-{race:02}-attempt-{item["attempts"]}'
            try:
                cache=folder/f'race-{race:02}-capture.json'
                if cache.exists():
                    receipt=json.loads(cache.read_text(encoding='utf-8'))
                    relative=Path(receipt['video'])
                    if relative.is_absolute() or '..' in relative.parts:raise ValueError('invalid_capture_cache')
                    video=(folder/relative).resolve()
                    if folder not in video.parents:raise ValueError('invalid_capture_cache')
                    summary=receipt['summary']
                else:
                    video,summary=capturer(day,race,destination);video=Path(video).resolve()
                    if folder not in video.parents:raise ValueError('capture_outside_private_storage')
                if (summary.get('date'),summary.get('jcd'),summary.get('rno'))!=(day,'04',race):
                    raise ValueError('capture_race_mismatch')
                fingerprint=sha(video)
                if fingerprint!=summary.get('source_sha256'):raise ValueError('capture_fingerprint_changed')
                write(cache,{'video':str(video.relative_to(folder)),'summary':summary})
                item.update(state='captured',source_sha256=fingerprint);write(state_path,state)
                result=analyzer(video)
                if (result.get('source_sha256')!=fingerprint or result.get('publication_ready') is not False
                        or result.get('prediction_used') is not False):raise ValueError('invalid_analysis_receipt')
                write(folder/f'race-{race:02}-candidates.json',result)
                item.update(state='analyzed_candidate',model_fingerprint=result.get('model_fingerprint'),
                            accepted_boats=sum(r.get('status')=='automatic_candidate' for r in result.get('results',[])))
                if result.get('analysis_mode')=='integrated_private_research_v2':
                    item['analysis_mode']=result['analysis_mode']
                    item['continuous_candidate_boats']=sum(r.get('status')=='automatic_candidate'
                        for r in result.get('learned_bow_review',{}).get('results',[]))
            except Exception as error:
                item.update(state='failed',error=safe_error(error),retry_after=time.time()+900)
                if access_denied(error):
                    item['state']='blocked_access'
                    write(block,{'date':day,'rno':race,'state':'blocked_access',
                                 'diagnostics':getattr(error,'safe_diagnostics',{})})
            write(state_path,state)
            if item['state']=='blocked_access':break
        return {'state':'blocked_access' if block.exists() else 'completed_run','date':day,
                'registered_races':len(available),'processed':processed,
                'candidate_races':sum(r.get('state')=='analyzed_candidate' for r in state['races'].values()),
                'publication_performed':False,'automatic_verified_timing_enabled':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date',required=True);parser.add_argument('--private-root',type=Path,required=True)
    parser.add_argument('--limit',type=int,default=2)
    parser.add_argument('--research-model-dir',type=Path,
                        help='Optional private integrated v2 models; only for an approved acquisition environment')
    args=parser.parse_args()
    try:
        analyzer=research_analyzer(args.research_model_dir,args.private_root) if args.research_model_dir else None
        print(json.dumps(run(args.date,args.private_root,limit=args.limit,analyzer=analyzer)))
    except Exception as error:
        print(json.dumps({'state':'failed','error':safe_error(error),'publication_performed':False}))
        raise SystemExit(1)
