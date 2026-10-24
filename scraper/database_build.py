"""Compile the independent official archive into small static player datasets.

The SQLite file is a disposable build cache, never a prediction input. Public
summaries and per-player histories are gzip files committed separately.
"""
from __future__ import annotations
import argparse, gzip, hashlib, json, re, sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from . import racer_database as rd
from .database_sources import BASE, JST, read_json, write_json

ROOT = Path(__file__).resolve().parent.parent


def periods():
    return sorted((read_json(p) for p in (BASE/'periods').glob('*.json.gz')), key=lambda x:(x['year'],x['half']))


def roster_catalog(terms):
    roster={};by_player=defaultdict(list)
    for term in terms:
        for t,info in term['players'].items():
            roster[t]={**info,'branch':info.get('branch') or '', 'period':term['id']}
            by_player[t].append({k:term[k] for k in ('id','year','half','from','through','source')} | {'stats':info})
    latest=terms[-1]['id'] if terms else None
    for info in roster.values():info['historical']=info['period']!=latest
    return roster,by_player


def open_cache(path):
    path.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path)
    db.executescript('''PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, stamp TEXT);
    CREATE TABLE IF NOT EXISTS races(day TEXT, venue TEXT, race INTEGER, payload TEXT, PRIMARY KEY(day,venue,race));
    CREATE TABLE IF NOT EXISTS entries(player TEXT, day TEXT, venue TEXT, race INTEGER, row TEXT, PRIMARY KEY(player,day,venue,race));
    CREATE INDEX IF NOT EXISTS entry_player ON entries(player,day);
    CREATE INDEX IF NOT EXISTS entry_day ON entries(day);
    ''')
    return db


def ingest(db, files):
    for path in files:
        # Git checkouts change mtimes; content hashes preserve the daily cache.
        stamp=hashlib.sha256(path.read_bytes()).hexdigest()
        old=db.execute('SELECT stamp FROM files WHERE path=?',(str(path),)).fetchone()
        if old and old[0]==stamp:continue
        count=0;race_rows=[];entry_rows=[];keys=[]
        # Archives and tests may use different filenames: derive protected
        # keys from actual content, rather than assuming a source directory.
        month=path.name[:6]
        candidates=db.execute('SELECT day,venue,race,payload FROM races WHERE day BETWEEN ? AND ?',(month+'01',month+'31')) if re.fullmatch(r'\d{6}',month) else db.execute('SELECT day,venue,race,payload FROM races')
        protected={(d,j,r) for d,j,r,raw in candidates if len(json.loads(raw))>12}
        protected_days={key[0] for key in protected}
        with gzip.open(path,'rt',encoding='utf-8') as f:
            for race in map(json.loads,f):
                # Rich K-file rows take precedence over legacy records.
                if len(race)<13:
                    if race[0] in protected_days:continue
                race_rows.append((*race[:3],json.dumps(race,ensure_ascii=False,separators=(',',':'))))
                keys.append(race[:3])
                index=rd.build_index([race],'99991231')
                for t,rows in index['players'].items():
                    row=rows[0]
                    row.append(race[12] if len(race)>12 else {})
                    entry_rows.append((t,*race[:3],json.dumps(row,ensure_ascii=False,separators=(',',':'))))
                count+=1
        if path.parent==BASE/'races':
            verified_days={r[0] for r in race_rows}
            db.executemany('DELETE FROM races WHERE day=?',[(d,) for d in verified_days])
            db.executemany('DELETE FROM entries WHERE day=?',[(d,) for d in verified_days])
        db.executemany('INSERT OR REPLACE INTO races VALUES(?,?,?,?)',race_rows)
        # Remove replaced race entries as a single indexed month operation, not
        # a full entries-table scan for every race.
        if keys:
            for month in {k[0][:6] for k in keys}:
                existing={(d,j,r) for d,j,r in keys if d.startswith(month)}
                stale=[(t,d,j,r) for t,d,j,r in db.execute('SELECT player,day,venue,race FROM entries WHERE day BETWEEN ? AND ?',(month+'01',month+'31')) if (d,j,r) in existing]
                db.executemany('DELETE FROM entries WHERE player=? AND day=? AND venue=? AND race=?',stale)
        db.executemany('INSERT OR REPLACE INTO entries VALUES(?,?,?,?,?)',entry_rows)
        db.execute('INSERT OR REPLACE INTO files VALUES(?,?)',(str(path),stamp));db.commit()
        print(f'indexed {path.name}: {count} races',flush=True)


def event_summary(db,as_of):
    events={};high=[];accidents=[];venues={};combinations=Counter();ties=[]
    for (raw,) in db.execute('SELECT payload FROM races WHERE day<? ORDER BY day,venue,race',(as_of,)):
        r=json.loads(raw);ents=r[11];meta=r[12] if len(r)>12 else {};j=r[1]
        v=venues.setdefault(j,{'n':0,'course':[0]*6,'payout_sum':0,'payout_n':0,'payout_bins':[0]*5,'kim':Counter()})
        v['n']+=1
        winners=[x for x in ents if x[5]==1]
        if len(winners)==1 and winners[0][2] in range(1,7):v['course'][winners[0][2]-1]+=1
        if len(winners)>1:ties.append(r[:3]+[[str(x[1]) for x in winners]])
        v['kim'][r[3] or '未確認']+=1
        if r[8]:combinations[r[8]]+=1
        if r[9] is not None:
            pay=r[9];v['payout_sum']+=pay;v['payout_n']+=1
            v['payout_bins'][0 if pay<1000 else 1 if pay<5000 else 2 if pay<10000 else 3 if pay<100000 else 4]+=1
            high.append(r[:3]+[r[8],pay,r[10]])
            if len(high)>1000:high=sorted(high,key=lambda x:x[4],reverse=True)[:200]
        bad=[str(x[1]) for x in ents if x[4] in ('F','L')]
        if bad:accidents.append(r[:3]+[bad])
        title=meta.get('title');day=meta.get('day')
        if title and day:
            start=(datetime.strptime(r[0],'%Y%m%d')-timedelta(days=day-1)).strftime('%Y%m%d')
            key=j+':'+start+':'+title
            ev=events.setdefault(key,{'venue':j,'start':start,'through':r[0],'title':title,'grade':meta.get('grade'),'final':None,'races':0})
            ev['through']=r[0];ev['races']+=1
            label=re.sub(r'\s+','',meta.get('race_name',''))
            if '優勝' in label and '準' not in label:
                ev['final']={'date':r[0],'race':r[2],'entrants':[str(x[1]) for x in ents],'winners':[str(x[1]) for x in winners]}
    return {'venues':venues,'combinations':dict(combinations),'high_payout':sorted(high,key=lambda x:x[4],reverse=True)[:200],
            'accidents':accidents[-500:][::-1],'ties':ties[-200:][::-1],
            'events':sorted(events.values(),key=lambda x:x['through'],reverse=True)}


def compile_database(as_of=None,cache=None):
    as_of=as_of or datetime.now(JST).strftime('%Y%m%d')
    terms=periods();roster,by_player=roster_catalog(terms)
    from .championships import records as official_records
    championships=official_records();official_finals=defaultdict(list)
    for record in sorted(championships,key=lambda r:r['date']):
        if record['date']>=as_of:continue
        for division,entries in enumerate(record['divisions']):
            for entry in entries:
                t=entry['player']
                official_finals[t].append({k:record[k] for k in ('category','number','date','name','group','edition','venue','source')} | {'division':division,'place':entry['place']})
                if t not in roster:
                    roster[t]={'name':entry['name'],'branch':entry['fields'].get('支部',''),'class':'','historical':True,'period':'公式大会記録 '+rd.date(record['date'])}
    db=open_cache(cache or ROOT/'.cache'/'public-database.sqlite')
    ingest(db,[*sorted((ROOT/'history').glob('*.jsonl.gz')),*sorted((BASE/'races').glob('*.jsonl.gz'))])
    bounds=db.execute('SELECT min(day),max(day),count(*) FROM races WHERE day<?',(as_of,)).fetchone()
    for (t,) in db.execute('SELECT DISTINCT player FROM entries'):
        if t not in roster:
            sample=db.execute('SELECT races.payload FROM entries JOIN races ON entries.day=races.day AND entries.venue=races.venue AND entries.race=races.race WHERE entries.player=? ORDER BY entries.day DESC LIMIT 1',(t,)).fetchone()
            name=next((e[10] for e in json.loads(sample[0])[11] if str(e[1])==t and len(e)>10),t) if sample else t
            roster[t]={'name':name,'branch':'','class':'','historical':True,'period':'期別未収録'}
    meta={'as_of':as_of,'from':bounds[0] or '', 'through':bounds[1] or '', 'races':bounds[2],
          'roster':roster,'periods':[{k:x[k] for k in ('id','year','half','from','through','source')} for x in terms]}
    summary=event_summary(db,as_of)
    finals=defaultdict(list)
    for ev in summary['events']:
        if ev['final']:
            for t in ev['final']['entrants']:finals[t].append(ev)
    rankings=[]
    for i,t in enumerate(roster):
        rows=[json.loads(x[0]) for x in db.execute('SELECT row FROM entries WHERE player=? AND day<? ORDER BY day DESC,venue DESC,race DESC',(t,as_of))]
        data=rd.profile(rows,as_of)
        for window in data['windows'].values():window.pop('since',None)
        data.update(periods=by_player[t],history_url=f'data/players/{t}.json',history_count=len(rows))
        data['finals']=finals[t]
        data['official_finals']=sorted(official_finals[t],key=lambda r:r['date'],reverse=True)
        for c,m in data['windows']['90']['course'].items():
            if m['n']>=15:rankings.append({'player':t,'course':c,**m})
        data['rows']=rows[:30]
        # Stored DEFLATE blocks keep these frequently changing caches delta-
        # friendly in Git. Git's object pack supplies the actual compression.
        write_json(BASE/'profiles'/(t+'.json.gz'),data,compression=0)
        write_json(BASE/'player_history'/(t+'.json.gz'),rows,compression=0)
        if i%500==0:print(f'profiles {i}/{len(roster)}',flush=True)
    summary['rankings']=rankings
    write_json(BASE/'finals.json.gz',dict(finals))
    write_json(BASE/'summary.json.gz',summary)
    audits=[read_json(p,{}) for p in (BASE/'sources').glob('*.json.gz')]
    meta['daily_files']={'saved':sum(v.get('status')=='saved' for a in audits for v in a.values()),
                         'unavailable':sum(v.get('status')!='saved' for a in audits for v in a.values())}
    write_json(BASE/'catalog.json.gz',meta)
    db.close();print(f'database ready: {len(roster)} players / {bounds[2]} races',flush=True)
    return meta


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--as-of');a=ap.parse_args();compile_database(a.as_of)
