"""Experimental detector + temporal colour + bow-flow validation. No publication."""
from __future__ import annotations
import argparse,hashlib,json,math,shutil,subprocess,tempfile,time
from pathlib import Path
from scraper.turn_measurement import crossing
from tools.boat_tracking import rider_region,colour_features,identify_colour,temporal_identity,flow_consistent,object_bow_seed

REGIONS={'A':[430,570,700,500],'B':[990,340,650,440],'C':[470,190,650,390]}


class ObjectDetector:
    def __init__(self,model):
        from tools.vendor.opencv_yolox import YoloX
        self.model=YoloX(str(model),confThreshold=.2,nmsThreshold=.45)

    def detect(self,image,gate):
        return self.detect_rect(image,REGIONS[gate])

    def detect_near(self,image,box):
        x,y,w,h=box;width=max(500,min(800,round(w*4)));height=max(400,min(650,round(h*5)))
        x0=max(0,min(image.shape[1]-width,round(x+w/2-width/2)))
        y0=max(0,min(image.shape[0]-height,round(y+h/2-height/2)))
        return self.detect_rect(image,[x0,y0,width,height])

    def detect_rect(self,image,region):
        import cv2,numpy as np
        x,y,w,h=region;crop=image[y:y+h,x:x+w]
        if crop.shape[:2]!=(h,w):raise ValueError('unsupported_camera_dimensions')
        rgb=cv2.cvtColor(crop,cv2.COLOR_BGR2RGB);ratio=min(640/h,640/w)
        padded=np.full((640,640,3),114,np.float32)
        resized=cv2.resize(rgb,(round(w*ratio),round(h*ratio)))
        padded[:resized.shape[0],:resized.shape[1]]=resized
        result=[]
        for det in self.model.infer(padded):
            bx,by,bw,bh=(det[:4]/ratio).tolist()
            if int(det[-1]) in (0,8,37):result.append({'box':[bx+x,by+y,bw,bh],'class':int(det[-1]),'score':float(det[-2])})
        return result


def refine(gray,gate,definition,templates,anchor=None):
    import cv2
    half=36
    if anchor is None:
        if definition['axis']=='x':
            x0,x1=int(definition['value']-80-half),int(definition['value']+80+half)
            y0,y1=int(definition['segment'][0]-half),int(definition['segment'][1]+half)
        else:
            x0,x1=int(definition['segment'][0]-half),int(definition['segment'][1]+half)
            y0,y1=int(definition['value']-80-half),int(definition['value']+80+half)
    else:
        x0,x1=round(anchor[0]-20-half),round(anchor[0]+20+half)
        y0,y1=round(anchor[1]-20-half),round(anchor[1]+20+half)
    x0,y0=max(0,x0),max(0,y0);x1,y1=min(gray.shape[1],x1),min(gray.shape[0],y1)
    roi=gray[y0:y1,x0:x1];best={'score':-1,'point':None}
    for template in templates:
        response=cv2.matchTemplate(roi,template,cv2.TM_CCOEFF_NORMED)
        _,score,_,position=cv2.minMaxLoc(response)
        if score>best['score']:best={'score':float(score),'point':[position[0]+x0+half,position[1]+y0+half]}
    return best


def analyze_frames(folder,detector_path,colour_model,bow_model,*,proposal_cache=None):
    import cv2,numpy as np
    from scipy.signal import find_peaks
    cv2.setNumThreads(1);started=time.monotonic();folder=Path(folder)
    manifest=json.loads((folder/'frames.json').read_text());frames=manifest['frames'];base=manifest['source']['time_base']
    if manifest.get('schema')!=2 or manifest['source'].get('clock')!='decoded_pts':raise ValueError('original_pts_required')
    times=[r['pts']*base[0]/base[1] for r in frames]
    if any(not 0<b-a<=.12 for a,b in zip(times,times[1:])):raise ValueError('invalid_frame_clock')
    config=json.loads(Path(colour_model).read_text())
    claimed=config['fingerprint'];body={k:v for k,v in config.items() if k!='fingerprint'}
    if hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest()!=claimed:raise ValueError('colour_model_fingerprint_changed')
    if hashlib.sha256(Path(detector_path).read_bytes()).hexdigest()!=config['detector_sha256']:raise ValueError('detector_fingerprint_changed')
    detector=ObjectDetector(detector_path)
    with np.load(bow_model,allow_pickle=False) as data:templates={g:data[g] for g in 'ABC'}
    gates=json.loads((Path(__file__).resolve().parents[1]/'scraper/exhibition_model/pilot-v1.json').read_text())['gates']
    cache={};colour_observations=[];events=[]
    def image(index):
        if index not in cache:
            filename=Path(frames[index]['file'])
            if filename.is_absolute() or '..' in filename.parts:raise ValueError('invalid_frame_path')
            path=(folder/filename).resolve()
            if folder.resolve() not in path.parents:raise ValueError('invalid_frame_path')
            if hashlib.sha256(path.read_bytes()).hexdigest()!=frames[index].get('sha256'):raise ValueError('source_frame_changed')
            value=cv2.imread(str(path))
            if value is None or value.shape[:2]!=(1080,1920):raise ValueError('invalid_source_frame')
            cache[index]=value
            if len(cache)>64:del cache[next(iter(cache))]
        return cache[index]
    scores=json.loads(Path(proposal_cache).read_text()) if proposal_cache else None
    for gate,definition in gates.items():
        if scores:
            values=scores['scores'][gate];points=scores['points'][gate];indices=list(range(len(frames)))
        else:
            indices=list(range(0,len(frames),3));values=[];points=[]
            for i in indices:
                proposal=refine(cv2.cvtColor(image(i),cv2.COLOR_BGR2GRAY),gate,definition,templates[gate][:6])
                values.append(proposal['score']);points.append(proposal['point'])
                if len(cache)>100:cache.clear()
        dt=float(np.median(np.diff([times[i] for i in indices])))
        peaks,_=find_peaks(values,height=.46,prominence=.10,distance=max(1,round(1.8/dt)))
        for peak in peaks:
            anchor_index=indices[int(peak)];anchor=points[int(peak)];observations=[];detector_rows=[]
            seeds=[]
            for offset in (-16,-12,-8,-4,0,4,8,12,16):
                i=anchor_index+offset
                if not 0<=i<len(frames):continue
                frame=image(i);detections=detector.detect(frame,gate)
                # Follow current detector boxes. A fixed peak-centred crop loses a moving boat.
                coarse=points[i] if scores else anchor
                seed=object_bow_seed(detections,coarse,gate)
                if seed is None:continue
                seeds.append({'time':times[i],'point':seed})
                region=rider_region(detections,seed,gate)
                features=colour_features(frame,region['box']) if region else None
                identity=identify_colour(features,config['prototypes'],max_distance=config['max_distance'],min_margin=config['min_margin'],
                                         allow_achromatic=bool(region and region['kind']=='person' and gate=='A'))
                detector_rows.append({'frame':i,'detections':detections,'rider_region':region,'identity':identity,'point':seed})
                observations.append({'time':times[i],'point':seed,'boat':identity['boat']})
            boat=temporal_identity(observations)
            record={'gate':gate,'peak_frame':anchor_index,'boat':boat,'observations':detector_rows,'publication_ready':False}
            colour_observations.append(record)
            if boat is None:continue
            proposals={};direct={};interpolated={}
            for i in range(max(0,anchor_index-18),min(len(frames),anchor_index+19)):
                if not seeds[0]['time']<=times[i]<=seeds[-1]['time']:continue
                seed=[float(np.interp(times[i],[s['time'] for s in seeds],[s['point'][axis] for s in seeds])) for axis in (0,1)]
                interpolated[i]=seed
                proposals[i]=refine(cv2.cvtColor(image(i),cv2.COLOR_BGR2GRAY),gate,definition,templates[gate],seed)
                direct[i]=refine(cv2.cvtColor(image(i),cv2.COLOR_BGR2GRAY),gate,definition,templates[gate][:6])
            candidates=[]
            for method,stream in [('seed_template_with_actor_check',direct),('object_guided_template',proposals)]:
                for i,a in stream.items():
                    b=stream.get(i+1)
                    if not b or min(a['score'],b['score'])<.60:continue
                    if any(math.dist(point['point'],interpolated[k])>70 for k,point in [(i,a),(i+1,b)]):continue
                    if math.dist(a['point'],b['point'])>1500*(times[i+1]-times[i]):continue
                    when=crossing({'time':times[i],'x':a['point'][0],'y':a['point'][1]},
                                  {'time':times[i+1],'x':b['point'][0],'y':b['point'][1]},definition)
                    if when is None:continue
                    if not flow_consistent(cv2.cvtColor(image(i),cv2.COLOR_BGR2GRAY),cv2.cvtColor(image(i+1),cv2.COLOR_BGR2GRAY),a['point'],b['point']):continue
                    candidates.append({'time':when,'frame':i,'score':min(a['score'],b['score']),'points':[a['point'],b['point']],
                                       'localization_method':method})
                if candidates:break
            if candidates and max(c['time'] for c in candidates)-min(c['time'] for c in candidates)<=.12:
                best=max(candidates,key=lambda c:c['score']);events.append({'boat':boat,'gate':gate,**best})
            if len(cache)>200:cache.clear()
    rows=[]
    for boat in range(1,7):
        selected={};reasons=[]
        for gate in 'ABC':
            matches=[e for e in events if e['boat']==boat and e['gate']==gate]
            if len(matches)!=1:reasons.append(('missing_' if not matches else 'duplicate_')+gate)
            else:selected[gate]=matches[0]
        if len(selected)==3 and not selected['A']['time']<selected['B']['time']<selected['C']['time']:reasons.append('invalid_gate_order')
        row={'boat':boat,'status':'automatic_candidate' if not reasons else 'rejected','events':selected,'reasons':reasons}
        if not reasons:
            row.update(entry_video_seconds=round(selected['B']['time']-selected['A']['time'],1),
                       exit_video_seconds=round(selected['C']['time']-selected['B']['time'],1))
        rows.append(row)
    return {'method':'heiwajima-detector-temporal-v2','source_sha256':manifest['source']['sha256'],
            'implementation_sha256':hashlib.sha256(Path(__file__).read_bytes().replace(b'\r\n',b'\n')).hexdigest(),
            'tracking_implementation_sha256':hashlib.sha256(Path(__file__).with_name('boat_tracking.py').read_bytes().replace(b'\r\n',b'\n')).hexdigest(),
            'bow_model_sha256':hashlib.sha256(Path(bow_model).read_bytes()).hexdigest(),
            'colour_model_fingerprint':config['fingerprint'],'results':rows,'identity_observations':colour_observations,
            'elapsed_seconds':round(time.monotonic()-started,2),'identity_assumed_from_passage_order':False,
            'gate_local_tracking_only':True,'full_turn_tracking_verified':False,'publication_ready':False,
            'prediction_used':False,'predeadline_verified':False,'real_time_scale_verified':False,
            'coarse_proposals_from_v1_cache':proposal_cache is not None}


def analyze_video(video,private_parent,detector_path,colour_model,bow_model,scene_model):
    """Decode a local original once; scene sampling never replaces original PTS."""
    import cv2,numpy as np
    from tools.automatic_turn import caption_score,scene_intervals
    from tools.extract_turn_frames import extract
    cv2.setNumThreads(1);started=time.monotonic();video=Path(video).resolve();parent=Path(private_parent).resolve()
    public=Path(__file__).resolve().parents[1]/'site'
    if parent==public or public in parent.parents:raise ValueError('private_storage_required')
    if not video.is_file() or video.suffix.lower() not in ('.ts','.mp4','.mkv'):raise ValueError('local_video_required')
    probe=subprocess.run([shutil.which('ffprobe'),'-v','error','-protocol_whitelist','file,pipe','-select_streams','v:0',
                          '-show_entries','stream=time_base,width,height:frame=pts','-show_frames','-of','json',str(video)],
                         capture_output=True,text=True,check=True,timeout=120)
    metadata=json.loads(probe.stdout);stream=metadata['streams'][0];num,den=map(int,stream['time_base'].split('/'))
    pts=[row['pts'] for row in metadata['frames']]
    if [stream['width'],stream['height']]!=[1920,1080] or not pts or len(pts)>6000:raise ValueError('unsupported_source_video')
    if any(type(p) is not int for p in pts) or any(b<=a for a,b in zip(pts,pts[1:])):raise ValueError('invalid_original_pts')
    times=[p*num/den for p in pts];origin=times[0]
    with np.load(scene_model,allow_pickle=False) as data:mask=data['caption_blue']
    capture=cv2.VideoCapture(str(video));index=0;next_sample=0;samples=[]
    try:
        while True:
            ok,frame=capture.read()
            if not ok:break
            if index>=len(times):raise ValueError('decoder_frame_count_changed')
            relative=times[index]-origin
            if relative>=next_sample:
                roi=cv2.cvtColor(frame[910:1040,1040:1860],cv2.COLOR_BGR2RGB)
                samples.append((relative,caption_score(roi,mask)));next_sample=relative+1-.001
            index+=1
    finally:capture.release()
    if index!=len(times):raise ValueError('decoder_frame_count_changed')
    scenes=scene_intervals(samples,.7)
    if len(scenes)!=1:raise ValueError('first_mark_scene_not_unique')
    start=max(0,scenes[0][0]-4);end=min(times[-1]-origin,scenes[0][1]+4)
    if not 0<end-start<=45:raise ValueError('scene_duration_limit')
    parent.mkdir(parents=True,exist_ok=True)
    # A new, verified subdirectory only; cleanup never targets a supplied existing folder.
    with tempfile.TemporaryDirectory(prefix='boat-v2-',dir=parent) as temporary:
        temporary=Path(temporary).resolve()
        if parent not in temporary.parents:raise ValueError('invalid_temporary_storage')
        folder=temporary/'frames';extract(video,folder,origin+start,origin+end)
        result=analyze_frames(folder,detector_path,colour_model,bow_model)
    result.update(source_container_sha256=hashlib.sha256(video.read_bytes()).hexdigest(),
                  scene_start_relative_seconds=start,scene_end_relative_seconds=end,
                  total_elapsed_seconds=round(time.monotonic()-started,2),
                  original_video_entrypoint=True,camera_calibrated=False,automatic_publication_enabled=False)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('video','private_parent','detector','colour_model','bow_model','scene_model','output'):
        parser.add_argument('--'+name.replace('_','-'),type=Path,required=True)
    args=parser.parse_args()
    result=analyze_video(args.video,args.private_parent,args.detector,args.colour_model,args.bow_model,args.scene_model)
    args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({'complete_candidates':sum(r['status']=='automatic_candidate' for r in result['results']),
                      'publication_ready':False,'total_elapsed_seconds':result['total_elapsed_seconds']}))
