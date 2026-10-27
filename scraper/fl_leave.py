"""Official *published* FL-leave records, isolated from prediction inputs.

Never infer leave consumption from an empty field, inactivity, or elapsed dates.
"""
from __future__ import annotations
import argparse, hashlib, io, re, unicodedata
from pathlib import Path
from datetime import datetime
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from .database_sources import BASE, JST, fetch, session, read_json, write_json

STORE = BASE / 'season_watch/fl_leave'
TSU_INDEX = 'https://www.boatrace-tsu.com/modules/raceinfo/?page=index_pdf'


def parse_tsu(text):
    text = unicodedata.normalize('NFKC', text)
    if not all(s in re.sub(r'\s', '', text) for s in ('F・L休み', '未消化', '前検日時点')):
        raise ValueError('Official unserved-leave heading missing')
    # Works for both interleaved two-column extraction and each column in order.
    starts = list(re.finditer(r'([AB][12])\s+(\d{4})\s+', text))
    rows = []
    for i, m in enumerate(starts):
        chunk = text[m.end():starts[i+1].start() if i+1 < len(starts) else len(text)]
        v = re.match(r'(.+?)\s+(\S+)\s+(\d{1,2}\.\d{2})(?!\d)(.*)', chunk, re.S)
        if not v:
            raise ValueError('Official table row not recognized')
        tail = v[4].split('※')[0]
        days = re.match(r'\s*(\d{1,3})\s*日', tail)
        served=bool(re.match(r'\s*消化済(?:み)?(?:\s|$)',tail)) or bool(days and int(days[1])==0)
        rows.append({'toban': m[2], 'name': re.sub(r'\s', '', v[1]), 'class': m[1],
                     'branch': v[2], 'days': int(days[1]) if days else (0 if served else None),
                     'explicit_served':served})
    if not 30 <= len(rows) <= 60 or len({r['toban'] for r in rows}) != len(rows):
        raise ValueError('Official participant table incomplete')
    return rows


def refresh_tsu():
    from pypdf import PdfReader
    s = session()
    html = fetch(s, TSU_INDEX)
    soup = BeautifulSoup(html, 'html.parser')
    urls = [urljoin(TSU_INDEX, a['href']) for a in soup.select('a[href]')]
    urls = [u for u in urls if urlparse(u).hostname == 'www.boatrace-tsu.com'
            and re.fullmatch(r'/uploads/cdn/pdf/syussou/09_\d{8}_1\.pdf', urlparse(u).path)]
    if not urls:
        raise ValueError('Official current cover link missing')
    url = max(urls, key=lambda u: urlparse(u).path)
    date = re.search(r'09_(\d{8})_1', url)[1]
    now = datetime.now(JST)
    if abs((datetime.strptime(date, '%Y%m%d').date() - now.date()).days) > 7:
        raise ValueError('Official programme date too old')
    raw = fetch(s, url)
    if not raw.startswith(b'%PDF'):
        raise ValueError('Official programme is not a PDF')
    text = '\n'.join(p.extract_text() or '' for p in PdfReader(io.BytesIO(raw)).pages)
    rows = parse_tsu(text)
    value = {'venue': '津', 'jcd': '09', 'document_date': date, 'source': url,
             'checked_at': now.isoformat(), 'sha256': hashlib.sha256(raw).hexdigest(),
             'basis': '前検日時点', 'participants': rows,
             'records': [dict(r, start=None, end=None) for r in rows if r['days'] or r['explicit_served']]}
    write_json(STORE / 'tsu.json', value)
    print('official FL: Tsu', len(rows), 'participants;', len(value['records']), 'unserved entries', flush=True)


def parse_omura(text, today, racers):
    soup=BeautifulSoup(text,'html.parser');area=soup.select_one('.tinymce')
    if area is None:raise ValueError('Official Omura notice missing')
    full=unicodedata.normalize('NFKC',soup.get_text(' ',strip=True))
    y,m,d=int(today[:4]),int(today[4:6]),int(today[6:8])
    if f'{y}年{m}月{d}日' not in full:raise ValueError('Official Omura notice date mismatch')
    names={}
    norm=lambda s:re.sub(r'\s','',unicodedata.normalize('NFKC',s))
    for t,info in racers.items():names.setdefault(norm(info.get('name','')),[]).append(t)
    active=False;days=None;records=[]
    for p in area.find_all('p',recursive=False):
        line=unicodedata.normalize('NFKC',p.get_text(' ',strip=True))
        if norm(line)=='F・L休み未消化選手':active=True;continue
        if not active:continue
        if line.startswith('※'):break
        band=re.fullmatch(r'◎\s*(\d+)\s*[~〜～-]\s*(\d+)日',line)
        if band:
            days=tuple(map(int,band.groups()))
            if not 1<=days[0]<=days[1]<=365:raise ValueError('Official leave band invalid')
            continue
        if not line:continue
        ids=names.get(norm(line),[])
        if days is None or len(ids)!=1:raise ValueError('Official leave identity not unique')
        records.append({'toban':ids[0],'name':norm(line),'days':None,'days_min':days[0],'days_max':days[1],'start':None,'end':None})
    if not active or not records:raise ValueError('Official Omura leave list unavailable')
    if len({r['toban'] for r in records})!=len(records):raise ValueError('Duplicate official leave identity')
    return records


def refresh_omura():
    now=datetime.now(JST);today=now.strftime('%Y%m%d')
    url=f'https://pic.omurakyotei.jp/yosou/trouble.php?day={today}&race=01'
    raw=fetch(session(),url)
    racers=(read_json(Path(__file__).with_name('racers.json'),{}) or {}).get('racers',{})
    records=parse_omura(raw,today,racers)
    write_json(STORE/'omura.json',{'venue':'大村','jcd':'24','document_date':today,'source':url,'checked_at':now.isoformat(),'sha256':hashlib.sha256(raw).hexdigest(),'basis':'公式お知らせのF・L休み未消化選手欄','records':records})
    print('official FL: Omura',len(records),'unserved entries',flush=True)


def published_records(today):
    rows, sources = [], []
    for path in sorted(STORE.glob('*.json')):
        doc = read_json(path, {})
        if not doc.get('source') or not doc.get('sha256'):
            continue
        checked = doc.get('checked_at', '')[:10].replace('-', '')
        if not checked or checked > today:
            continue
        sources.append({k: doc.get(k) for k in ('venue', 'source', 'document_date', 'checked_at', 'basis')})
        age = (datetime.strptime(today, '%Y%m%d') - datetime.strptime(checked, '%Y%m%d')).days
        for item in doc.get('records', []):
            r = {**item, **{k: doc[k] for k in ('source', 'venue', 'document_date', 'checked_at', 'basis')}}
            if r.get('explicit_served') is True:
                r['status']='served_confirmed' if age<=7 else 'stale_unverified'
            elif r.get('start') and r.get('end'):
                datetime.strptime(r['start'], '%Y%m%d');datetime.strptime(r['end'], '%Y%m%d')
                if r['start'] > r['end']:
                    continue
                r['status'] = 'scheduled' if today < r['start'] else 'in_period' if today <= r['end'] else 'ended_unverified'
            else:
                r['status'] = 'snapshot_unserved' if age <= 7 else 'stale_unverified'
            rows.append(r)
    return {'records': rows, 'sources': sources, 'as_of': today}


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    failed=False
    for refresh in (refresh_tsu,refresh_omura):
        try:refresh()
        except Exception as exc:
            print('official FL:',refresh.__name__,'kept previous snapshot:',type(exc).__name__,flush=True);failed=True
    if failed:raise SystemExit(1)

if __name__ == '__main__':
    main()
