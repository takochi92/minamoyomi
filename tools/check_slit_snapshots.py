"""Report today's generation coverage without counting absent inputs as success."""
import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path


def audit(root, date):
    counts=Counter()
    data=Path(root)/'site/data'
    index_path=data/'index.json'
    index=json.loads(index_path.read_text(encoding='utf-8')) if index_path.exists() else {}
    expected={(v['jcd'],r['rno']) for v in index.get('venues',[]) for r in v.get('races',[])} if index.get('date')==date else None
    observed=set()
    for p in (Path(root)/'site/data/races'/date).glob('*.json'):
        r=json.loads(p.read_text(encoding='utf-8'));counts['races']+=1
        observed.add((r['jcd'],r['rno']))
        d=r.get('start_slit')
        if not d:counts['not_recorded']+=1;continue
        counts[d.get('status','unknown')]+=1
        try:
            at=datetime.fromisoformat(d['captured_at'])
            dl=datetime.strptime(date+r['deadline'],'%Y%m%d%H:%M').replace(tzinfo=at.tzinfo)
            assert at.tzinfo is not None and at<dl and at.strftime('%Y%m%d')==date
            if d['status']=='ready':
                assert len(d['boats'])==6
                assert {b['course'] for b in d['boats']}==set(range(1,7))
                assert {b['frame'] for b in d['boats']}==set(range(1,7))
                assert d['fingerprint'] and d['input_fingerprint']
        except (KeyError,ValueError,TypeError,AssertionError):counts['invalid']+=1
    if expected is not None:
        counts['scheduled_races']=len(expected)
        counts['missing_race_json']=len(expected-observed)
    else:
        counts['schedule_unknown']=1
    return dict(counts)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--date',required=True)
    args=parser.parse_args()
    result=audit(Path(__file__).resolve().parents[1],args.date)
    print(json.dumps(result,ensure_ascii=False))
    raise SystemExit(1 if result.get('invalid') else 0)
