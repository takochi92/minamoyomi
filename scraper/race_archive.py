"""Monthly public results, merged independently of frozen prediction records."""
from __future__ import annotations
import gzip,json,re
from pathlib import Path
from .database_sources import BASE

HISTORY=Path(__file__).resolve().parent.parent/'history'


def months(as_of,history=HISTORY,archive=None):
    archive=archive or BASE/'races'
    return sorted({p.name[:6] for folder in (history,archive) for p in folder.glob('*.jsonl.gz') if re.fullmatch(r'\d{6}',p.name[:6]) and p.name[:6]<=as_of[:6]},reverse=True)


def month_records(month,as_of,history=HISTORY,archive=None):
    if not re.fullmatch(r'\d{6}',month):raise ValueError('Invalid result month')
    archive=archive or BASE/'races';records={}
    for folder in (history,archive):
        path=folder/(month+'.jsonl.gz')
        if not path.exists():continue
        with gzip.open(path,'rt',encoding='utf-8') as f:
            rows=[r for r in map(json.loads,f) if r[0]<as_of]
            if folder==archive:
                days={r[0] for r in rows}
                records={k:v for k,v in records.items() if k[0] not in days}
            for row in rows:
                if row[0]>=as_of:continue
                key=tuple(row[:3]);old=records.get(key)
                if old is None or len(row)>=len(old):records[key]=row
    return [records[k] for k in sorted(records,reverse=True)]


def write_assets(output,as_of):
    output=Path(output)/'data'/'database'/'races';output.mkdir(parents=True,exist_ok=True)
    for month in months(as_of):
        with (output/(month+'.json')).open('w',encoding='utf-8') as f:
            json.dump(month_records(month,as_of),f,ensure_ascii=False,separators=(',',':'))
