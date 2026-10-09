"""締切前の研究入力を固定し、結果と一緒に月別履歴に保存する。"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import gzip
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JST = timezone(timedelta(hours=9))
FIELDS = ('date', 'jcd', 'rno', 'deadline', 'racelist', 'before', 'oriten', 'odds_pre')


def mark_fetched(race, field, now):
    """成功した取得の完了時刻。未計測の古い値に時刻を補わない。"""
    if now.tzinfo is None:
        raise ValueError('timezone-aware timestamp required')
    race.setdefault('research_fetched_at', {})[field] = now.isoformat()


def valid_snapshot(snap, race=None):
    try:
        if not isinstance(snap, dict) or not isinstance(snap.get('inputs'), dict):
            return False
        if 'result' in snap['inputs']:
            return False
        if race and any(snap['inputs'].get(k) != race.get(k) for k in ('date','jcd','rno','deadline')):
            return False
        at = datetime.fromisoformat(snap['captured_at'])
        dl = datetime.fromisoformat(snap['deadline_at'])
        inputs=snap['inputs']
        expected_dl=datetime.strptime(inputs['date']+' '+inputs['deadline'], '%Y%m%d %H:%M').replace(tzinfo=JST)
        return (at.tzinfo is not None and dl.tzinfo is not None and at < dl and dl==expected_dl
                and at.astimezone(JST).strftime('%Y%m%d')==inputs['date'])
    except (TypeError, ValueError, KeyError):
        return False


def decision(race):
    """現行AIの本線＋押さえを各100円とする固定の仮想購入。実購入ではない。"""
    pred = race.get('prediction') or {}
    bets = pred.get('bets') or {}
    combos = sorted({b['combo'] for b in bets.get('main', []) + bets.get('sub', [])})
    return {'strategy': 'existing_ai_main_sub_100_v1', 'simulation': True,
            'model_version': pred.get('version'), 'stage': pred.get('stage'),
            'p3': deepcopy(pred.get('p3')), 'entry': deepcopy(pred.get('entry')),
            'tickets': [{'combo': c, 'amount': 100} for c in combos]}


def capture(race, now, deadline):
    """取得完了時点が締切前の場合だけ保存。結果情報を一切含めない。"""
    if now.tzinfo is None or deadline.tzinfo is None:
        raise ValueError('timezone-aware timestamps required')
    if now >= deadline or (race.get('result') or {}).get('finished'):
        return False
    if not (race.get('before') or {}).get('exhibition_done'):
        return False
    previous = race.get('research_snapshot') or {}
    if valid_snapshot(previous, race) and datetime.fromisoformat(previous['captured_at']) >= now:
        return False
    snap = {'schema': 2, 'captured_at': now.isoformat(),
                                 'deadline_at': deadline.isoformat(),
                                 'fetched_at': deepcopy(race.get('research_fetched_at', {})),
                                 'decision': decision(race),
                                 'inputs': {k: deepcopy(race[k]) for k in FIELDS if k in race}}
    if not valid_snapshot(snap,race):
        return False
    race['research_snapshot']=snap
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
        verified = valid_snapshot(snap or {}, r)
        inputs = snap['inputs'] if verified else {k: deepcopy(r[k]) for k in FIELDS if k in r}
        row = {**inputs, 'result': r['result'], 'provenance': 'timestamped_pre_deadline' if verified else 'legacy_unverified',
               'captured_at': snap['captured_at'] if verified else None,
               'deadline_at': snap['deadline_at'] if verified else None,
               'fetched_at': deepcopy(snap.get('fetched_at', {})) if verified else {},
               'decision': deepcopy(snap.get('decision')) if verified else None}
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
