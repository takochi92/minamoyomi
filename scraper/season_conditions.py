"""Read-only current-day overlay for provisional class-period conditions."""
from copy import deepcopy
from datetime import datetime, timedelta

from .season_watch import JST, POINTS, period, race_grade


def rank_points(grade, name):
    if grade not in ('一般', 'G3', 'G2', 'G1', 'SG') or not name:
        return None
    if '優勝戦' in name and not name.startswith(('優勝戦', '準優勝戦')):
        return None
    final = name.startswith('優勝戦')
    bonus = 2 if grade == 'SG' else 1 if grade in ('G1', 'G2') else 0
    return [POINTS[place] + bonus + ((1 if place <= 3 else 2) if final else 0)
            for place in range(1, 7)]


def current_conditions(report, index, load_race, now, calendars):
    """Never infer future starts from remaining calendar days or race order.

    Daily archived totals remain authoritative through report['through']; only
    later, explicitly finished and unambiguous current-day results are added.
    The input report and the prediction/race files are never mutated.
    """
    out = deepcopy(report)
    now = now.replace(tzinfo=JST) if now.tzinfo is None else now.astimezone(JST)
    today = now.strftime('%Y%m%d')
    yesterday = (now-timedelta(days=1)).strftime('%Y%m%d')
    issues = []
    if report.get('period') != period(today) or index.get('date') != today:
        issues.append('審査期または本日の番組が更新待ち')
    if report.get('as_of') != today or report.get('through', '') < yesterday:
        issues.append('前日までの日次集計が更新待ち')
    if report.get('missing_days'):
        issues.append('審査期間の保存結果に未確認日あり')
    context = {'today': today, 'updated_at': index.get('updated_at', ''),
               'baseline_through': report.get('through', ''), 'issues': issues,
               'last_day': report.get('period', {}).get('through') == today,
               'live_results_added': 0, 'scope': 'published_current_day_programmes_only'}
    out['conditions_context'] = context
    players = {p['toban']: p for p in out['players']}
    for p in players.values():
        p['condition'] = {'races': [], 'issues': [], 'venues': [], 'live_results_added': 0,
                          'programme_complete': False}
    if issues:
        return out
    seen = set()
    completeness = {}
    for venue in index.get('venues', []):
        if venue.get('cancelled'):
            continue
        jcd = venue['jcd']
        complete = bool(venue.get('races'))
        for stub in venue.get('races', []):
            rno = stub['rno']
            key = (today, jcd, rno)
            if key in seen:
                complete = False
                continue
            seen.add(key)
            race = load_race(today, jcd, rno) or {}
            boats = (race.get('racelist') or {}).get('boats') or []
            identities = [(b.get('frame'), str(b.get('toban', ''))) for b in boats]
            if (any(race.get(k) != v for k, v in zip(('date', 'jcd', 'rno'), key)) or len(boats) != 6
                    or {f for f,t in identities} != set(range(1,7))
                    or len({t for f,t in identities}) != 6 or any(not t.isdigit() for f,t in identities)):
                complete = False
                continue
            name = race.get('race_name') or (race.get('racelist') or {}).get('race_name', '')
            categories = {source['category'] for source in calendars if source['year'] == int(today[:4])}
            grade = race_grade([today, jcd, rno], calendars) if {'01','02','03'}.issubset(categories) else None
            points = rank_points(grade, name)
            result = race.get('result') or {}
            order = result.get('order') or []
            places = {r.get('frame'): str(r.get('place', '')) for r in order}
            normal_result = (len(order) == len(places) == 6 and set(places) == set(range(1,7))
                             and set(places.values()) == set('123456') and points is not None)
            try:
                clock = race.get('deadline') or stub.get('deadline')
                deadline = datetime.strptime(today+' '+clock, '%Y%m%d %H:%M').replace(tzinfo=JST)
            except (ValueError, TypeError):
                deadline = None
            for frame, toban in identities:
                p = players.get(toban)
                if p is None:
                    continue
                condition = p['condition']
                if jcd not in condition['venues']:
                    condition['venues'].append(jcd)
                if result.get('finished'):
                    if not normal_result:
                        condition['issues'].append('当日結果に事故・同着・未確認の計算条件あり')
                        continue
                    # Exact day boundary prevents counting archived results twice.
                    if today <= report['through']:
                        continue
                    place = int(places[frame])
                    p['n'] += 1
                    p['points'] += points[place-1]
                    p['top2'] += int(place <= 2)
                    p['top3'] += int(place <= 3)
                    p['win'] = p['points']/p['n']
                    p['last'] = today
                    condition['live_results_added'] += 1
                    context['live_results_added'] += 1
                elif deadline is None or deadline <= now:
                    condition['issues'].append('締切後の結果待ち、または締切時刻未確認')
                else:
                    condition['races'].append({'jcd': jcd, 'venue': venue.get('name', jcd), 'rno': rno,
                                               'deadline': clock, 'grade': grade, 'name': name,
                                               'points': points})
        completeness[jcd] = complete
    for p in players.values():
        c = p['condition']
        c['programme_complete'] = len(c['venues']) == 1 and all(completeness.get(j, False) for j in c['venues'])
        if c['venues'] and not c['programme_complete']:
            c['issues'].append('本日の出走表が未取得、または所属場の照合待ち')
        c['issues'] = sorted(set(c['issues']))
        c['races'].sort(key=lambda r: (r['deadline'], r['rno']))
    return out
