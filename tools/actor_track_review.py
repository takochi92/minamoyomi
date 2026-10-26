"""Private review trajectories from colour-supported seeds. Never public timing."""
from __future__ import annotations
import argparse,hashlib,json,math,time
from pathlib import Path
from tools.automatic_turn_v2 import ObjectDetector
from tools.boat_tracking import track_actor
from tools.frame_binding import require_frame_binding


def overlap(a,b):
    x=max(a[0],b[0]);y=max(a[1],b[1]);x1=min(a[0]+a[2],b[0]+b[2]);y1=min(a[1]+a[3],b[1]+b[3])
    intersection=max(0,x1-x)*max(0,y1-y)
    return intersection/max(1,a[2]*a[3]+b[2]*b[3]-intersection)


def entry_connected_track(attempts,*,min_shared=12,min_overlap=.5):
    """Never assign an unrelated longer trajectory the entry seed's identity.

    Engineering association thresholds, not independently calibrated confidence.
    A colour seen only at the turn/exit cannot create an entry identity.
    """
    roots=[i for i,a in enumerate(attempts) if a.get('gate')=='A']
    if len(roots)!=1:return None,[]
    boxes=[{r['frame']:r['box'] for r in a['frames']} for a in attempts]
    connected={roots[0]}
    for _ in attempts:
        added=set()
        for i in range(len(attempts)):
            if i in connected:continue
            for j in connected:
                ious=sorted(overlap(boxes[i][f],boxes[j][f]) for f in boxes[i].keys() & boxes[j].keys())
                boundary=False
                if boxes[i] and boxes[j]:
                    for first,second in ((boxes[i],boxes[j]),(boxes[j],boxes[i])):
                        a,b=max(first),min(second)
                        if b!=a+1:continue
                        p,q=first[a],second[b]
                        delta=math.dist([p[0]+p[2]/2,p[1]+p[3]/2],[q[0]+q[2]/2,q[1]+q[3]/2])
                        if overlap(p,q)>=.5 and delta<=50:boundary=True
                if (len(ious)>=min_shared and ious[len(ious)//2]>=min_overlap) or boundary:
                    added.add(i);break
        if not added:break
        connected.update(added)
    chosen=max(connected,key=lambda i:len(attempts[i]['frames']))
    return attempts[chosen],sorted(connected)


def choose_seeds(options):
    """Retain competing turn/exit actors until physical association resolves them."""
    selected=[]
    for gate in 'ABC':
        groups={}
        for option in options:
            if option[3]!=gate:continue
            peak=option[4]
            if peak not in groups or (option[5],option[0])>(groups[peak][5],groups[peak][0]):groups[peak]=option
        ordered=sorted(groups.values(),key=lambda o:(o[5],o[0]),reverse=True)
        selected.extend(ordered[:1 if gate=='A' else 2])
    return selected


def supporting_rider(detections,box):
    """An observed rider can support valid flow, never replace a missing hull point."""
    x,y,w,h=box
    for detection in detections:
        if detection['class']!=0 or detection['score']<.4:continue
        px,py,pw,ph=detection['box']
        if pw<=0 or ph<=0:continue
        area=max(0,min(x+w,px+pw)-max(x,px))*max(0,min(y+h,py+ph)-max(y,py))
        if area/(pw*ph)>=.5 and x<=px+pw/2<=x+w and y-15<=py+ph/2<=y+h:
            return True
    return False


def make_tracks(folder,observations,detector_path,*,boats=range(1,7)):
    import cv2
    cv2.setNumThreads(1);started=time.monotonic();folder=Path(folder)
    manifest=json.loads((folder/'frames.json').read_text());frames=manifest['frames'];base=manifest['source']['time_base']
    data=json.loads(Path(observations).read_text())
    binding=require_frame_binding(manifest,data)
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
        x,y,w,h=box;choices=[];detections=detector.detect_near(frame,box)
        for d in detections:
            if d['class'] not in (8,37) or d['box'][2]<55:continue
            bx,by,bw,bh=d['box'];distance=math.dist([x+w/2,y+h/2],[bx+bw/2,by+bh/2]);iou=overlap(box,d['box'])
            if distance<100 and iou>.1:choices.append((distance/100+1-iou,d['box']))
        if choices:return min(choices,key=lambda row:row[0])[1]
        # This supports a rectangle already observed by valid flow. The tracker
        # must reject this fallback when flow itself is missing.
        return {'box':box,'support':'observed_rider'} if supporting_rider(detections,box) else None
    rows=[]
    for boat in boats:
        options=[]
        for event in data['identity_observations']:
            for row in event['observations']:
                if row['identity'].get('boat')!=boat:continue
                # Entry identity must come from a detected rider. Hull/water
                # fallback colours can otherwise outrank the actual cap.
                if event['gate']=='A' and (row.get('rider_region') or {}).get('kind')!='person':continue
                for d in row['detections']:
                    if d['class'] not in (8,37) or d['box'][2]<55:continue
                    x,y,w,h=d['box'];point=[x+w,y+.2*h] if event['gate']=='A' else [x,y+(.3 if event['gate']=='B' else .55)*h]
                    if math.dist(point,row['point'])<5:
                        options.append((row['identity'].get('margin',0),row['frame'],d['box'],event['gate'],
                                        event['peak_frame'],(row.get('rider_region') or {}).get('kind')=='person'))
        if not options:
            rows.append({'boat':boat,'state':'no_colour_seed','frames':[]});continue
        seeds=choose_seeds(options)
        if not any(s[3]=='A' for s in seeds):
            rows.append({'boat':boat,'state':'no_entry_colour_seed','frames':[],
                         'identity_independently_verified':False});continue
        attempts=[]
        for seed in seeds:
            _,start,box=seed[:3]
            diagnostics={}
            trajectory=track_actor(image,start,box,len(frames),detector=refresh,max_steps=160,diagnostics=diagnostics)
            attempts.append({'seed_frame':start,'gate':seed[3],'frames':trajectory,'diagnostics':diagnostics})
        primary,connected=entry_connected_track(attempts)
        if primary is None:
            rows.append({'boat':boat,'state':'no_entry_colour_seed','frames':[],
                         'seed_attempts':len(attempts),'identity_independently_verified':False});continue
        start=primary['seed_frame']
        # Merge only actual observations from the physically connected component.
        # Adjacent partial tracks may cover each other, but missing frames are
        # never interpolated or manufactured.
        combined={r['frame']:{**r,'actor_seed_frame':start} for r in primary['frames']}
        for index in sorted(connected,key=lambda i:len(attempts[i]['frames']),reverse=True):
            for row in attempts[index]['frames']:
                combined.setdefault(row['frame'],{**row,'actor_seed_frame':attempts[index]['seed_frame']})
        trajectory=[combined[i] for i in sorted(combined)]
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
                     'entry_connected_seed_count':len(connected),'excluded_disconnected_seeds':len(attempts)-len(connected),
                     'entry_identity_required':True,
                     'seed_stop_diagnostics':[{'seed_frame':a['seed_frame'],'gate':a['gate'],**a['diagnostics']} for a in attempts],
                     'identity_independently_verified':False,'bow_measurement':False})
    return {'source_sha256':manifest['source']['sha256'],'frame_binding':binding,'time_base':base,'tracks':rows,
            'elapsed_seconds':round(time.monotonic()-started,2),'publication_ready':False,
            'prediction_used':False,'independent_identity_review_complete':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('frames','observations','detector','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();result=make_tracks(args.frames,args.observations,args.detector)
    args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({'tracks':[{k:r.get(k) for k in ('boat','state','duration_video_seconds')} for r in result['tracks']],
                      'publication_ready':False}))
