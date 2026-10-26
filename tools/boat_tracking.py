"""Research-only object/colour/temporal identity helpers, independent of v1."""
from __future__ import annotations
import math


def rider_region(detections,bow,gate):
    """Associate detected people/boats to a bow hypothesis; never use passage order."""
    dx,dy={'A':(-60,-10),'B':(50,-10),'C':(60,-10)}[gate]
    expected=(bow[0]+dx,bow[1]+dy)
    people=[];boats=[]
    for d in detections:
        x,y,w,h=d['box']
        if not all(math.isfinite(v) for v in (x,y,w,h,d['score'])) or min(w,h)<=0:continue
        if d['class']==0 and d['score']>=.22:
            distance=math.hypot(x+w/2-expected[0],y+h/2-expected[1])
            if distance<=75:people.append((distance-.1*d['score'],[x+.15*w,y,.7*w,.40*h],'person'))
        if d['class']==8 and d['score']>=.25 and 65<=w<=240 and 18<=h<=150:
            estimated=(x+w,y+.25*h) if gate=='A' else (x,y+.5*h)
            distance=math.dist(estimated,bow)
            if distance<=50:
                if gate=='A':region=[x+.15*w,y-.6*h,.5*w,.65*h]
                elif gate=='B':region=[x+.35*w,y-.35*h,.45*w,.55*h]
                else:region=[x+.4*w,y+.05*h,.45*w,.6*h]
                boats.append((distance-.1*d['score'],region,'boat'))
    pool=people or boats
    if not pool:return None
    _,region,kind=min(pool,key=lambda row:row[0])
    return {'box':region,'kind':kind}


def object_bow_seed(detections,proposal,gate):
    """Coarse localization from a learned hull box, not a measured bow point."""
    candidates=[]
    for d in detections:
        x,y,w,h=d['box']
        if d['class'] not in (8,37) or not .2<=d['score']<=1 or not 55<=w<=260 or not 18<=h<=150:continue
        point=[x+w,y+.2*h] if gate=='A' else [x,y+(.3 if gate=='B' else .55)*h]
        distance=math.dist(point,proposal)
        if distance<=240:candidates.append((distance-10*d['score'],point))
    return min(candidates,key=lambda row:row[0])[1] if candidates else None


def colour_features(image,region):
    import cv2,numpy as np
    x,y,w,h=region
    x0,y0=max(0,round(x)),max(0,round(y));x1,y1=min(image.shape[1],round(x+w)),min(image.shape[0],round(y+h))
    if x1-x0<5 or y1-y0<5:return None
    hsv=cv2.cvtColor(image[y0:y1,x0:x1],cv2.COLOR_BGR2HSV);H,S,V=cv2.split(hsv)
    masks=[((H<10)|(H>170))&(S>70)&(V>60),(H>=90)&(H<=135)&(S>70)&(V>60),
           (H>=18)&(H<=40)&(S>70)&(V>60),(H>40)&(H<90)&(S>40)&(V>50),
           (V<65),(S<65)&(V>170)]
    counts=np.array([m.mean() for m in masks],dtype=float)
    return np.sqrt(counts).tolist()


def identify_colour(features,prototypes,*,max_distance=.65,min_margin=.04,allow_achromatic=False):
    if features is None:return {'boat':None,'reason':'no_rider_region'}
    if len(features)!=6 or any(not math.isfinite(v) or not 0<=v<=1 for v in features):
        return {'boat':None,'reason':'invalid_colour_features'}
    areas=[v*v for v in features];colours=sorted(range(4),key=lambda i:areas[i],reverse=True)
    best,second=colours[:2];strong=areas[best]
    if strong>=.02 and strong>=1.7*max(areas[second],.001) and (strong>=.06 or strong>=.3*areas[5]):
        return {'boat':(3,4,5,6)[best],'margin':strong-areas[second],'distance':0.,'reason':None,'source':'chromatic_evidence'}
    if allow_achromatic and areas[5]>=.08 and areas[5]>=2.5*max(areas[4],.001) and strong<.5*areas[5]:
        return {'boat':1,'margin':areas[5]-areas[4],'distance':0.,'reason':None,'source':'white_evidence'}
    if allow_achromatic and areas[4]>=.08 and areas[4]>=2.5*max(areas[5],.001) and strong<.5*areas[4]:
        return {'boat':2,'margin':areas[4]-areas[5],'distance':0.,'reason':None,'source':'black_evidence'}
    scores={}
    for boat,examples in prototypes.items():
        distances=sorted(math.dist(features,v) for v in examples)
        if distances:scores[int(boat)]=sum(distances[:2])/min(2,len(distances))
    ordered=sorted(scores,key=scores.get)
    if len(ordered)!=6:return {'boat':None,'reason':'incomplete_colour_model'}
    best,second=ordered[:2];distance=scores[best];margin=scores[second]-distance
    accepted=distance<=max_distance and margin>=min_margin
    return {'boat':best if accepted else None,'distance':distance,'margin':margin,
            'reason':None if accepted else 'ambiguous_colour'}


def temporal_identity(observations,*,min_observations=3,min_fraction=.8,max_gap=.4,max_speed=1200):
    """Require same physical actor and consistent colours across original PTS."""
    if len(observations)<min_observations:return None
    if any(not math.isfinite(r['time']) or len(r['point'])!=2 or
           any(not math.isfinite(v) for v in r['point']) for r in observations):return None
    rows=sorted(observations,key=lambda r:r['time'])
    for a,b in zip(rows,rows[1:]):
        delta=b['time']-a['time']
        if not 0<delta<=max_gap or math.dist(a['point'],b['point'])>max_speed*delta:return None
    votes={boat:sum(r.get('boat')==boat for r in rows) for boat in range(1,7)}
    winner=max(votes,key=votes.get)
    known=sum(votes.values())
    return winner if votes[winner]>=min_observations and known and votes[winner]/known>=min_fraction else None


def flow_consistent(previous,current,a,b,*,max_backward_error=1.5,max_proposal_error=4):
    import cv2,numpy as np
    p=np.array([[a]],np.float32);initial=np.array([[b]],np.float32);expected=initial.copy()
    nxt,status,_=cv2.calcOpticalFlowPyrLK(previous,current,p,initial,winSize=(21,21),maxLevel=3,
                                        flags=cv2.OPTFLOW_USE_INITIAL_FLOW)
    if nxt is None or status is None or not status[0,0]:return False
    back,ok,_=cv2.calcOpticalFlowPyrLK(current,previous,nxt,None,winSize=(21,21),maxLevel=3)
    return bool(back is not None and ok is not None and ok[0,0] and
                np.linalg.norm(back-p)<=max_backward_error and np.linalg.norm(nxt-expected)<=max_proposal_error)


def track_actor(image_loader,start,box,frame_count,*,detector=None,max_steps=160):
    """Track an actor in both directions. This does not measure its bow or verify ID."""
    import cv2,numpy as np
    scale=.5;initial=np.array(box,dtype=float)*scale;tracks={start:list(map(float,box))}
    def gray(index):return cv2.resize(cv2.cvtColor(image_loader(index),cv2.COLOR_BGR2GRAY),None,fx=scale,fy=scale)
    def features(image,rect):
        x,y,w,h=rect;mask=np.zeros_like(image)
        x0,y0=max(0,round(x+.1*w)),max(0,round(y+.1*h))
        x1,y1=min(image.shape[1],round(x+.9*w)),min(image.shape[0],round(y+.9*h))
        if x1<=x0 or y1<=y0:return None
        mask[y0:y1,x0:x1]=255
        return cv2.goodFeaturesToTrack(image,maxCorners=40,qualityLevel=.02,minDistance=2,mask=mask)
    for direction in (-1,1):
        previous=gray(start);rect=initial.copy();points=features(previous,rect);misses=0;last_motion=None
        for step in range(1,max_steps+1):
            index=start+direction*step
            if not 0<=index<frame_count or points is None or len(points)<4:break
            current=gray(index)
            moved,status,_=cv2.calcOpticalFlowPyrLK(previous,current,points,None,winSize=(25,25),maxLevel=3)
            if moved is None or status is None:break
            back,back_status,_=cv2.calcOpticalFlowPyrLK(current,previous,moved,None,winSize=(25,25),maxLevel=3)
            if back is None or back_status is None:break
            valid=(status[:,0]>0)&(back_status[:,0]>0)&(np.max(np.abs(back-points),axis=(1,2))<1.5)
            if int(valid.sum())<4:break
            motion=np.median((moved-points)[valid,0,:],axis=0)
            if not .1<=float(np.linalg.norm(motion))<=35:break
            if last_motion is not None and float(np.linalg.norm(motion-last_motion))>15:break
            rect[:2]+=motion;points=moved[valid];last_motion=motion
            if rect[0]<0 or rect[1]<0 or rect[0]+rect[2]>=current.shape[1] or rect[1]+rect[3]>=current.shape[0]:break
            if detector is not None and step%6==0:
                refreshed=detector(image_loader(index),(rect/scale).tolist())
                if refreshed is not None:
                    rect=np.array(refreshed)*scale;points=features(current,rect);misses=0
                else:
                    misses+=1
                    if misses>=4:break
            tracks[index]=(rect/scale).tolist();previous=current
    return [{'frame':i,'box':tracks[i]} for i in sorted(tracks)]
