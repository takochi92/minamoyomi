"""Render a private, display-only slow tracking clip. Never measurement input."""
import argparse,hashlib,json,shutil,subprocess
from fractions import Fraction
from pathlib import Path
from tools.frame_binding import require_frame_binding


def render(folder,track_path,output,boat):
    import cv2
    from PIL import Image,ImageDraw,ImageFont
    folder=Path(folder);output=Path(output).resolve();raw=json.loads(Path(track_path).read_text())
    repository=Path(__file__).resolve().parents[1]
    if output==repository or repository in output.parents:raise ValueError('private_media_outside_repository_required')
    manifest=json.loads((folder/'frames.json').read_text());frames=manifest['frames'];base=Fraction(*manifest['source']['time_base'])
    binding=require_frame_binding(manifest,raw)
    track=next((r for r in raw.get('tracks',[raw]) if r.get('boat')==boat),None)
    if not track or len(track.get('frames',[]))<2:raise ValueError('continuous_track_required')
    records=track['frames'];indices=[r['frame'] for r in records]
    if indices!=list(range(indices[0],indices[-1]+1)):raise ValueError('continuous_frames_required')
    if any(r.get('pts')!=frames[r['frame']]['pts'] for r in records):raise ValueError('track_pts_mismatch')
    pts=[frames[i]['pts'] for i in indices];deltas={b-a for a,b in zip(pts,pts[1:])}
    if len(deltas)!=1 or min(deltas)<=0:raise ValueError('constant_original_pts_required_for_demo')
    interval=Fraction(next(iter(deltas)))*base;fps=1/(interval*2)
    command=[shutil.which('ffmpeg'),'-v','error','-nostdin','-f','rawvideo','-pix_fmt','bgr24','-s','960x540',
             '-framerate',f'{fps.numerator}/{fps.denominator}','-i','pipe:0','-an','-c:v','libx264','-preset','fast',
             '-crf','23','-pix_fmt','yuv420p','-movflags','+faststart','-y',str(output)]
    fonts=[Path('C:/Windows/Fonts/meiryo.ttc'),Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')]
    font_path=next((p for p in fonts if p.exists()),None)
    font=ImageFont.truetype(str(font_path),18) if font_path else ImageFont.load_default(size=18)
    process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    try:
        for position,row in enumerate(records):
            index=row['frame'];path=(folder/frames[index]['file']).resolve()
            if folder.resolve() not in path.parents or hashlib.sha256(path.read_bytes()).hexdigest()!=frames[index]['sha256']:
                raise ValueError('source_frame_changed')
            frame=cv2.resize(cv2.imread(str(path)),(960,540));x,y,w,h=[round(v*.5) for v in row['box']]
            cv2.rectangle(frame,(x,y),(x+w,y+h),(0,255,0),2)
            image=Image.fromarray(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB));draw=ImageDraw.Draw(image)
            draw.rectangle((0,488,960,540),fill=(12,22,28))
            seconds=float((frames[index]['pts']-pts[0])*base)
            title=f'研究中：{boat}号艇の追跡候補／0.5倍速　映像内 +{seconds:.2f}秒' if font_path else f'Research: boat {boat} candidate / 0.5x / source +{seconds:.2f}s'
            note='この加工動画はタイム測定・予想には使用しません。映像出典：BOATCAST 平和島展示' if font_path else 'Display only. Not timing or prediction input. Source: BOATCAST Heiwajima exhibition.'
            draw.text((12,491),title,font=font,fill='white');draw.text((12,514),note,font=font,fill='#9edbd4')
            if position==len(records)//2:image.save(output.with_suffix('.jpg'),quality=92)
            process.stdin.write(cv2.cvtColor(__import__('numpy').asarray(image),cv2.COLOR_RGB2BGR).tobytes())
        process.stdin.close();process.stdin=None;_,error=process.communicate(timeout=90)
        if process.returncode:raise ValueError('demo_render_failed')
    except Exception:
        process.kill();process.communicate();raise
    receipt={'boat':boat,'frame_binding':binding,'source_frames':len(records),'source_video_seconds':float((pts[-1]-pts[0])*base),
             'display_speed':.5,'measurement_input':False,'publication_performed':False}
    output.with_suffix('.json').write_text(json.dumps(receipt,indent=2))
    return receipt


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('frames','track','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--boat',type=int,required=True)
    args=parser.parse_args();print(json.dumps(render(args.frames,args.track,args.output,args.boat)))
