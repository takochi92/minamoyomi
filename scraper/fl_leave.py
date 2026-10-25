"""Official *published* FL-leave records, isolated from prediction inputs.

Never infer leave consumption from an empty field, inactivity, or elapsed dates.
"""
from __future__ import annotations
import argparse, hashlib, io, re, unicodedata
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
        rows.append({'toban': m[2], 'name': re.sub(r'\s', '', v[1]), 'class': m[1],
                     'branch': v[2], 'days': int(days[1]) if days else None})
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
             'records': [dict(r, start=None, end=None) for r in rows if r['days']]}
    write_json(STORE / 'tsu.json', value)
    print('official FL: Tsu', len(rows), 'participants;', len(value['records']), 'unserved entries', flush=True)


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
            if r.get('start') and r.get('end'):
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
    refresh_tsu()

if __name__ == '__main__':
    main()
