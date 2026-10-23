"""Archive the official SG/PG1/G1 record book, including historical finals.

Category is the official record-book grouping, not a guessed historical grade.
Each published result retains its original source URL and download checksum.
"""
from __future__ import annotations
import argparse,hashlib,re,time,unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta
from urllib.parse import urljoin,urlparse,parse_qs
from bs4 import BeautifulSoup
from .database_sources import BASE,JST,session,fetch,read_json,write_json

INDEX='https://www.boatrace.jp/owpc/pc/data/record/index'
ROOT=BASE/'championships'
norm=lambda s:re.sub(r'\s+','',unicodedata.normalize('NFKC',s))


def parse_index(content):
    page=BeautifulSoup(content,'html.parser');out={}
    for table in page.select('table'):
        headers=[x.get_text(' ',strip=True) for x in table.select('thead th')]
        if not headers:continue
        for row in table.select('tbody tr'):
            for col,cell in enumerate(row.find_all('td',recursive=False)):
                for a in cell.select('a[href]'):
                    if '/record/list?' not in a['href']:continue
                    url=urljoin(INDEX,a['href']);category=parse_qs(urlparse(url).query).get('category',[''])[0]
                    if category.isdigit():out[category]={'id':category,'name':a.get_text(strip=True),'group':headers[min(col,len(headers)-1)],'source':url}
    if not out:raise ValueError('Official record categories missing')
    return list(out.values())


def parse_list(content,category):
    page=BeautifulSoup(content,'html.parser');records=[]
    for body in page.select('table tbody'):
        rows=body.find_all('tr',recursive=False)
        if not rows:continue
        cells=rows[0].find_all('td',recursive=False)
        if len(cells)<5:continue
        date=cells[1].get_text(strip=True)
        if not re.fullmatch(r'\d{4}/\d{2}/\d{2}',date):continue
        edition=cells[0].get_text(strip=True);venue=cells[2].find('img')
        a=body.select_one('a[href*="listdetail?"]')
        if not a:continue
        url=urljoin(INDEX,a['href']);number=parse_qs(urlparse(url).query).get('record_no',[''])[0]
        if not number.isdigit():continue
        winners=[re.sub(r'\s+',' ',c.get_text(' ',strip=True)) for c in body.select('td.is-victory')]
        records.append({'category':category['id'],'name':category['name'],'group':category['group'],
                        'number':number,'edition':edition,'date':date.replace('/',''),
                        'venue':venue.get('alt') if venue else cells[2].get_text(strip=True),'winners_label':winners,'source':url})
    if not records:raise ValueError('Official title list has no dated records')
    return records


def parse_detail(content,record):
    page=BeautifulSoup(content,'html.parser');divisions=[]
    for table in page.select('table'):
        headers=[norm(h.get_text()) for h in table.select('thead th')]
        if '登番' not in headers or '着' not in headers:continue
        entries=[]
        for tr in table.select('tbody tr'):
            cells=tr.find_all('td',recursive=False)
            if len(cells)!=len(headers):continue
            row={k:re.sub(r'\s+',' ',unicodedata.normalize('NFKC',c.get_text(' ',strip=True))).strip() for k,c in zip(headers,cells)}
            t=norm(row.get('登番',''))
            if not t.isdigit() or not 1<=len(t)<=4:continue
            entries.append({'player':t.zfill(4),'name':row.get('レーサー',''),'place':row['着'],'fields':row})
        if entries:divisions.append(entries)
    if not divisions:raise ValueError('Official final table not recognized')
    # Preserve all original field labels; old boats/classes may have more than
    # one final in a single event page, and must not be collapsed together.
    return {**record,'divisions':divisions}


def collect(budget_seconds=1800):
    deadline=time.monotonic()+budget_seconds;s=session()
    categories=parse_index(fetch(s,INDEX));write_json(ROOT/'categories.json.gz',categories)
    all_records=[];fail=[]
    for cat in categories:
        dest=ROOT/'lists'/(cat['id']+'.json.gz')
        old=read_json(dest)
        today=datetime.now(JST).strftime('%Y%m%d')
        try:
            if old and old.get('checked')==today:records=old['records']
            else:
                blob=fetch(s,cat['source']);records=parse_list(blob,cat)
                write_json(dest,{'records':records,'source':cat['source'],'checked':today,'sha256':hashlib.sha256(blob).hexdigest()})
            all_records.extend(records)
        except Exception as ex:
            fail.append({'category':cat['id'],'error':type(ex).__name__})
            if old:all_records.extend(old['records'])
        print('official titles',cat['id'],cat['name'],flush=True)
    def one(record):
        dest=ROOT/'finals'/(record['category']+'-'+record['number']+'.json.gz')
        if time.monotonic()>=deadline:return
        if dest.exists():
            recent=(datetime.now(JST)-timedelta(days=14)).strftime('%Y%m%d')
            cached=read_json(dest,{})
            if record['date']<recent or cached.get('downloaded_at','').startswith(datetime.now(JST).strftime('%Y-%m-%d')):return
        try:
            blob=fetch(session(),record['source']);result=parse_detail(blob,record)
            result.update(sha256=hashlib.sha256(blob).hexdigest(),downloaded_at=datetime.now(JST).isoformat())
            write_json(dest,result)
        except Exception as ex:fail.append({'source':record['source'],'error':type(ex).__name__})
    with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(one,sorted(all_records,key=lambda r:r['date'],reverse=True)))
    saved=len(list((ROOT/'finals').glob('*.json.gz')))
    report={'categories':len(categories),'listed_finals':len(all_records),'saved_finals':saved,'errors':fail,'checked_at':datetime.now(JST).isoformat()}
    write_json(ROOT/'coverage.json',report);print({k:v for k,v in report.items() if k!='errors'} | {'errors':len(fail)},flush=True)


def records():
    return [read_json(p) for p in (ROOT/'finals').glob('*.json.gz')]


def player_index(as_of):
    from collections import defaultdict
    roster={};index=defaultdict(list)
    for record in sorted(records(),key=lambda r:r['date']):
        if record['date']>=as_of:continue
        for division,entries in enumerate(record['divisions']):
            for entry in entries:
                t=entry['player'];roster[t]={'name':entry['name'],'branch':entry['fields'].get('支部',''),'class':'','historical':True,'period':'公式大会記録 '+record['date']}
                index[t].append({k:record[k] for k in ('category','number','date','name','group','edition','venue','source')} | {'division':division,'place':entry['place']})
    for values in index.values():values.sort(key=lambda r:r['date'],reverse=True)
    return roster,index


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--budget-seconds',type=int,default=1800);a=ap.parse_args();collect(max(1,a.budget_seconds))
