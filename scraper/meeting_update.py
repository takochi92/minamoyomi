"""Collect optional, public display data separately from five-minute race updates."""
from __future__ import annotations
import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from pathlib import Path
from bs4 import BeautifulSoup
from .fetch import Fetcher
from .meeting import bounds, parse_precheck, parse_points, norm, page_matches
from .parse import parse_oriten, parse_beforeinfo

JST=timezone(timedelta(hours=9))
DATA=Path(__file__).resolve().parent.parent/'site/data'


def read(path, default=None):
    try:return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError,ValueError):return default


def save(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    tmp.replace(path)


def refresh(data, idx, now, fetcher, workers=4, backfill_limit=4):
    day=now.strftime('%Y%m%d'); stamp=now.isoformat(timespec='seconds'); folder=Path(data)/'meetings'
    if idx.get('date')!=day:return []
    def one(v):
        jcd=v.get('jcd',''); period=bounds(day,v.get('day',''))
        if not period or not isinstance(jcd,str) or not jcd.isdigit() or len(jcd)!=2 or not 1<=int(jcd)<=24 or v.get('cancelled'):return None
        path=folder/f'{period[0]}-{jcd}.json'
        old=read(path,{})
        feed=old if old.get('start')==period[0] and old.get('end')==period[1] and norm(old.get('title'))==norm(v.get('title')) else {}
        feed.update(version=1,jcd=jcd,start=period[0],end=period[1],title=v.get('title',''))
        attempts=feed.setdefault('attempts',{})
        def due(key, minutes):
            try:return (now-datetime.fromisoformat(attempts[key]['at'])).total_seconds()>=minutes*60
            except (KeyError,ValueError,TypeError):return True
        if not feed.get('precheck') and due('precheck',60) and not fetcher.exhausted:
            try:
                rows=parse_precheck(fetcher.get('rankingmotor',jcd=jcd,hd=day),day,jcd,v['title'])
                attempts['precheck']={'at':stamp,'status':'ok' if rows else 'no_data'}
                if rows:feed['precheck']={'rows':rows,'fetched_at':stamp,'source_url':f'https://www.boatrace.jp/owpc/pc/race/rankingmotor?jcd={jcd}&hd={day}'}
            except Exception:attempts['precheck']={'at':stamp,'status':'error'}
        interval=60 if attempts.get('points',{}).get('status')=='no_data' else 14
        if due('points',interval) and not fetcher.exhausted:
            try:
                url=f'https://www.boatrace.jp/owpc/pc/race/pointrank?jcd={jcd}&hd={day}'
                if jcd=='23':
                    url='https://www.boatrace-karatsu.jp/sp/index.php?page=raceinfo-tokutenrank'
                    fetcher._slot(); response=fetcher.s.get(url,timeout=(10,25));response.raise_for_status();response.encoding='utf-8'
                    points=parse_points(response.text,day,jcd,v['title'],karatsu=True)
                else:points=parse_points(fetcher.get('pointrank',jcd=jcd,hd=day),day,jcd,v['title'])
                attempts['points']={'at':stamp,'status':'ok' if points else 'no_data'}
                if points:feed.setdefault('points',{})[day]={**points,'fetched_at':stamp,'source_url':url}
            except Exception:attempts['points']={'at':stamp,'status':'error'}
        for p in sorted((Path(data)/'races'/day).glob(jcd+'*.json')):
            race=read(p,{})
            if race.get('oriten') or not (race.get('before') or {}).get('boats'):continue
            try:deadline=datetime.strptime(day+race['deadline'],'%Y%m%d%H:%M').replace(tzinfo=JST)
            except (KeyError,ValueError):continue
            key=day+'-'+str(race.get('rno',''))
            if not 0 <= (now-deadline).total_seconds() <= 90*60 or key in feed.get('late_exhibition',{}) or not due('ex-'+key,14) or fetcher.exhausted:continue
            try:
                text=fetcher.oriten(jcd,race['rno'],day); ot=parse_oriten(text)
                expected={str(b['frame']):norm(b.get('name')) for b in (race.get('racelist') or {}).get('boats',[])}
                names={str(int(parts[0])):norm(parts[1]) for line in (text or '').splitlines() if len(parts:=line.split('\t'))>=2 and parts[0].strip().isdigit()}
                if ot and len(expected)==6 and all(names.get(f)==name for f,name in expected.items()):
                    feed.setdefault('late_exhibition',{})[key]={**ot,'fetched_at':stamp,'source_url':f'https://race.boatcast.jp/txt/{jcd}/bc_oriten_{day}_{jcd}_{race["rno"]:02}.txt'}
                    attempts['ex-'+key]={'at':stamp,'status':'ok'}
                else:attempts['ex-'+key]={'at':stamp,'status':'no_data'}
            except Exception:attempts['ex-'+key]={'at':stamp,'status':'error'}
        # Past K-files contain results/ST but not necessarily exhibition times.
        # Fill those public numbers gradually, without touching frozen race files.
        filled=0
        for past_folder in sorted((Path(data)/'races').glob('*'),reverse=True):
            if not past_folder.is_dir() or not period[0]<=past_folder.name<day:continue
            for p in sorted(past_folder.glob(jcd+'*.json')):
                if filled>=backfill_limit or fetcher.exhausted:break
                race=read(p,{})
                key=past_folder.name+'-'+str(race.get('rno',''))
                boats=(race.get('racelist') or {}).get('boats',[])
                if len(boats)!=6 or key in feed.get('exhibitions',{}) or not due('before-'+key,60):continue
                if len([b for b in (race.get('before') or {}).get('boats',[]) if b.get('exhibit_time')])==6:continue
                filled+=1
                try:
                    html=fetcher.beforeinfo(jcd,race['rno'],past_folder.name)
                    if not page_matches(BeautifulSoup(html,'html.parser'),past_folder.name,jcd,v['title']):
                        attempts['before-'+key]={'at':stamp,'status':'mismatch'};continue
                    bi=parse_beforeinfo(html)
                    expected={b['frame']:b for b in boats}
                    fetched=bi.get('boats',[])
                    if len(fetched)==6 and set(b['frame'] for b in fetched)==set(expected) and all(norm(b.get('name'))==norm(expected[b['frame']].get('name')) for b in fetched):
                        values=[{'frame':b['frame'],'toban':expected[b['frame']]['toban'],'exhibit_time':b['exhibit_time']} for b in fetched if b.get('exhibit_time') and 3<b['exhibit_time']<30]
                        if len(values)==6:
                            feed.setdefault('exhibitions',{})[key]={'date':past_folder.name,'rno':race['rno'],'boats':values,'fetched_at':stamp}
                    attempts['before-'+key]={'at':stamp,'status':'ok' if key in feed.get('exhibitions',{}) else 'no_data'}
                except Exception:attempts['before-'+key]={'at':stamp,'status':'error'}
        feed['updated_at']=stamp
        save(path,feed)
        return {'jcd':jcd,'precheck':len(feed.get('precheck',{}).get('rows',{})),
                'points':len(feed.get('points',{}).get(day,{}).get('rows',{})),
                'late_exhibition':len(feed.get('late_exhibition',{})), 'past_exhibitions':len(feed.get('exhibitions',{}))}
    with ThreadPoolExecutor(workers) as pool:return [r for r in pool.map(one,idx.get('venues',[])) if r]


def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--now');args=p.parse_args(argv)
    now=datetime.fromisoformat(args.now).replace(tzinfo=JST) if args.now else datetime.now(JST)
    f=Fetcher(max_requests=160,budget=240)
    rows=refresh(DATA,read(DATA/'index.json',{}),now,f)
    print(json.dumps({'meetings':rows,'requests':f.count,'seconds':round(time.time()-f.started)},ensure_ascii=False))
    return 0


if __name__=='__main__':raise SystemExit(main())
