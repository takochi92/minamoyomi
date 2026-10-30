"""Official future meetings and announced entrants, collected outside live updates."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from html import escape
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup

from .fetch import UA

JST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / 'site/data/next_meetings.json'
BASE = 'https://www.boatrace.jp/owpc/pc/race/'


def parse_calendar(html, today, ym=None):
    soup = BeautifulSoup(html, 'html.parser')
    if ym:
        selected = []
        for field in ('TTRMP010A_4', 'TTRMP010A_5'):
            option = soup.select_one(f'select[name="{field}"] option[selected]')
            selected.append(option.get('value', '') if option else '')
        if selected != [ym[:4], str(int(ym[4:]))]:
            raise ValueError('Calendar month mismatch')
    venues, events = set(), {}
    for tr in soup.select('tr'):
        venue = tr.select_one('th a[href*="stadium?jcd="]')
        if not venue:
            continue
        jcd = parse_qs(urlparse(venue['href']).query).get('jcd', [''])[0]
        if jcd not in {f'{n:02}' for n in range(1, 25)}:
            raise ValueError('Unknown calendar venue')
        venues.add(jcd)
        for a in tr.select('td a[href]'):
            url = urlparse(a['href'])
            if url.path not in ('/owpc/pc/race/assen', '/owpc/pc/race/raceindex'):
                continue
            q = parse_qs(url.query)
            date = q.get('hd', [''])[0]
            if q.get('jcd') != [jcd] or not re.fullmatch(r'\d{8}', date):
                raise ValueError('Invalid calendar meeting')
            datetime.strptime(date, '%Y%m%d')
            if date <= today:
                continue
            title = a.get_text(' ', strip=True)
            if not title:
                raise ValueError('Missing meeting title')
            event = {'jcd': jcd, 'from': date, 'title': title,
                     'source': f'{BASE}assen?jcd={jcd}&hd={date}'}
            if jcd not in events or date < events[jcd]['from']:
                events[jcd] = event
    if len(venues) != 24:
        raise ValueError(f'Incomplete national calendar: {len(venues)}/24 venues')
    return events


def parse_entrants(html, event):
    soup = BeautifulSoup(html, 'html.parser')
    title = soup.select_one('.heading2_titleName')
    label = soup.find(string=re.compile(r'\d{4}/\d{2}/\d{2}\s*-\s*\d{4}/\d{2}/\d{2}'))
    if not title or not label or not soup.select_one(f'.heading2 img[src*="text_place2_{event["jcd"]}"]'):
        raise ValueError('Entrant meeting identity missing')
    match = re.search(r'(\d{4}/\d{2}/\d{2})\s*-\s*(\d{4}/\d{2}/\d{2})', str(label))
    first, last = [datetime.strptime(d, '%Y/%m/%d').strftime('%Y%m%d') for d in match.groups()]
    if first != event['from'] or last < first:
        raise ValueError('Entrants belong to another meeting')
    rows = []
    for number in soup.select('.photoGallery3_bodyNumber'):
        body = number.parent
        name, tier = body.select_one('.photoGallery3_bodyName'), body.select_one('.photoGallery3_bodyClass span')
        t = number.get_text(strip=True)
        link = body.parent.select_one('a[href*="toban="]')
        if not re.fullmatch(r'\d{4}', t) or not name or not tier or not link:
            raise ValueError('Incomplete entrant')
        if parse_qs(urlparse(link['href']).query).get('toban') != [t]:
            raise ValueError('Entrant registration mismatch')
        cls = tier.get_text(strip=True)
        if cls not in ('A1', 'A2', 'B1', 'B2'):
            raise ValueError('Unknown entrant class')
        rows.append({'toban': t, 'name': re.sub(r'\s+', ' ', name.get_text(' ', strip=True)), 'class': cls})
    if not 6 <= len(rows) <= 100 or len({r['toban'] for r in rows}) != len(rows):
        raise ValueError('Entrant list incomplete or duplicated')
    return {**event, 'title': title.get_text(' ', strip=True), 'through': last,
            'entrants': sorted(rows, key=lambda r: int(r['toban']))}


def get(url):
    response = requests.get(url, headers={'User-Agent': UA}, timeout=(10, 35))
    response.raise_for_status()
    response.encoding = 'utf-8'
    return response.text


def refresh(today=None, fetch=get, path=PATH):
    now = datetime.now(JST)
    today = today or now.strftime('%Y%m%d')
    month = datetime.strptime(today[:6], '%Y%m')
    months = []
    for _ in range(3):
        months.append(month.strftime('%Y%m'))
        month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    old = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    fan = json.loads((ROOT / 'scraper/racers.json').read_text(encoding='utf-8'))
    candidates, calendars, errors, available_months = {}, [], [], set()
    for ym in months:
        url = BASE + 'monthlyschedule?ym=' + ym
        try:
            events = parse_calendar(fetch(url), today, ym)
            calendars.append(url)
            available_months.add(ym)
            for jcd, event in events.items():
                if jcd not in candidates or event['from'] < candidates[jcd]['from']:
                    candidates[jcd] = event
        except Exception as exc:
            errors.append(f'calendar {ym}: {type(exc).__name__}')
    if not calendars:
        raise RuntimeError('No official calendar available; previous data retained')
    candidates = {j: ev for j, ev in candidates.items()
                  if all(m in available_months for m in months if m <= ev['from'][:6])}

    def one(pair):
        jcd, event = pair
        try:
            meeting = parse_entrants(fetch(event['source']), event)
            for row in meeting['entrants']:
                row['win'] = (fan.get('racers', {}).get(row['toban']) or {}).get('win')
            meeting['win_source'] = fan.get('source', '')
            meeting['checked_at'] = now.isoformat(timespec='minutes')
            return jcd, meeting, None
        except Exception as exc:
            previous = old.get('venues', {}).get(jcd, {})
            if previous.get('from') == event['from']:
                meeting = {**previous, 'refresh_pending': True}
            else:
                meeting = {**event, 'entrants': [], 'refresh_pending': True}
            return jcd, meeting, f'entrants {jcd}: {type(exc).__name__}'
    venues = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for jcd, meeting, error in pool.map(one, sorted(candidates.items())):
            venues[jcd] = meeting
            if error:
                errors.append(error)
    # An unavailable month must not erase a still-future, previously confirmed meeting.
    if errors:
        for jcd, previous in old.get('venues', {}).items():
            if previous.get('from', '') > today and (jcd not in venues or previous['from'] < venues[jcd]['from']):
                venues[jcd] = {**previous, 'refresh_pending': True}
    report = {'schema': 1, 'as_of': today, 'checked_at': now.isoformat(timespec='minutes'),
              'win_source': fan.get('source', ''), 'calendar_sources': calendars,
              'venues': venues, 'errors': errors}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(report, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')
    temporary.replace(path)
    print(f'next meetings: {len(venues)}/24 venues; {sum(len(v["entrants"]) for v in venues.values())} entrants; {len(errors)} pending', flush=True)
    return report


def upcoming(report, jcd, today):
    event = (report or {}).get('venues', {}).get(jcd)
    return event if event and event.get('from', '') > today else None


def short_date(date):
    return f'{int(date[4:6])}/{int(date[6:])}'


def render(page, event, source):
    if not event:
        return '<section class="panel next-meeting" id="next-meeting"><h2>次回開催</h2><p class="sub">日程確認中</p></section>'
    e = escape
    end = f'〜{short_date(event["through"])}' if event.get('through') else '〜'
    rows = []
    for r in sorted(event.get('entrants', []), key=lambda r: int(r['toban'])):
        win = f'{r["win"]:.2f}' if isinstance(r.get('win'), (int, float)) else '—'
        href = page.u('racer/' + r['toban'] + '.html') if r.get('win') is not None else 'https://www.boatrace.jp/owpc/pc/data/racersearch/profile?toban=' + r['toban']
        rows.append(f'<tr><td class="num">{e(r["toban"])}</td><td><a href="{e(href, quote=True)}">{e(r["name"])}</a></td><td><span class="next-class">{e(r["class"])}</span></td><td class="r num">{win}</td></tr>')
    m = re.fullmatch(r'fan(\d{2})(04|10)\.lzh', event.get('win_source', source))
    term = (f'{2000+int(m[1])+(m[2]=="10")}年{"前期" if m[2]=="10" else "後期"}' if m else '公式期別成績')
    table = (f'<h3>出場予定選手 <small>{len(rows)}人・登録番号順</small></h3>'
             f'<p class="sub next-period">勝率：{term}の期別成績</p>'
             f'<table class="next-entrants"><thead><tr><th>登番</th><th>選手</th><th>級別</th><th class="r">勝率</th></tr></thead><tbody>{"".join(rows)}</tbody></table>' if rows else
             '<p class="sub">出場予定選手は発表・取得待ちです。</p>')
    return (f'<section class="panel next-meeting" id="next-meeting"><h2>次回 {short_date(event["from"])}{end}</h2>'
            f'<p class="next-title">{e(event["title"])}</p>{table}'
            '<p class="sub next-footnote">出場予定は変更される場合があります。'
            f'<a href="{e(event["source"], quote=True)}" target="_blank" rel="noopener">公式の出場予定</a></p></section>')


if __name__ == '__main__':
    refresh()
