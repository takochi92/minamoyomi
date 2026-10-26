"""Small research heatmap model. Source-derived weights remain private."""
from __future__ import annotations
import argparse,hashlib,json,math,time
from pathlib import Path


def make_model():
    import torch
    from torch import nn
    class Model(nn.Module):
        def __init__(self):
            super().__init__()
            def block(a,b):return nn.Sequential(nn.Conv2d(a,b,3,padding=1),nn.ReLU(),nn.Conv2d(b,b,3,padding=1),nn.ReLU())
            self.a=block(4,4);self.b=block(4,8);self.c=block(8,16)
            self.d=block(24,8);self.e=block(12,4);self.out=nn.Conv2d(4,1,1)
        def forward(self,x):
            a=self.a(x);b=self.b(nn.functional.max_pool2d(a,2));c=self.c(nn.functional.max_pool2d(b,2))
            d=self.d(torch.cat([nn.functional.interpolate(c,size=b.shape[-2:],mode='bilinear',align_corners=False),b],1))
            e=self.e(torch.cat([nn.functional.interpolate(d,size=a.shape[-2:],mode='bilinear',align_corners=False),a],1))
            return self.out(e)
    return Model()


def train(dataset,metadata,output,*,steps=800,seed=20261027):
    output=Path(output).resolve();public=Path(__file__).resolve().parents[1]/'site'
    if output==public or public in output.parents or type(steps) is not int or not 1<=steps<=5000:
        raise ValueError('invalid_private_training_arguments')
    import cv2,numpy as np,torch
    torch.set_num_threads(2);torch.manual_seed(seed);rng=np.random.default_rng(seed);started=time.monotonic()
    meta=json.loads(Path(metadata).read_text());rows=meta['examples']
    if not rows or any(r['split']!='train' or r['race'] not in (1,2) for r in rows):raise ValueError('training_race_leakage')
    with np.load(dataset,allow_pickle=False) as data:patches=data['images'];positions=data['positions'];directions=data['directions']
    if len(rows)!=len(patches):raise ValueError('dataset_count_mismatch')
    model=make_model();optimizer=torch.optim.Adam(model.parameters(),lr=.002,weight_decay=.0001)
    yy,xx=np.mgrid[:64,:64];history=[];model.train()
    for step in range(steps):
        inputs=[];targets=[]
        for index in rng.integers(0,len(patches),size=16):
            image=patches[index];point=positions[index]
            for _ in range(50):
                size=float(rng.uniform(155,230));centre=point+rng.uniform(-65,65,size=2)
                x0,y0=centre-size/2
                if x0>=0 and y0>=0 and x0+size<image.shape[1] and y0+size<image.shape[0]:break
            else:raise ValueError('invalid_training_crop')
            matrix=np.float32([[size/64,0,x0],[0,size/64,y0]])
            crop=cv2.warpAffine(image,matrix,(64,64),flags=cv2.INTER_LINEAR|cv2.WARP_INVERSE_MAP)
            rgb=crop.astype(np.float32)/255
            rgb=np.clip(rgb*float(rng.uniform(.75,1.25))+float(rng.uniform(-.04,.04)),0,1)
            target=(point-[x0,y0])*64/size;direction=float(directions[index])
            if rng.random()<.5:rgb=rgb[:,::-1].copy();target[0]=63-target[0];direction=-direction
            tensor=np.concatenate([rgb.transpose(2,0,1),np.full((1,64,64),direction,np.float32)],0)
            gaussian=np.exp(-((xx-target[0])**2+(yy-target[1])**2)/(2*1.2**2));gaussian/=gaussian.sum()
            inputs.append(tensor);targets.append(gaussian.astype(np.float32).ravel())
        prediction=model(torch.from_numpy(np.stack(inputs))).flatten(1)
        target=torch.from_numpy(np.stack(targets))
        loss=-(target*torch.log_softmax(prediction,1)).sum(1).mean()
        optimizer.zero_grad();loss.backward();optimizer.step()
        if step==steps*3//4:
            for group in optimizer.param_groups:group['lr']=.0003
        if step%100==0 or step==steps-1:
            record={'step':step,'loss':float(loss.detach()),'elapsed_seconds':round(time.monotonic()-started,2)}
            history.append(record);print(json.dumps(record),flush=True)
    output=Path(output)
    torch.save({'state_dict':model.state_dict(),'seed':seed,'steps':steps,'input_size':64,'crop_size':192,
                'training_races':[1,2],'dataset_sha256':hashlib.sha256(Path(dataset).read_bytes()).hexdigest()},output)
    receipt={'method':'bow-heatmap-prototype-v1','training_races':[1,2],'development_races':[3],
             'examples':len(rows),'steps':steps,'history':history,'weights_sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
             'implementation_sha256':hashlib.sha256(Path(__file__).read_bytes().replace(b'\r\n',b'\n')).hexdigest(),
             'publication_ready':False,'prediction_used':False}
    output.with_suffix('.json').write_text(json.dumps(receipt,indent=2))
    return receipt


def load_model(weights):
    import torch
    torch.set_num_threads(2);weights=Path(weights)
    receipt=json.loads(weights.with_suffix('.json').read_text())
    if hashlib.sha256(weights.read_bytes()).hexdigest()!=receipt['weights_sha256']:raise ValueError('keypoint_weights_changed')
    checkpoint=torch.load(weights,map_location='cpu',weights_only=True)
    model=make_model();model.load_state_dict(checkpoint['state_dict']);model.eval()
    return model


def usable_prediction(result,*,max_spread=8,min_peak_mass=.10):
    point=result.get('point');spread=result.get('crop_spread_pixels');mass=result.get('mean_peak_mass')
    return (isinstance(point,list) and len(point)==2 and all(math.isfinite(v) for v in point)
            and type(spread) in (int,float) and math.isfinite(spread) and 0<=spread<=max_spread
            and type(mass) in (int,float) and math.isfinite(mass) and min_peak_mass<=mass<=1)


def locate(model,image,coarse_point,gate):
    import cv2,numpy as np,torch
    inputs=[];origins=[];size=192
    for dx,dy in [(0,0),(-24,0),(24,0),(0,-24),(0,24)]:
        x0,y0=coarse_point[0]+dx-size/2,coarse_point[1]+dy-size/2
        if x0<0 or y0<0 or x0+size>=image.shape[1] or y0+size>=image.shape[0]:continue
        matrix=np.float32([[size/64,0,x0],[0,size/64,y0]])
        crop=cv2.warpAffine(image,matrix,(64,64),flags=cv2.INTER_LINEAR|cv2.WARP_INVERSE_MAP)
        rgb=cv2.cvtColor(crop,cv2.COLOR_BGR2RGB).astype(np.float32)/255
        inputs.append(np.concatenate([rgb.transpose(2,0,1),np.full((1,64,64),1 if gate=='A' else -1,np.float32)],0))
        origins.append((x0,y0))
    if len(inputs)<3:return {'point':None,'reason':'insufficient_visible_crops'}
    with torch.no_grad():maps=torch.softmax(model(torch.from_numpy(np.stack(inputs))).flatten(1),1).reshape(-1,64,64).numpy()
    points=[];masses=[]
    for heatmap,(x0,y0) in zip(maps,origins):
        y,x=np.unravel_index(heatmap.argmax(),heatmap.shape);a,b=max(0,x-1),max(0,y-1);c,d=min(64,x+2),min(64,y+2)
        local=heatmap[b:d,a:c];yy,xx=np.mgrid[b:d,a:c];total=local.sum()
        px=float((local*xx).sum()/total);py=float((local*yy).sum()/total)
        points.append([x0+px*size/64,y0+py*size/64]);masses.append(float(heatmap[max(0,y-2):y+3,max(0,x-2):x+3].sum()))
    point=np.median(points,axis=0);spread=max(float(np.linalg.norm(np.asarray(p)-point)) for p in points)
    return {'point':point.tolist(),'crop_spread_pixels':spread,'mean_peak_mass':sum(masses)/len(masses),
            'crop_predictions':points,'publication_ready':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('dataset','metadata','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--steps',type=int,default=800)
    args=parser.parse_args();train(args.dataset,args.metadata,args.output,steps=args.steps)
