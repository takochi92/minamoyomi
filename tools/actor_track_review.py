"""Private review trajectories from colour-supported seeds. Never public timing."""
from __future__ import annotations
import argparse,hashlib,json,math,time
from pathlib import Path
from tools.automatic_turn_v2 import ObjectDetector
from tools.boat_tracking import track_actor


def overlap(a,b):
    x=max(a[0],b[0]);y=max(a[1],b[1]);x1=min(a[0]+a[2],b[0]+b[2]);y1=min(a[1]+a[3],b[1]+b[3])
    intersection=max(0,x1-x)*max(0,y1-y)
    return intersection/max(1,a[2]*a[3]+b[2]*b[3]-intersection)


def make_tracks(folder,observations,detector_path,*,boats=range(1,7)):
    import cv2
    cv2.setNumThreads(1);started=time.monotonic();folder=Path(folder)
    manifest=json.loads((folder/'frames.json').read_text());frames=manifest['frames'];base=manifest['source']['time_base']
    data=json.loads(Path(observations).read_text())
    if data['source_sha256']!=manifest['source']['sha256']:raise ValueError('source_mismatch')
    detector=ObjectDetector(detector_path);cache={}
    def image(i):
        if i not in cache:
            path=(folder/frames[i]['file']).resolve()
            if folder.resolve() not in path.parents:raise ValueError('invalid_frame_path')
            if hashlib.sha256(path.read_bytes()).hexdigest()!=frames[i].get('sha256'):raise ValueError('source_frame_changed')
            cache[i]=cv2.imread(str(path))
            if len(cache)>30:del cache[next(iter(cache))]
        return cache[i]
    def refresh(frame,box):
        x,y,w,h=box;choices=[]
        for d in detector.detect_near(frame,box):
            if d['class'] not in (8,37) or d['box'][2]<55:continue
            bx,by,bw,bh=d['box'];distance=math.dist([x+w/2,y+h/2],[bx+bw/2,by+bh/2]);iou=overlap(box,d['box'])
            if distance<100 and iou>.1:choices.append((distance/100+1-iou,d['box']))
        return min(choices,key=lambda row:row[0])[1] if choices else None
    rows=[]
    for boat in boats:
        options=[]
        for event in data['identity_observations']:
            for row in event['observations']:
                if row['identity'].get('boat')!=boat:continue
                for d in row['detections']:
                    if d['class'] not in (8,37) or d['box'][2]<55:continue
                    x,y,w,h=d['box'];point=[x+w,y+.2*h] if event['gate']=='A' else [x,y+(.3 if event['gate']=='B' else .55)*h]
                    if math.dist(point,row['point'])<5:options.append((row['identity'].get('margin',0),row['frame'],d['box'],event['gate']))
        if not options:
            rows.append({'boat':boat,'state':'no_colour_seed','frames':[]});continue
        seeds=[max((o for o in options if o[3]==gate),default=None) for gate in 'ABC']
        attempts=[]
        for seed in seeds:
            if seed is None:continue
            _,start,box,_=seed
            trajectory=track_actor(image,start,box,len(frames),detector=refresh,max_steps=160)
            attempts.append({'seed_frame':start,'frames':trajectory})
        primary=max(attempts,key=lambda r:len(r['frames']));start=primary['seed_frame'];trajectory=primary['frames']
        primary_boxes={r['frame']:r['box'] for r in trajectory};agreements=[]
        for attempt in attempts:
            if attempt is primary:continue
            ious=sorted(overlap(r['box'],primary_boxes[r['frame']]) for r in attempt['frames'] if r['frame'] in primary_boxes)
            agreements.append({'seed_frame':attempt['seed_frame'],'shared_frames':len(ious),
                               'median_box_overlap':ious[len(ious)//2] if ious else 0})
        for row in trajectory:row['pts']=frames[row['frame']]['pts']
        rows.append({'boat':boat,'state':'provisional_actor_track','seed_frame':start,'frames':trajectory,
                     'duration_video_seconds':(trajectory[-1]['pts']-trajectory[0]['pts'])*base[0]/base[1],
                     'seed_attempts':len(attempts),'seed_track_agreement':agreements,
                     'identity_independently_verified':False,'bow_measurement':False})
    return {'source_sha256':manifest['source']['sha256'],'time_base':base,'tracks':rows,
            'elapsed_seconds':round(time.monotonic()-started,2),'publication_ready':False,
            'prediction_used':False,'independent_identity_review_complete':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('frames','observations','detector','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();result=make_tracks(args.frames,args.observations,args.detector)
    args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({'tracks':[{k:r.get(k) for k in ('boat','state','duration_video_seconds')} for r in result['tracks']],
                      'publication_ready':False}))
