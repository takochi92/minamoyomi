"""Experimental CPU-only bow proposals. Never formal times or prediction inputs.

Boat identity is inferred from helmet colour at all three gates, not passage
order. Missing or ambiguous crossings suppress the whole boat's intervals.
"""
from __future__ import annotations
import hashlib,json,math,shutil,subprocess,time
from pathlib import Path
from scraper.turn_measurement import crossing

MODEL=Path(__file__).resolve().parents[1]/'scraper/exhibition_model'


def load_model(directory=MODEL):
    import numpy as np
    directory=Path(directory)
    config=json.loads((directory/'pilot-v1.json').read_text(encoding='utf-8'))
    implementation=hashlib.sha256(Path(__file__).read_bytes().replace(b'\r\n',b'\n')).hexdigest()
    if implementation!=config.get('implementation_sha256'):
        raise ValueError('model_implementation_changed')
    path=directory/'pilot-v1.npz'
    if hashlib.sha256(path.read_bytes()).hexdigest()!=config['templates_sha256']:
        raise ValueError('model_fingerprint_mismatch')
    claimed=config['model_fingerprint'];body={k:v for k,v in config.items() if k!='model_fingerprint'}
    if hashlib.sha256(json.dumps(body,sort_keys=True,separators=(',',':')).encode()).hexdigest()!=claimed:
        raise ValueError('model_settings_changed')
    with np.load(path,allow_pickle=False) as data:arrays={k:data[k] for k in data.files}
    if (any(arrays['templates_'+g].shape!=(6,73,73) for g in 'ABC')
            or arrays['caption_blue'].shape!=(130,820)):
        raise ValueError('invalid_model_dimensions')
    return config,arrays


def identify_helmet(image,point,gate,config):
    import cv2
    x,y=point;dx,dy,w,h=config['helmet_rois'][gate]
    x0,y0=round(x+dx-w/2),round(y+dy-h/2)
    if x0<0 or y0<0 or x0+w>image.shape[1] or y0+h>image.shape[0]:return None
    hsv=cv2.cvtColor(image[y0:y0+h,x0:x0+w],cv2.COLOR_BGR2HSV);H,S,V=cv2.split(hsv)
    counts={3:int((((H<10)|(H>170))&(S>80)&(V>70)).sum()),
            4:int(((H>=90)&(H<=135)&(S>80)&(V>70)).sum()),
            5:int(((H>=18)&(H<=40)&(S>80)&(V>70)).sum()),
            6:int(((H>40)&(H<90)&(S>70)&(V>60)).sum())}
    ranked=sorted(counts,key=counts.get,reverse=True)
    black=int(((S<100)&(V<55)).sum());white=int(((S<70)&(V>170)).sum())
    if counts[ranked[0]]>=10 and counts[ranked[0]]>=1.5*max(counts[ranked[1]],1) and counts[ranked[0]]>black:return ranked[0]
    if white>=30 and white>2*black:return 1
    if black>=30 and black>2*white:return 2
    return None


def caption_score(rgb,mask):
    import numpy as np
    pixels=rgb.astype(np.int16)
    blue=(pixels[:,:,2]>pixels[:,:,0]*1.3)&(pixels[:,:,2]>pixels[:,:,1]*1.15)&(pixels[:,:,2]>110)
    count=int(blue.sum())
    return (float((blue&mask).sum())/math.sqrt(max(count,1)*int(mask.sum()))) if count>=700 else 0.0


def scene_intervals(samples,min_score=.7):
    """Only scene selection, never a 1fps measurement clock."""
    groups=[]
    for when,score in samples:
        if score<min_score:continue
        if groups and 0<when-groups[-1][-1]<=1.2:groups[-1].append(when)
        else:groups.append([when])
    return [(g[0],g[-1]+1) for g in groups if 18<=g[-1]-g[0]+1<=45]


def combine_candidates(frames,tracks,config):
    """Pure geometry/identity validation; never infer identity from order."""
    from scipy.signal import find_peaks
    import numpy as np
    times=[f['time'] for f in frames]
    if len(times)<2 or any(not math.isfinite(t) for t in times) or any(b<=a for a,b in zip(times,times[1:])):
        raise ValueError('invalid_frame_clock')
    step=float(np.median(np.diff(times)))
    distance=max(1,math.ceil(config['min_peak_separation_seconds']/step))
    groups={(b,g):[] for b in range(1,7) for g in 'ABC'}
    peaks_report={}
    for gate in 'ABC':
        rows=tracks[gate]
        if len(rows)!=len(frames):raise ValueError('incomplete_track_clock')
        peaks,_=find_peaks([p['score'] for p in rows],height=config['peak_height'],
                           prominence=config['peak_prominence'],distance=distance)
        peaks_report[gate]=len(peaks)
        used=set()
        for peak in peaks:
            for i in range(max(0,int(peak)-math.ceil(1/step)),min(len(rows)-1,int(peak)+math.ceil(1/step))):
                a,b=rows[i:i+2];delta=times[i+1]-times[i]
                identity=a.get('boat')
                if (identity not in range(1,7) or type(identity) is not int or b.get('boat')!=identity
                        or min(a['score'],b['score'])<config['min_match_score'] or not 0<delta<=config['max_pair_gap_seconds']):continue
                p,q=a['point'],b['point']
                if any(not math.isfinite(v) for v in p+q) or math.hypot(q[0]-p[0],q[1]-p[1])>config['max_point_velocity_pixels_per_second']*delta:continue
                event=crossing({'time':times[i],'x':p[0],'y':p[1]},{'time':times[i+1],'x':q[0],'y':q[1]},config['gates'][gate])
                key=(identity,i)
                if event is None or key in used:continue
                used.add(key);groups[(identity,gate)].append({'time':event,'score':min(a['score'],b['score']),
                    'frames':[frames[i]['index'],frames[i+1]['index']],'points':[p,q],'boat':identity})
    results=[]
    for boat in range(1,7):
        events={};reasons=[]
        for gate in 'ABC':
            candidates=groups[(boat,gate)]
            if not candidates:reasons.append('missing_'+gate);continue
            if max(c['time'] for c in candidates)-min(c['time'] for c in candidates)>config['max_candidate_time_span_seconds']:
                reasons.append('ambiguous_'+gate);continue
            events[gate]=max(candidates,key=lambda c:c['score'])
        if len(events)==3 and not events['A']['time']<events['B']['time']<events['C']['time']:reasons.append('invalid_gate_order')
        if len(events)==3 and not all(.3<=events[b]['time']-events[a]['time']<=10 for a,b in [('A','B'),('B','C')]):reasons.append('implausible_interval')
        row={'boat':boat,'status':'rejected' if reasons else 'automatic_candidate','reasons':reasons,'events':events}
        if not reasons:
            row['entry_video_seconds']=round(events['B']['time']-events['A']['time'],1)
            row['exit_video_seconds']=round(events['C']['time']-events['B']['time'],1)
        results.append(row)
    return {'results':results,'gate_peak_counts':peaks_report,'publication_ready':False,'prediction_used':False,
            'identity_assumed_from_passage_order':False}


def analyze(video,model_dir=MODEL):
    import cv2
    config,arrays=load_model(model_dir);cv2.setNumThreads(1)
    video=Path(video).resolve();started=time.monotonic()
    if not video.is_file() or video.suffix.lower() not in ('.ts','.mp4','.mkv'):raise ValueError('local_video_required')
    probe=subprocess.run([shutil.which('ffprobe'),'-v','error','-protocol_whitelist','file,pipe','-select_streams','v:0',
        '-show_entries','stream=time_base,width,height:frame=pts','-show_frames','-of','json',str(video)],capture_output=True,text=True,check=True,timeout=120)
    metadata=json.loads(probe.stdout);stream=metadata['streams'][0]
    if [stream['width'],stream['height']]!=config['image_size']:raise ValueError('unsupported_camera_dimensions')
    num,den=map(int,stream['time_base'].split('/'));pts=[f['pts'] for f in metadata['frames']]
    if not pts or len(pts)>6000 or any(type(p) is not int for p in pts) or any(b<=a for a,b in zip(pts,pts[1:])):raise ValueError('invalid_decoded_pts')
    times=[p*num/den for p in pts];origin=times[0]
    cap=cv2.VideoCapture(str(video));samples=[];index=0;next_sample=0
    x,y,w,h=config['caption_roi']
    while True:
        ok,image=cap.read()
        if not ok:break
        if index>=len(times):raise ValueError('decoder_frame_count_changed')
        relative=times[index]-origin
        if relative>=next_sample:
            rgb=cv2.cvtColor(image[y:y+h,x:x+w],cv2.COLOR_BGR2RGB)
            samples.append((relative,caption_score(rgb,arrays['caption_blue'])));next_sample=relative+1-.001
        index+=1
    cap.release()
    if index!=len(times):raise ValueError('decoder_frame_count_changed')
    scenes=scene_intervals(samples,config['min_caption_cosine'])
    if len(scenes)!=1:raise ValueError('first_lap_scene_not_unique')
    start,end=max(0,scenes[0][0]-4),scenes[0][1]+4
    cap=cv2.VideoCapture(str(video));frames=[];tracks={g:[] for g in 'ABC'};index=0
    while True:
        ok,image=cap.read()
        if not ok:break
        if index>=len(times):raise ValueError('decoder_frame_count_changed')
        relative=times[index]-origin
        if relative>end:break
        if relative>=start:
            frames.append({'index':index,'pts':pts[index],'time':times[index]})
            gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
            for gate,g in config['gates'].items():
                half=36
                if g['axis']=='x':x1,x2=int(g['value']-70-half),int(g['value']+70+half);y1,y2=int(g['segment'][0]-half),int(g['segment'][1]+half)
                else:x1,x2=int(g['segment'][0]-half),int(g['segment'][1]+half);y1,y2=int(g['value']-70-half),int(g['value']+70+half)
                roi=gray[y1:y2,x1:x2];best=(-1,None)
                for template in arrays['templates_'+gate]:
                    match=cv2.matchTemplate(roi,template,cv2.TM_CCOEFF_NORMED);_,score,_,location=cv2.minMaxLoc(match)
                    if score>best[0]:best=(score,[location[0]+x1+half,location[1]+y1+half])
                tracks[gate].append({'score':float(best[0]),'point':best[1],'boat':identify_helmet(image,best[1],gate,config)})
        index+=1
    cap.release()
    result=combine_candidates(frames,tracks,config)
    result.update(schema=1,method=config['method'],model_fingerprint=config['model_fingerprint'],
        source_sha256=hashlib.sha256(video.read_bytes()).hexdigest(),source_clock='decoded_pts',
        time_base=[num,den],scene_start_relative_seconds=start,scene_end_relative_seconds=end,
        image_size=config['image_size'],gates=config['gates'],elapsed_seconds=round(time.monotonic()-started,2),
        camera_calibrated=False,real_time_scale_verified=False,reference_only=True,predeadline_verified=False)
    return result
