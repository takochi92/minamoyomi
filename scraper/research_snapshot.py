"""締切前の研究入力を固定し、結果と一緒に月別履歴に保存する。"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import gzip
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JST = timezone(timedelta(hours=9))
FIELDS = ('date', 'jcd', 'rno', 'deadline', 'racelist', 'before', 'oriten', 'odds_pre')


def capture(race, now, deadline):
    """取得完了時点が締切前の場合だけ保存。結果情報を一切含めない。"""
    if now.tzinfo is None or deadline.tzinfo is None:
        raise ValueError('timezone-aware timestamps required')
    if now >= deadline or (race.get('result') or {}).get('finished'):
        return False
    if not (race.get('before') or {}).get('exhibition_done'):
        return False
    previous = race.get('research_snapshot') or {}
    if previous.get('captured_at') and datetime.fromisoformat(previous['captured_at']) >= now:
        return False
    race['research_snapshot'] = {'schema': 1, 'captured_at': now.isoformat(),
                                 'deadline_at': deadline.isoformat(),
                                 'inputs': {k: deepcopy(race[k]) for k in FIELDS if k in race}}
    return True


def archived_records(root=ROOT):
    output = {}
    for p in sorted((root/'history'/'exhibition_research').glob('*.jsonl.gz')):
        with gzip.open(p, 'rt', encoding='utf-8') as f:
            for line in f:
                r = json.loads(line)
                output[(r['date'], r['jcd'], r['rno'])] = r
    return output


def archive(root=ROOT):
    """終了レースを保存。旧データは取得時刻未確認として明示し、検証済み入力に昇格しない。"""
    records = archived_records(root)
    added = 0
    for p in sorted((root/'site'/'data'/'races').glob('*/*.json')):
        r = json.loads(p.read_text())
        if not (r.get('result') or {}).get('finished') or not r.get('before'):
            continue
        key = (r['date'], r['jcd'], r['rno'])
        snap = r.get('research_snapshot')
        verified = False
        if snap and snap.get('captured_at') and snap.get('deadline_at'):
            at, dl = map(datetime.fromisoformat, (snap['captured_at'], snap['deadline_at']))
            verified = at.tzinfo is not None and dl.tzinfo is not None and at < dl
        inputs = snap['inputs'] if verified else {k: deepcopy(r[k]) for k in FIELDS if k in r}
        row = {**inputs, 'result': r['result'], 'provenance': 'timestamped_pre_deadline' if verified else 'legacy_unverified',
               'captured_at': snap['captured_at'] if verified else None}
        existing = records.get(key)
        if existing and existing['provenance'] == 'timestamped_pre_deadline':
            # 入力は固定したまま、公式結果の訂正だけは反映できるようにする。
            if existing.get('result') != r['result']:
                existing['result'] = deepcopy(r['result']); added += 1
            continue
        if existing == row:
            continue
        records[key] = row; added += 1
    out = root/'history'/'exhibition_research'
    out.mkdir(parents=True, exist_ok=True)
    months = {}
    for key, r in sorted(records.items()):
        months.setdefault(r['date'][:6], []).append(r)
    for month, rows in months.items():
        content = ''.join(json.dumps(r, ensure_ascii=False, separators=(',', ':'))+'\n' for r in rows)
        (out/f'{month}.jsonl.gz').write_bytes(gzip.compress(content.encode(), mtime=0))
    return {'records': len(records), 'added_or_updated': added,
            'timestamped': sum(r['provenance']=='timestamped_pre_deadline' for r in records.values())}


if __name__ == '__main__':
    print(json.dumps(archive(), ensure_ascii=False))
