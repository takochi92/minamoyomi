"""Official downloads for the public database. Does not update prediction inputs.

python -m scraper.database_sources --periods
python -m scraper.database_sources --start 20010101 --workers 2
"""
from __future__ import annotations
import argparse, gzip, hashlib, json, re, threading, time, unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from .kfile import parse_k, RE_ENTRY
from .lzh import unlzh

BASE = Path(__file__).parent / 'database'
DOWNLOAD = 'https://www.boatrace.jp/owpc/pc/extra/data/download.html'
JST = timezone(timedelta(hours=9))
_lock = threading.Lock()
_last_request = 0.0
_deadline = float('inf')
PARSER_VERSION=3
ARCHIVE_START='19960101'


def needs_update(day,entry,now=None):
    if not entry:return True
    if entry.get('parser_version',1)<PARSER_VERSION and (entry.get('status')!='saved' or (entry.get('parser_version',1)<2 and day<'20030101')):return True
    if entry.get('status')=='saved':return False
    now=now or datetime.now(JST)
    try:checked=datetime.fromisoformat(entry['checked_at'])
    except (KeyError,ValueError):return True
    wait_days=30 if entry.get('http_status')==404 or entry.get('error')=='ValueError' else 1
    return now-checked>=timedelta(days=wait_days)


def read_json(path, default=None):
    if not path.exists(): return default
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path,'rt',encoding='utf-8') as f:return json.load(f)


def write_json(path, value, compression=9):
    path.parent.mkdir(parents=True,exist_ok=True)
    raw=json.dumps(value,ensure_ascii=False,separators=(',',':')).encode()
    tmp=path.with_name(path.name+'.tmp')
    tmp.write_bytes(gzip.compress(raw,compresslevel=compression,mtime=0) if path.suffix=='.gz' else raw)
    tmp.replace(path)


def session():
    s=requests.Session();s.trust_env=False
    s.headers['User-Agent']='Mozilla/5.0 (compatible; TeilogData/1.0; official-download archive)'
    return s


def fetch(s,url):
    global _last_request
    for attempt in range(3):
        with _lock:
            time.sleep(max(0,.36-(time.monotonic()-_last_request)))
            _last_request=time.monotonic()
        r=s.get(url,timeout=(10,30))
        if r.status_code in (429,500,502,503,504):
            time.sleep(3*(attempt+1));continue
        r.raise_for_status()
        if len(r.content)>8_000_000:raise ValueError('Unexpected official download size')
        return r.content
    raise RuntimeError('Official source temporarily unavailable')


def integer(line,start,size):
    raw=line[start:start+size].strip()
    return int(raw) if raw.isdigit() else None


def parse_period(raw):
    """Fixed official layout, including pre-2014 location (not silently a branch)."""
    players={};term=None
    for line in raw.splitlines():
        if len(line)<402 or not line[:4].isdigit():continue
        year,half=integer(line,174,4),integer(line,178,1)
        begin,end=line[179:187].decode('ascii'),line[187:195].decode('ascii')
        if not year or half not in (1,2):raise ValueError('Unrecognized official period header')
        datetime.strptime(begin,'%Y%m%d');datetime.strptime(end,'%Y%m%d')
        key=f'{year}-{half}'
        if term and term['id']!=key:raise ValueError('Mixed official periods')
        term={'id':key,'year':year,'half':half,'from':begin,'through':end}
        text=lambda a,b: re.sub(r'[\s　]+',' ',line[a:b].decode('cp932',errors='replace')).strip()
        starts=integer(line,72,3);wins=integer(line,66,3);second=integer(line,69,3)
        if starts is None or wins is None or second is None or wins+second>starts:raise ValueError('Inconsistent official counts')
        courses=[]
        for c in range(6):
            at=198+c*34
            places=[integer(line,at+i*3,3) for i in range(6)]
            accidents={k:integer(line,at+18+i*2,2) for i,k in enumerate(('F','L0','L1','K0','K1','S0','S1','S2'))}
            courses.append({'entries':integer(line,82+c*13,3),'places':places,'accidents':accidents,
                            'top2':(integer(line,85+c*13,4) or 0)/10,
                            'st':(integer(line,89+c*13,3) or 0)/100,
                            'st_rank':(integer(line,92+c*13,3) or 0)/100})
        old=(year,half)<(2014,2)
        t=line[:4].decode()
        players[t]={'name':text(4,20),'kana':text(20,35),'branch':None if old else text(35,39),
                    'location':text(35,39) if old else None,'class':text(39,41),
                    'lady':integer(line,48,1)==2,'age':integer(line,49,2),
                    'height':integer(line,51,3),'weight':integer(line,54,2),'blood':text(56,58),
                    'ki':integer(line,195,3) or None,'birthplace':text(410,416) if len(line)>=416 else None,
                    'birth_era':text(41,42),'birth_date':text(42,48),
                    'win':(integer(line,58,4) or 0)/100,'top2':(integer(line,62,4) or 0)/10,
                    'starts':starts,'wins':wins,'second':second,'finals':integer(line,75,2),
                    'titles':integer(line,77,2),'st':(integer(line,79,3) or 0)/100,'courses':courses,
                    'prior_classes':[text(160+i*2,162+i*2) for i in range(3)],
                    'prior_ability':(integer(line,166,4) or 0)/100,'ability':(integer(line,170,4) or 0)/100,
                    'no_course_accidents':{k:integer(line,402+i*2,2) for i,k in enumerate(('L0','L1','K0','K1'))}}
    if not players or not term:raise ValueError('No valid official period records')
    return {**term,'players':players,'schema':2}


def download_periods():
    s=session();page=BeautifulSoup(fetch(s,DOWNLOAD),'html.parser')
    links=list(dict.fromkeys(urljoin(DOWNLOAD,a['href']) for a in page.select('a[href]') if re.search(r'fan\d{4}\.lzh$',a['href'])))
    if not links:raise ValueError('Official period listing was not recognized')
    done=[];fail=[]
    for url in links:
        name=url.rsplit('/',1)[-1];dest=BASE/'periods'/(name+'.json.gz')
        try:
            if not dest.exists() or read_json(dest,{}).get('schema',1)<2:
                raw=fetch(s,url);period=parse_period(unlzh(raw))
                period.update(source=url,sha256=hashlib.sha256(raw).hexdigest(),downloaded_at=datetime.now(JST).isoformat())
                write_json(dest,period)
            done.append(name)
        except Exception as ex:fail.append({'file':name,'error':type(ex).__name__})
        print('period',name,'saved' if name in done else 'unavailable',flush=True)
    report={'source':DOWNLOAD,'listed':len(links),'saved':len(done),'missing':fail,'checked_at':datetime.now(JST).isoformat()}
    write_json(BASE/'period_coverage.json',report)
    return report


def normalize_k(raw):
    text=raw.decode('cp932',errors='replace')
    # Old official files use YY/MM/DD, spaced weather, and extra blank lines.
    # Normalize only this independent archive; never rewrite prediction input.
    lines=[]
    for line in text.replace('\r\n','\n').replace('\r','\n').split('\n'):
        if not line.strip():continue
        line=re.sub(r'(第\s*\d+日\s+)(\d{2})(/\s*\d{1,2}/\s*\d{1,2})',lambda m:m[1]+str((1900 if int(m[2])>=80 else 2000)+int(m[2]))+m[3],line)
        line=re.sub(r'(H\d{4}m)\s+(.*?)\s*風',lambda m:m[1]+' '+(re.sub(r'\s+','',m[2]) or '未確認')+' 風',line)
        # Some official non-established races leave a finisher's place blank.
        # Preserve that unknown code so following F rows are still readable.
        line=re.sub(r'^\s{4,}([1-6])\s+(\d{4})\s',r'   ?  \1 \2 ',line)
        if re.match(r'^\s*\d{1,2}R.*H\d{4}m',line):
            line=re.sub(r'(風\s+)(.*?)(\d+)m',lambda m:m[1]+(re.sub(r'\s+','',m[2]) or ('無風' if int(m[3])==0 else '不明'))+m[3]+'m',line)
        lines.append(line)
    return '\n'.join(lines)


def parse_database_k(raw):
    text=normalize_k(raw);races=parse_k(text)
    context={};entry_counts={};jcd=None;title_next=False;title='';day=None;current_race=None
    for line in text.replace('\r','').split('\n'):
        m=re.match(r'^(\d{2})KBGN',line)
        if m:jcd=m[1];title='';day=None;title_next=False;current_race=None
        if '競走成績' in line and '***' in unicodedata.normalize('NFKC',line):title_next=True;continue
        if title_next and line.strip():title=line.strip();title_next=False
        m=re.search(r'第\s*(\d+)日\s+(\d{4})/\s*(\d{1,2})/\s*(\d{1,2})',line)
        if m:day=int(m[1])
        m=re.match(r'^\s*(\d{1,2})R\s+(.*?)\s*H(\d{4})m',unicodedata.normalize('NFKC',line))
        if m and jcd:
            label=unicodedata.normalize('NFKC',title)
            label=re.sub(r'GIII','G3',label);label=re.sub(r'GII','G2',label);label=re.sub(r'GI','G1',label)
            grade=re.match(r'^(SG|PG1|G[123])(?=[^A-Za-z0-9]|$)',label)
            context[(jcd,int(m[1]))]={'title':title,'race_name':re.sub(r'\s+','',m[2]),'day':day,'grade':grade[1] if grade else None,
                                      'grade_source':'official_title_prefix' if grade else None}
            current_race=(jcd,int(m[1]))
            entry_counts[current_race]=0
        if current_race and RE_ENTRY.match(line):entry_counts[current_race]+=1
        decision=re.search(r'決まり手\s+([^\s]+)',line)
        if decision and current_race in context:
            context[current_race]['decision']=decision[1].strip()
    expected={k for k,n in entry_counts.items() if n>=2}
    if not expected.issubset({(r['jcd'],r['rno']) for r in races}):
        raise ValueError('Official race sections missing after parsing')
    records=[]
    for r in races:
        ents=[]
        for e in r['entries']:
            ents.append([e['frame'],e['toban'],e['course'],round(e['st']*100) if e['st'] is not None else None,e['st_flag'],
                         e['place'] if e['place'] is not None else e['code'],round(e['exhibit_time']*100) if e['exhibit_time'] else None,None,e['motor_no'],e['boat_no'],e['name']])
            if not ents[-1][4] and e['code'] in ('F','L'):ents[-1][4]=e['code']
        info=context.get((r['jcd'],r['rno']),{})
        records.append([r['date'],r['jcd'],r['rno'],r['kimarite'] or info.get('decision',''),r['wind_dir'],r['wind_speed'],r['wave'],int(r['fixed']),
                        r.get('trifecta'),r.get('trifecta_payout'),r.get('trifecta_ninki'),ents,context.get((r['jcd'],r['rno']),{})])
    return records


def month_dates(start,end):
    out={};d=datetime.strptime(start,'%Y%m%d');stop=datetime.strptime(end,'%Y%m%d')
    while d<=stop:
        value=d.strftime('%Y%m%d');out.setdefault(value[:6],[]).append(value);d+=timedelta(days=1)
    return dict(sorted(out.items(),reverse=True))


def archive_month(item,refresh=False):
    ym,days=item;dest=BASE/'races'/(ym+'.jsonl.gz');audit=BASE/'sources'/(ym+'.json.gz')
    if time.monotonic()>=_deadline:return {'month':ym,'status':'deferred'}
    records={};provenance=read_json(audit,{})
    if dest.exists():
        with gzip.open(dest,'rt',encoding='utf-8') as f:
            for r in map(json.loads,f):
                for e in r[11]:
                    if not e[4] and e[5] in ('F','L'):e[4]=e[5]
                records[(r[0],r[1],r[2])]=r
    s=session()
    for day in sorted(days,reverse=True):
        if time.monotonic()>=_deadline:break
        old=provenance.get(day,{})
        reparse_old=day<'20030101' and old.get('parser_version',1)<2
        if not refresh and old.get('status')=='saved' and not reparse_old:continue
        if not refresh and old and old.get('status')!='saved' and not needs_update(day,old):continue
        url=f'https://www1.mbrace.or.jp/od2/K/{ym}/k{day[2:]}.lzh'
        try:
            blob=fetch(s,url);values=parse_database_k(unlzh(blob))
            if not values:raise ValueError('No parsed races; not treated as a non-racing day')
            if any(r[0]!=day for r in values):raise ValueError('Official result date does not match requested file')
            # A fresh official day replaces its old rows, including cancellations.
            records={k:v for k,v in records.items() if k[0]!=day}
            for r in values:records[(r[0],r[1],r[2])]=r
            provenance[day]={'status':'saved','races':len(values),'source':url,'sha256':hashlib.sha256(blob).hexdigest(),'parser_version':PARSER_VERSION,'checked_at':datetime.now(JST).isoformat()}
        except Exception as ex:
            # A failed refresh never erases a previously verified source.
            if provenance.get(day,{}).get('status')!='saved':provenance[day]={'status':'unavailable','error':type(ex).__name__,'source':url,'parser_version':PARSER_VERSION,'http_status':getattr(getattr(ex,'response',None),'status_code',None),'checked_at':datetime.now(JST).isoformat()}
        if int(day[-2:])%7==0:print('archive progress',ym,day,flush=True)
    dest.parent.mkdir(parents=True,exist_ok=True)
    data=''.join(json.dumps(records[k],ensure_ascii=False,separators=(',',':'))+'\n' for k in sorted(records))
    tmp=dest.with_name(dest.name+'.tmp');tmp.write_bytes(gzip.compress(data.encode(),mtime=0));tmp.replace(dest)
    write_json(audit,provenance)
    report={'month':ym,'races':len(records),'days':sum(x['status']=='saved' for x in provenance.values()),'unavailable':sum(x['status']!='saved' for x in provenance.values())}
    print(json.dumps(report),flush=True)
    return report


def main():
    global _deadline
    ap=argparse.ArgumentParser();ap.add_argument('--periods',action='store_true');ap.add_argument('--start');ap.add_argument('--end');ap.add_argument('--workers',type=int,default=2);ap.add_argument('--refresh',action='store_true');ap.add_argument('--backfill-months',type=int,default=0);ap.add_argument('--budget-seconds',type=int,default=6000)
    a=ap.parse_args()
    _deadline=time.monotonic()+max(1,a.budget_seconds)
    if a.periods:download_periods()
    if a.start:
        end=a.end or (datetime.now(JST)-timedelta(days=1)).strftime('%Y%m%d')
        with ThreadPoolExecutor(max_workers=max(1,min(a.workers,24))) as pool:
            list(pool.map(lambda item:archive_month(item,a.refresh),month_dates(a.start,end).items()))
    if a.backfill_months:
        end=(datetime.now(JST)-timedelta(days=1)).strftime('%Y%m%d')
        pending=[]
        for ym,days in month_dates(ARCHIVE_START,end).items():
            audit=read_json(BASE/'sources'/(ym+'.json.gz'),{})
            if any(needs_update(d,audit.get(d)) for d in days):pending.append((ym,days))
            if len(pending)>=a.backfill_months:break
        with ThreadPoolExecutor(max_workers=max(1,min(a.workers,24))) as pool:list(pool.map(archive_month,pending))

if __name__=='__main__':main()
