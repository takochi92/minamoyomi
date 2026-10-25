"""Independent, provisional class-period and F-history display data.

Never used as a prediction feature. Official decisions and unserved F leave
cannot be inferred from race results alone.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from bs4 import BeautifulSoup
from .database_sources import BASE, JST, fetch, read_json, session, write_json

ROOT = Path(__file__).resolve().parent.parent
STORE = BASE / 'season_watch'
POINTS = {1: 10, 2: 8, 3: 6, 4: 4, 5: 2, 6: 1}
EXCLUDED = {'S0', 'L0', 'K0'}
# Verified announcements only. A special class-retention exception in the fan
# roster must not turn its minimum score into an alleged official cut line.
OFFICIAL_BORDERS = {
    '2026-1': {'A1': 6.24, 'A2': 5.48, 'source': 'https://www.boatrace.jp/owpc/pc/site/news/2025/11/46265/'},
    '2026-2': {'A1': 6.27, 'A2': 5.46, 'source': 'https://www.boatrace.jp/owpc/pc/site/news/2026/05/49344/'},
}


def period(date):
    d = datetime.strptime(date, '%Y%m%d')
    if d.month >= 11:
        return {'from': f'{d.year}1101', 'through': f'{d.year+1}0430', 'label': f'{d.year+1}年後期', 'apply': f'{d.year+1}0701'}
    if d.month <= 4:
        return {'from': f'{d.year-1}1101', 'through': f'{d.year}0430', 'label': f'{d.year}年後期', 'apply': f'{d.year}0701'}
    return {'from': f'{d.year}0501', 'through': f'{d.year}1031', 'label': f'{d.year+1}年前期', 'apply': f'{d.year+1}0101'}


def parse_calendar(html, year, category):
    soup = BeautifulSoup(html, 'html.parser')
    if not any(re.fullmatch(rf'\s*{year}\s*年\s*', h.get_text()) for h in soup.select('h2,h3,h4')):
        raise ValueError('Calendar year not recognized')
    events = []
    for tr in soup.select('tbody tr'):
        cell = tr.select_one('.td_date')
        venue = tr.select_one('img[src*="text_place1_"]')
        if not cell or not venue:
            continue
        dates = re.fullmatch(r'\s*(\d\d)/(\d\d)\s*[-〜～]\s*(\d\d)/(\d\d)\s*', cell.get_text())
        j = re.search(r'text_place1_(\d{2})', venue['src'])
        classes = ' '.join(c for td in tr.select('td') for c in td.get('class', []))
        grade = re.search(r'is-(SG|G1|G2|G3)[a-z]*\b', classes)
        if not dates or not j or not grade:
            raise ValueError('Official calendar row incomplete')
        am, ad, bm, bd = map(int, dates.groups())
        first = datetime(year, am, ad)
        last = datetime(year + int((bm, bd) < (am, ad)), bm, bd)
        title = tr.select_one('.is-alignL')
        events.append({'from': first.strftime('%Y%m%d'), 'through': last.strftime('%Y%m%d'),
                       'jcd': j[1], 'grade': grade[1], 'title': title.get_text(' ', strip=True) if title else ''})
    if len(events) < (8 if category == '01' else 15):
        raise ValueError('Official annual calendar incomplete')
    return events


def refresh_calendars(years):
    def one(pair):
        year, cat = pair
        url = f'https://www.boatrace.jp/owpc/pc/race/gradesch?hcd={cat}&year={year}'
        raw = fetch(session(), url)
        events = parse_calendar(raw.decode('utf-8'), year, cat)
        write_json(STORE / 'calendars' / f'{year}-{cat}.json',
                   {'year': year, 'category': cat, 'source': url, 'sha256': hashlib.sha256(raw).hexdigest(),
                    'checked_at': datetime.now(JST).isoformat(), 'events': events})
        return year, cat, len(events)
    with ThreadPoolExecutor(max_workers=2) as pool:
        for result in pool.map(one, [(y, c) for y in sorted(years) for c in ('01', '02', '03')]):
            print('calendar', *result, flush=True)


def calendars():
    return [read_json(p) for p in sorted((STORE / 'calendars').glob('*.json'))]


def load_records(start, through):
    rows = {}
    for folder in (ROOT / 'history', BASE / 'races'):
        for p in sorted(folder.glob('*.jsonl.gz')):
            if not start[:6] <= p.name[:6] <= through[:6]:
                continue
            with gzip.open(p, 'rt', encoding='utf-8') as f:
                for r in map(json.loads, f):
                    if start <= r[0] <= through:
                        key = tuple(r[:3])
                        if key not in rows or len(r) >= len(rows[key]):
                            rows[key] = r
    return sorted(rows.values(), key=lambda r: (r[0], r[1], r[2]))


def race_grade(r, sources):
    year = int(r[0][:4])
    if not {'01', '02'}.issubset({x['category'] for x in sources if x['year'] == year}):
        return None
    matches = [ev for x in sources if x['year'] == year for ev in x['events']
               if ev['jcd'] == r[1] and ev['from'] <= r[0] <= ev['through']]
    grades = {x['grade'] for x in matches}
    # A simultaneous SG / women's G2 programme cannot be resolved from date alone.
    return next(iter(grades)) if len(grades) == 1 else ('一般' if not grades else None)


def final_race(r):
    return len(r) > 12 and bool(re.match(r'^優勝戦', r[12].get('race_name', '')))


def aggregate(races, sources, start, through, final_bonus=True):
    players = {}
    for r in races:
        if not start <= r[0] <= through:
            continue
        grade = race_grade(r, sources)
        final = final_race(r)
        name = r[12].get('race_name', '') if len(r) > 12 else ''
        special = '優勝戦' in name and not re.match(r'^(準)?優勝戦', name)
        for e in r[11]:
            t = str(e[1])
            p = players.setdefault(t, {'n': 0, 'points': 0, 'top2': 0, 'top3': 0, 'f': [],
                                       'accident_min': 0, 'unknown': 0, 'last': r[0]})
            p['last'] = r[0]
            code = e[5]
            if code in EXCLUDED:
                continue
            p['n'] += 1
            p['top2'] += int(code in (1, 2))
            p['top3'] += int(code in (1, 2, 3))
            if grade is None or len(r) <= 12 or special:
                p['unknown'] += 1
            if isinstance(code, int) and code in POINTS:
                bonus = 2 if grade == 'SG' else 1 if grade in ('G1', 'G2') else 0
                extra = (1 if code <= 3 else 2) if final and final_bonus else 0
                p['points'] += POINTS[code] + bonus + extra
            if e[4] == 'F' or code == 'F':
                repeated = bool(p['f'])
                p['accident_min'] += (50 if final else 30) if repeated and r[0] >= '20250501' else (30 if final else 20)
                p['f'].append({'date': r[0], 'jcd': r[1], 'rno': r[2], 'final': final})
            elif code in ('L', 'L1'):
                p['accident_min'] += 30 if final else 20
            elif code == 'S2':
                p['accident_min'] += 15
            elif code in ('S1', 'K1'):
                p['accident_min'] += 10
            elif not isinstance(code, int):
                p['unknown'] += 1
    for p in players.values():
        p['win'] = p['points'] / p['n'] if p['n'] else None
    return players


def provisional_borders(players, roster_n):
    """An explicitly provisional 20% quota model, not the official decision."""
    quota = int(roster_n * .20)
    scenarios = []
    # Dropping unresolved high scorers biases a national cut line downward.
    # Retain them and compare no extra points vs up to 4 extra points per unknown
    # race (grade + final bonus). This is a scenario range, not a confidence band.
    for extra in (0, 4):
        selected = set()
        trial = {}
        for tier, minimum in [('A1', 90), ('A2', 80)]:
            eligible = [(t, p['win'] + extra * p['unknown'] / p['n']) for t, p in players.items()
                        if t not in selected and p['n'] >= minimum
                        and p['top2'] / p['n'] >= .30 and p['top3'] / p['n'] >= .40
                        and p['accident_min'] / p['n'] <= .70]
            eligible.sort(key=lambda x: (-x[1], x[0]))
            winners = eligible[:quota]
            selected.update(t for t, score in winners)
            trial[tier] = {'quota': quota, 'eligible': len(eligible),
                           'win': winners[-1][1] if quota and len(winners) == quota else None}
        scenarios.append(trial)
    out = {}
    for tier in ('A1', 'A2'):
        values = [x[tier]['win'] for x in scenarios if x[tier]['win'] is not None]
        low, high = (min(values), max(values)) if len(values) == 2 else (None, None)
        out[tier] = {**scenarios[0][tier], 'low': low, 'high': high, 'win': high}
    return out


def programme_snapshots(today):
    out = {}
    for folder in sorted((ROOT / 'site/data/races').glob('*')):
        if not folder.is_dir() or folder.name > today:
            continue
        for path in sorted(folder.glob('*.json')):
            race = read_json(path, {}) or {}
            for b in (race.get('racelist') or {}).get('boats', []):
                if b.get('f') is None or b.get('f_known') is not True:
                    continue
                t = str(b.get('toban', ''))
                row = {'date': race['date'], 'jcd': race['jcd'], 'rno': race['rno'], 'f': b['f']}
                if t not in out or (row['date'], row['rno']) > (out[t]['date'], out[t]['rno']):
                    out[t] = row
    return out


def build_report(today, races, sources, terms, snapshots):
    current = period(today)
    previous = period((datetime.strptime(current['from'], '%Y%m%d') - timedelta(days=1)).strftime('%Y%m%d'))
    through = min(current['through'], (datetime.strptime(today, '%Y%m%d') - timedelta(days=1)).strftime('%Y%m%d'))
    latest = max((t for t in terms if t['through'] < current['from']), key=lambda t: t['through'], default=None)
    # A newly published next-period fan file is NOT yet the currently applied class.
    applied_half = 1 if today[4:6] <= '06' else 2
    applied = next((t for t in terms if t['year'] == int(today[:4]) and t['half'] == applied_half), None)
    roster = dict(applied['players']) if applied else {}
    stats = aggregate(races, sources, current['from'], through)
    for r in races:
        if r[0] > through:
            continue
        for e in r[11]:
            if str(e[1]) not in roster and len(e) > 10:
                roster[str(e[1])] = {'name': e[10], 'class': '', 'branch': ''}
    current_ids = set(stats) | (set(latest['players']) if latest else set())
    borders = provisional_borders(stats, len(current_ids))
    unresolved_grades = sum(race_grade(r, sources) is None for r in races if current['from'] <= r[0] <= through)
    if unresolved_grades:
        # Do not estimate a national cut line after discarding unresolved mixed
        # programmes (e.g. SG + women's G2), which would bias the whole ranking.
        for b in borders.values():
            b['win'] = None
            b['low'] = b['high'] = None
    for tier, b in borders.items():
        official = OFFICIAL_BORDERS.get((latest or {}).get('id'), {})
        b['previous_official'] = official.get(tier)
        b['previous_source'] = official.get('source')
    rows = []
    for t, p in stats.items():
        if not p['n']:
            continue
        info = roster.get(t, {})
        rows.append({'toban': t, 'name': info.get('name', t), 'kana': info.get('kana', ''),
                     'class': info.get('class', ''), 'branch': info.get('branch', ''), **p})
    rows.sort(key=lambda p: (-(p['win'] or 0), p['toban']))
    # In April/October prepare the NEXT rollover. Otherwise compare the prior
    # period with a genuinely new-period programme, never an old F0 snapshot.
    preparing = today[4:6] in ('04', '10')
    f_period = current if preparing else previous
    f_stats = stats if preparing else aggregate(races, sources, previous['from'], previous['through'])
    new_start = (datetime.strptime(current['through'], '%Y%m%d') + timedelta(days=1)).strftime('%Y%m%d') if preparing else current['from']
    f_rows = []
    for t, p in f_stats.items():
        if not p['f']:
            continue
        info = roster.get(t, {})
        observed = snapshots.get(t)
        if not observed or observed['date'] < new_start:
            observed = None
        # A known F after rollover invalidates an earlier F0 programme.
        current_f = (stats.get(t) or {}).get('f') if not preparing else []
        f0 = bool(observed is not None and observed['f'] == 0 and not current_f)
        f_rows.append({'toban': t, 'name': info.get('name', t), 'class': info.get('class', ''),
                       'branch': info.get('branch', ''), 'events': p['f'], 'last_f': p['f'][-1]['date'],
                       'programme': observed, 'f0': f0, 'leave_status': 'unverified'})
        f_rows[-1]['current_f_known'] = bool(current_f)
    f_rows.sort(key=lambda p: (p['last_f'], p['toban']), reverse=True)
    source_status = {}
    for path in (BASE / 'sources').glob('*.json.gz'):
        if previous['from'][:6] <= path.name[:6] <= through[:6]:
            source_status.update(read_json(path, {}))
    missing = []
    day = datetime.strptime(current['from'], '%Y%m%d')
    while day.strftime('%Y%m%d') <= through:
        key = day.strftime('%Y%m%d')
        if source_status.get(key, {}).get('status') != 'saved':
            missing.append(key)
        day += timedelta(days=1)
    return {'schema': 1, 'as_of': today, 'through': max((r[0] for r in races if current['from'] <= r[0] <= through), default=''),
            'period': current, 'previous_period': previous,
            'current_class_period': applied['id'] if applied else None,
            'grade_unresolved_races': unresolved_grades,
            'roster_n': len(current_ids), 'borders': borders, 'players': rows,
            'official_period': {k: latest[k] for k in ('id', 'from', 'through', 'source')} if latest else None,
            'f_period': f_period, 'f_preparing': preparing, 'new_start': new_start, 'f_players': f_rows,
            'missing_days': missing, 'calendar_sources': [{k: x[k] for k in ('year', 'category', 'source', 'checked_at')} for x in sources]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--refresh-calendars', action='store_true')
    args = ap.parse_args()
    today = datetime.now(JST).strftime('%Y%m%d')
    if args.refresh_calendars:
        refresh_calendars({int(today[:4]) - 1, int(today[:4])})
    from .database_build import periods
    current = period(today)
    start = period((datetime.strptime(current['from'], '%Y%m%d') - timedelta(days=1)).strftime('%Y%m%d'))['from']
    through = (datetime.strptime(today, '%Y%m%d') - timedelta(days=1)).strftime('%Y%m%d')
    report = build_report(today, load_records(start, through), calendars(), periods(), programme_snapshots(today))
    write_json(STORE / 'summary.json.gz', report)
    print('season watch:', len(report['players']), 'players;', len(report['f_players']), 'F histories', flush=True)


if __name__ == '__main__':
    main()
