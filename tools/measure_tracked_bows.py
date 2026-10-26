"""Private learned bow proposals on continuous actor tracks; no release authority."""
from __future__ import annotations
import argparse,hashlib,json,math,time
from pathlib import Path
from scraper.turn_measurement import crossing
from tools.frame_binding import require_frame_binding
from tools.bow_keypoint import load_model,locate,usable_prediction
from tools.boat_tracking import flow_consistent


def gate_candidates(points,gate,*,flow_check):
    """Only adjacent decoded frames can define a crossing; never bridge missing detections."""
    candidates=[]
    for a,b in zip(points,points[1:]):
        dt=b['time']-a['time']
        if b['frame']!=a['frame']+1 or not 0<dt<=.12:continue
        if math.dist(a['point'],b['point'])>1500*dt:continue
        when=crossing({'time':a['time'],'x':a['point'][0],'y':a['point'][1]},
                      {'time':b['time'],'x':b['point'][0],'y':b['point'][1]},gate)
        if when is None or not flow_check(a,b):continue
        candidates.append({'time':when,'before_frame':a['frame'],'after_frame':b['frame'],
                           'before_pts':a['pts'],'after_pts':b['pts'],'points':[a['point'],b['point']]})
    # A second crossing is ambiguous even if it occurs very close to the first.
    return candidates


def measure(folder,tracks_path,weights):
    import cv2
    cv2.setNumThreads(1);started=time.monotonic();folder=Path(folder)
    manifest=json.loads((folder/'frames.json').read_text());frames=manifest['frames'];base=manifest['source']['time_base']
    tracks=json.loads(Path(tracks_path).read_text());binding=require_frame_binding(manifest,tracks)
    model=load_model(weights);cache={}
    def image(i):
        if type(i) is not int or not 0<=i<len(frames):raise ValueError('invalid_frame_index')
        if i not in cache:
            path=(folder/frames[i]['file']).resolve()
            if folder.resolve() not in path.parents:raise ValueError('invalid_frame_path')
            if hashlib.sha256(path.read_bytes()).hexdigest()!=frames[i]['sha256']:raise ValueError('source_frame_changed')
            cache[i]=cv2.imread(str(path))
            if cache[i] is None or cache[i].shape[:2]!=(1080,1920):raise ValueError('invalid_source_frame')
            if len(cache)>40:del cache[next(iter(cache))]
        return cache[i]
    gates=json.loads((Path(__file__).resolve().parents[1]/'scraper/exhibition_model/pilot-v1.json').read_text())['gates']
    results=[]
    for track in tracks['tracks']:
        events={};diagnostics={};reasons=[]
        for name,gate in gates.items():
            observations=[];attempts=0;rejected=0
            for row in track['frames']:
                i=row['frame'];pts=frames[i]['pts']
                if row.get('pts')!=pts:raise ValueError('track_pts_mismatch')
                x,y,w,h=row['box']
                coarse=[x+w,y+.2*h] if name=='A' else [x,y+(.3 if name=='B' else .55)*h]
                axis=0 if gate['axis']=='x' else 1;other=1-axis
                if abs(coarse[axis]-gate['value'])>75 or not gate['segment'][0]-75<=coarse[other]<=gate['segment'][1]+75:continue
                attempts+=1;prediction=locate(model,image(i),coarse,name)
                if not usable_prediction(prediction):rejected+=1;continue
                px,py=prediction['point']
                if not x-25<=px<=x+w+25 or not y-25<=py<=y+h+25:rejected+=1;continue
                observations.append({'frame':i,'pts':pts,'time':pts*base[0]/base[1],**prediction})
            def flow(a,b):
                return flow_consistent(cv2.cvtColor(image(a['frame']),cv2.COLOR_BGR2GRAY),
                                       cv2.cvtColor(image(b['frame']),cv2.COLOR_BGR2GRAY),a['point'],b['point'])
            candidates=gate_candidates(observations,gate,flow_check=flow)
            diagnostics[name]={'attempts':attempts,'rejected_points':rejected,'observations':observations,'crossings':candidates}
            if len(candidates)==1:events[name]=candidates[0]
            else:reasons.append(('missing_' if not candidates else 'ambiguous_')+name)
        if len(events)==3 and not events['A']['time']<events['B']['time']<events['C']['time']:reasons.append('invalid_gate_order')
        result={'boat':track['boat'],'status':'automatic_candidate' if not reasons else 'rejected',
                'events':events,'reasons':reasons,'diagnostics':diagnostics,'identity_independently_verified':False}
        if not reasons:
            result.update(entry_video_seconds=events['B']['time']-events['A']['time'],
                          exit_video_seconds=events['C']['time']-events['B']['time'])
        results.append(result)
    return {'method':'continuous-actor-learned-bow-research-v1','frame_binding':binding,'results':results,
            'weights_sha256':hashlib.sha256(Path(weights).read_bytes()).hexdigest(),
            'track_result_sha256':hashlib.sha256(Path(tracks_path).read_bytes()).hexdigest(),
            'implementation_sha256':hashlib.sha256(Path(__file__).read_bytes().replace(b'\r\n',b'\n')).hexdigest(),
            'elapsed_seconds':round(time.monotonic()-started,2),'publication_ready':False,'prediction_used':False,
            'camera_calibrated':False,'real_time_scale_verified':False,'independent_identity_review_complete':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('frames','tracks','weights','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();result=measure(args.frames,args.tracks,args.weights)
    args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({'boats':[{k:r.get(k) for k in ('boat','status','reasons','entry_video_seconds','exit_video_seconds')} for r in result['results']],
                      'publication_ready':False,'elapsed_seconds':result['elapsed_seconds']}))
