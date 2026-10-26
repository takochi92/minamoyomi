"""Refresh official Heiwajima availability without fabricating measurements.

No ChatGPT/API key, browser session, media decryption, or prediction mutations.
Video import and automatic bow identification are not implemented by this job.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlencode

from scraper.exhibition_views import valid_date

BASE = 'https://front.player.boatrace-cdn.jp'
JST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parents[1]


def official_player(day, race):
    if not valid_date(day) or type(race) is not int or not 1 <= race <= 12:
        raise ValueError('Invalid day or race')
    return BASE + '/player/vod?' + urlencode({'service':'boatcast', 'stadium':'04heiwajima',
        'raceType':'exhibition', 'raceDate':day, 'raceNumber':f'{race:02}', 'autoplay':'0', 'bitrate':'low'})


def parse_setting(raw, day):
    """An entry proves source registration, not decoded playback or analysis."""
    if not valid_date(day) or not isinstance(raw, dict) or not isinstance(raw.get('races'), dict):
        raise ValueError('Invalid official setting')
    found = []
    for race in range(1,13):
        row = raw['races'].get(f'{race:02}')
        if not isinstance(row, dict):
            continue
        if (str(row.get('race_number')) != f'{race:02}' or not isinstance(row.get('ref_id'), str)
                or not row['ref_id'] or not isinstance(row.get('source_type'), str) or not row['source_type']):
            continue
        # Require the selected date/venue/race in the official reference itself.
        suffix = f'-04heiwajima-exhibition-{day}-{race:02}'
        if not row['ref_id'].endswith(suffix):
            continue
        found.append({'date':day, 'jcd':'04', 'rno':race, 'official_url':official_player(day,race),
                      'source_state':'registered', 'analysis_state':'not_measured'})
    return found


def fetch_setting(day, opener=urlopen):
    if not valid_date(day):
        raise ValueError('Invalid day')
    request=Request(BASE+f'/setting/vod/{day}/04heiwajima/exhibition/setting.json',
                    headers={'User-Agent':'Teilog-exhibition-research/1.0', 'Accept':'application/json'})
    with opener(request, timeout=20) as response:
        # Never follow a redirect into a different service.
        if not response.geturl().startswith(BASE+'/setting/vod/'):
            raise ValueError('Unexpected setting redirect')
        data=response.read(512_001)
    if len(data)>512_000:
        raise ValueError('Excessive setting size')
    return json.loads(data)


def merge_records(previous, fresh, day):
    """Keep reviewed evidence immutable and never carry it into another race/day."""
    existing = {(r.get('date'),r.get('jcd'),r.get('rno')):r for r in previous.get('records',[]) if isinstance(r,dict)}
    result = {key:dict(value) for key,value in existing.items()}
    fresh_keys=set()
    for row in fresh:
        key=(row['date'],row['jcd'],row['rno']);fresh_keys.add(key)
        old=existing.get(key,{})
        merged={**row}
        if 'reference' in old:
            merged['reference']=old['reference']
            merged['analysis_state']='reviewed_video_reference'
        result[key]=merged
    # A successfully read setting may remove a registration. Preserve the record
    # and evidence, but stop presenting its old source link as currently confirmed.
    for key,row in result.items():
        if key[0]==day and key[1]=='04' and key not in fresh_keys:
            row['source_state']='unavailable'
    ordered=sorted(result.values(),key=lambda r:(str(r.get('date','')),str(r.get('jcd','')),int(r.get('rno',0))))
    return {'schema':1,'source_page':'https://race.boatcast.jp/replay?jo=04&md=T','records':ordered}


def write_json(path, value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    content=json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n'
    if path.exists() and path.read_text(encoding='utf-8')==content:
        return False
    temporary=path.with_name(path.name+'.tmp')
    temporary.write_text(content,encoding='utf-8');os.replace(temporary,path)
    return True


def run(day, registry, status, *, fetcher=fetch_setting, now=None):
    if not valid_date(day):
        raise ValueError('Invalid day')
    previous=json.loads(Path(registry).read_text(encoding='utf-8')) if Path(registry).exists() else {'records':[]}
    stamp=(now or datetime.now(JST)).isoformat(timespec='seconds')
    health={'schema':1,'date':day,'checked_at':stamp, 'venue':'04', 'source_registered_races':0,
            'source_state':'unknown','automatic_video_analysis_enabled':False,
            'automatic_video_analysis_state':'not_implemented','prediction_used':False}
    changed=False
    try:
        fresh=parse_setting(fetcher(day),day)
        health.update(source_state='checked',source_registered_races=len(fresh))
        changed=write_json(registry,merge_records(previous,fresh,day))
    except HTTPError as error:
        health['source_state']='waiting' if error.code==404 else 'fetch_error'
        health['error']='not_available' if error.code==404 else 'http_'+str(error.code)
    except (URLError,TimeoutError,OSError,ValueError,KeyError,TypeError):
        # Response bodies, headers, signed URLs and credentials never go to logs.
        health.update(source_state='fetch_error',error='source_unavailable_or_invalid')
    health['registry_changed']=changed
    health['reviewed_races']=sum(r.get('date')==day and r.get('jcd')=='04' and bool(r.get('reference')) for r in previous.get('records',[]))
    write_json(status,health)
    return health


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date',default=datetime.now(JST).strftime('%Y%m%d'))
    parser.add_argument('--registry',type=Path,default=ROOT/'site/data/exhibition/research.json')
    parser.add_argument('--status',type=Path,default=ROOT/'site/data/exhibition/status.json')
    args=parser.parse_args()
    result=run(args.date,args.registry,args.status)
    print(json.dumps(result,ensure_ascii=False))
    if result['source_state']=='fetch_error':
        raise SystemExit(1)


if __name__=='__main__':
    main()
