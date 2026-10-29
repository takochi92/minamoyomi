"""One-calendar-month public race browsing; preserve original saved predictions."""
from __future__ import annotations

import calendar
from datetime import datetime, timedelta
import gzip
import json
from pathlib import Path
import re


def bounds(today):
    day = datetime.strptime(today, '%Y%m%d').date()
    year, month = (day.year, day.month - 1) if day.month > 1 else (day.year - 1, 12)
    first = day.replace(year=year, month=month,
                        day=min(day.day, calendar.monthrange(year, month)[1]))
    return first.strftime('%Y%m%d'), today


def days(today):
    first, _ = bounds(today)
    day = datetime.strptime(first, '%Y%m%d').date()
    end = datetime.strptime(today, '%Y%m%d').date()
    while day <= end:
        yield day.strftime('%Y%m%d')
        day += timedelta(days=1)


def save_packet(data, date, races, index=None):
    """Only public race files go here, never client notes/account data."""
    if not re.fullmatch(r'\d{8}', date):
        raise ValueError('Invalid archive date')
    rows = sorted(races, key=lambda r: (r['jcd'], int(r['rno'])))
    if any(r.get('date') != date for r in rows):
        raise ValueError('Race date does not match archive')
    packet = {'schema': 1, 'date': date, 'races': rows}
    if index and index.get('date') == date:
        packet['index'] = index
    path = Path(data) / 'race-days' / (date + '.json.gz')
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(packet, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    if path.exists() and gzip.decompress(path.read_bytes()) == raw:
        return path
    temp = path.with_suffix('.gz.tmp')
    temp.write_bytes(gzip.compress(raw, mtime=0))
    temp.replace(path)
    return path


def save_index(data, index):
    date = index.get('date', '')
    if not re.fullmatch(r'\d{8}', date):
        return
    # Static meeting metadata, not the frequently changing results summary.
    value = {'date': date, 'venues': [
        {k: v[k] for k in ('jcd', 'name', 'title', 'day', 'grade', 'timezone', 'cancelled') if k in v}
        for v in index.get('venues', [])]}
    path = Path(data) / 'day-index' / (date + '.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    if not path.exists() or path.read_text(encoding='utf-8') != text:
        path.write_text(text, encoding='utf-8')


def retain_completed(data, today, raw_days=14):
    """Archive ended days before raw pruning. Unchanged archives need no re-read."""
    data = Path(data)
    first, _ = bounds(today)
    raw_limit = (datetime.strptime(today, '%Y%m%d') - timedelta(days=raw_days)).strftime('%Y%m%d')
    for folder in sorted((data / 'races').glob('*')):
        date = folder.name
        if (not folder.is_dir() or folder.is_symlink() or not re.fullmatch(r'\d{8}', date)
                or not first <= date < today):
            continue
        path = data / 'race-days' / (date + '.json.gz')
        if path.exists() and date >= raw_limit:
            continue
        rows = [json.loads(p.read_text(encoding='utf-8')) for p in sorted(folder.glob('*.json'))]
        ip = data / 'day-index' / (date + '.json')
        index = json.loads(ip.read_text(encoding='utf-8')) if ip.exists() else None
        if rows:
            save_packet(data, date, rows, index)
    for name, pattern in (('race-days', '*.json.gz'), ('day-index', '*.json')):
        base = data / name
        for path in base.glob(pattern):
            date = path.name[:8]
            if (re.fullmatch(r'\d{8}', date) and date < first and not path.is_symlink()
                    and path.resolve().parent == base.resolve()):
                path.unlink()


def load_details(data, today):
    first, last = bounds(today)
    data = Path(data)
    out = {}
    for path in sorted((data / 'race-days').glob('*.json.gz')):
        date = path.name[:8]
        if not re.fullmatch(r'\d{8}', date) or not first <= date <= last:
            continue
        packet = json.loads(gzip.decompress(path.read_bytes()))
        if packet.get('date') != date:
            raise ValueError('Archived date mismatch')
        out[date] = {(r['jcd'], int(r['rno'])): r for r in packet.get('races', []) if r.get('date') == date}
    # More recent official corrections in raw files take priority.
    for folder in sorted((data / 'races').glob('*')):
        if not folder.is_dir() or not re.fullmatch(r'\d{8}', folder.name) or not first <= folder.name <= last:
            continue
        rows = out.setdefault(folder.name, {})
        for path in sorted(folder.glob('*.json')):
            r = json.loads(path.read_text(encoding='utf-8'))
            if r.get('date') == folder.name and r.get('jcd') and r.get('rno'):
                rows[(r['jcd'], int(r['rno']))] = r
    return {date: list(rows.values()) for date, rows in out.items()}


def prune_generated(output, today):
    """Remove only expired generated date paths, with resolved-parent checks."""
    import shutil
    first, _ = bounds(today)
    output = Path(output).resolve()
    for name in ('race', 'races'):
        base = output / name
        if base.is_symlink() or not base.exists():
            continue
        for path in base.iterdir():
            date = path.stem if path.is_file() else path.name
            if (not re.fullmatch(r'\d{8}', date) or date >= first or path.is_symlink()
                    or path.resolve().parent != base.resolve()):
                continue
            if name == 'race' and path.is_dir():
                shutil.rmtree(path)
            elif name == 'races' and path.is_file() and path.suffix == '.html':
                path.unlink()
