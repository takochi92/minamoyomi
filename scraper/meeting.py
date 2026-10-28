"""Display-only meeting data. Never used by predictions or ticket decisions."""
from __future__ import annotations
import json
import math
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from bs4 import BeautifulSoup


def norm(text):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', text or ''))


def bounds(day, label):
    m = re.search(r'(\d{1,2})/(\d{1,2})\s*[-〜～]\s*(\d{1,2})/(\d{1,2})', label or '')
    if not m:
        return None
    anchor = datetime.strptime(day, '%Y%m%d')
    for year in (anchor.year - 1, anchor.year):
        try:
            sm, sd, em, ed = map(int, m.groups())
            start = datetime(year, sm, sd)
            end = datetime(year + (em < sm), em, ed)
            if start <= anchor <= end and (end - start).days <= 30:
                return start.strftime('%Y%m%d'), end.strftime('%Y%m%d')
        except ValueError:
            pass
    return None


def page_matches(soup, day, jcd, title):
    heading = soup.find('h2')
    if not heading or norm(heading.get_text()) != norm(title):
        return False
    return any(parse_qs(urlparse(a['href']).query).get('hd') == [day] and
               parse_qs(urlparse(a['href']).query).get('jcd') == [jcd]
               for a in soup.select('a[href]'))


def numeric(text):
    t = norm(text)
    return float(t) if re.fullmatch(r'\d+(?:\.\d+)?', t) else None


def parse_precheck(html, day, jcd, title):
    soup = BeautifulSoup(html, 'html.parser')
    if not page_matches(soup, day, jcd, title):
        return None
    table = next((t for t in soup.select('table') if '前検タイム' in norm(t.find('thead').get_text() if t.find('thead') else '')), None)
    if not table:
        return None
    rows = {}
    for tr in table.select('tbody tr'):
        cells = tr.find_all('td', recursive=False)
        if len(cells) != 9:
            continue
        toban = norm(cells[1].get_text())
        value = numeric(cells[8].get_text())
        motor = numeric(cells[4].get_text())
        if re.fullmatch(r'\d{4}', toban) and value and 3 < value < 30 and motor is not None:
            if toban in rows:
                return None
            rows[toban] = {'time': value, 'motor_no': int(motor)}
    return rows or None


def parse_points(html, day, jcd, title, *, karatsu=False):
    soup = BeautifulSoup(html, 'html.parser')
    if karatsu:
        heading = soup.find('h3')
        stamp = soup.select_one('.day')
        text = unicodedata.normalize('NFKC', stamp.get_text(' ', strip=True) if stamp else '')
        m = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', text)
        if not heading or norm(heading.get_text()) != norm(title) or not m or ''.join([m[1],m[2].zfill(2),m[3].zfill(2)]) != day:
            return None
        as_of = text
    else:
        if not page_matches(soup, day, jcd, title):
            return None
        as_of = ''
        for li in soup.select('li'):
            text = unicodedata.normalize('NFKC', li.get_text(' ', strip=True))
            if '終了時点' in text and len(text) < 200:
                as_of = text.split('終了時点')[0] + '終了時点'
                break
    rows = {}
    for table in soup.select('table'):
        head = norm(table.find('thead').get_text() if table.find('thead') else '')
        if '得点率' not in head or not any(x in head for x in ('登録番号','登番')):
            continue
        for tb in table.select('tbody'):
            tr = tb.find('tr')
            cells = tr.find_all('td', recursive=False) if tr else []
            if len(cells) < (6 if karatsu else 8):
                continue
            id_text = norm(cells[1].get_text())
            found = re.match(r'^(\d{4})(?:/|$)', id_text)
            rank = numeric(cells[0].get_text())
            rate = numeric(cells[2 if karatsu else 4].get_text())
            if not found or rank is None or not 1 <= rank <= 200 or rate is None or not 0 <= rate <= 30:
                continue
            toban = found[1]
            if toban in rows:
                return None
            rows[toban] = {'rank': int(rank), 'rate': rate,
                          'n': int(numeric(cells[5].get_text()) or 0) if karatsu else None}
    return {'as_of': as_of, 'rows': rows} if rows else None


def load_feeds(data, day):
    since = (datetime.strptime(day, '%Y%m%d')-timedelta(days=35)).strftime('%Y%m%d')
    out = []
    for p in sorted((Path(data)/'meetings').glob('*.json')):
        if not re.fullmatch(r'\d{8}-\d{2}\.json', p.name) or not since <= p.name[:8] <= day:
            continue
        try:
            v = json.loads(p.read_text(encoding='utf-8'))
            if v.get('start') == p.name[:8] and v.get('jcd') == p.stem[-2:]:
                out.append(v)
        except (OSError,ValueError):
            pass
    return out


def profile(feeds, idx, day, jcd):
    candidates = [f for f in feeds if f.get('jcd') == jcd and f.get('start','9') <= day <= f.get('end','')]
    if candidates:
        return max(candidates, key=lambda f:f['start'])
    for v in idx.get('venues',[]):
        period = bounds(idx.get('date',day), v.get('day')) if v.get('jcd') == jcd else None
        if period and period[0] <= day <= period[1]:
            return {'jcd':jcd,'start':period[0],'end':period[1],'title':v.get('title','')}
    return None


class MeetingIndex:
    def __init__(self, history=(), races=()):
        self.races = {}
        for r in history:
            entries = {int(e[0]): {'toban':str(e[1]),'st':e[3]/100 if e[3] is not None else None,
                       'flag':e[4], 'place':e[5], 'ex':e[6]/100 if len(e)>6 and e[6] else None}
                       for e in r[11]}
            self.races[(r[0],r[1],int(r[2]))] = entries
        for r in races:
            if not all(r.get(k) is not None for k in ('date','jcd','rno')):
                continue
            key=(r['date'],r['jcd'],int(r['rno']))
            entries=self.races.setdefault(key,{})
            for b in (r.get('racelist') or {}).get('boats',[]):
                f=b['frame']; old=entries.get(f,{})
                if old.get('toban') and old['toban'] != b.get('toban'):
                    old={}
                entries[f]={**old,'toban':str(b.get('toban',''))}
            for b in (r.get('before') or {}).get('boats',[]):
                if b.get('exhibit_time') is not None and b['frame'] in entries:
                    entries[b['frame']]['ex']=b['exhibit_time']
            result=r.get('result') or {}
            if result.get('finished'):
                for b in result.get('start',[]):
                    if b.get('frame') in entries:
                        entries[b['frame']].update(st=b.get('st'),flag=b.get('flag',''))
                for b in result.get('order',[]):
                    if b.get('frame') in entries:
                        entries[b['frame']]['place']=b.get('place')
        self.by_racer=defaultdict(list)
        for key, entries in sorted(self.races.items()):
            complete=set(entries)==set(range(1,7)) and all(self.normal(e) or e.get('flag') in ('F','L') for e in entries.values())
            normal=[round(e['st'],2) for e in entries.values() if self.normal(e)]
            for frame,e in entries.items():
                t=e.get('toban','')
                if not re.fullmatch(r'\d{4}',t):
                    continue
                rank=1+sum(v<round(e['st'],2) for v in normal) if complete and self.normal(e) else None
                self.by_racer[(key[1],t)].append({**e,'date':key[0],'rno':key[2],'frame':frame,'rank':rank})

    @staticmethod
    def normal(e):
        v=e.get('st')
        return isinstance(v,(int,float)) and math.isfinite(v) and 0 <= v < 1 and not e.get('flag')

    def summary(self, jcd, toban, start, end, day):
        rows=[r for r in self.by_racer.get((jcd,toban),[]) if start<=r['date']<=min(day,end)]
        ex=[r['ex'] for r in rows if isinstance(r.get('ex'),(int,float)) and math.isfinite(r['ex']) and 3<r['ex']<30]
        st=[r['st'] for r in rows if self.normal(r)]
        ranks=[r['rank'] for r in rows if r.get('rank') is not None]
        results=[r for r in rows if r.get('place') is not None and str(r['place']).strip()]
        return {'ex':sum(ex)/len(ex) if ex else None,'ex_n':len(ex),
                'st':sum(st)/len(st) if st else None,'st_n':len(st),
                'rank':sum(ranks)/len(ranks) if ranks else None,'rank_n':len(ranks),'results':results}
