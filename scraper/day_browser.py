"""Bounded, dated meeting pages using saved details and official results only."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
import gzip
from html import escape
import json
from pathlib import Path

from .race_days import bounds, days


def iso(date):
    return f'{date[:4]}-{date[4:6]}-{date[6:]}'


def date_picker(page, today, selected, jcd=''):
    from .sitegen import SLUG
    first, last = bounds(today)
    home = page.u('index.html')
    current = page.u(f'venue/{SLUG[jcd]}.html') if jcd else home + '#held-races'
    return (f'<form class="day-picker" data-today="{today}" data-home="{home}" data-venue="{jcd}" data-current="{current}">'
            f'<label for="race-day">開催日</label><input id="race-day" name="date" type="date" min="{iso(first)}" max="{iso(last)}" value="{iso(selected)}" required>'
            '<button type="submit">表示</button>'
            f'<a href="{current}">本日</a>'
            '<span class="day-picker-status" role="alert"></span></form>')


def saved_results(data, today):
    """Join archived names/boat numbers with historical B statistics."""
    data = Path(data)
    root = data.parent.parent if data.parent.name == 'site' else data.parent
    first, _ = bounds(today)
    records = {}
    for folder in (root / 'history', root / 'scraper/database/races'):
        for path in sorted(folder.glob('*.jsonl.gz')):
            if not first[:6] <= path.name[:6] <= today[:6]:
                continue
            with gzip.open(path, 'rt', encoding='utf-8') as f:
                for row in map(json.loads, f):
                    if not first <= row[0] < today:
                        continue
                    key = (row[0], str(row[1]), int(row[2]))
                    old = records.get(key)
                    if old and len(row) > 12:
                        book = {e[0]: e[7] for e in old[11]}
                        for entry in row[11]:
                            if not entry[7]:
                                entry[7] = book.get(entry[0])
                    records[key] = row
    return records


def result_race(site, row):
    date, jcd, no = row[:3]
    meta = row[12] if len(row) > 12 else {}
    boats, order, start = [], [], []
    for en in sorted(row[11], key=lambda e: e[0]):
        book = en[7] or []
        boats.append({'frame': en[0], 'toban': str(en[1]),
                      'name': en[10] if len(en) > 10 else site.racer_name(str(en[1]), '登録' + str(en[1])),
                      'class': book[0] if book else '', 'motor_no': en[8] if len(en) > 8 else None,
                      'course': en[2], 'st': en[3] / 100 if en[3] is not None else None,
                      'st_flag': en[4], 'place': en[5], 'exhibit_time': en[6] / 100 if en[6] else None})
        order.append({'frame': en[0], 'place': str(en[5])})
        if en[2] in range(1, 7):
            start.append({'frame': en[0], 'course': en[2], 'st': en[3] / 100 if en[3] is not None else None, 'flag': en[4]})
    return {'date': date, 'jcd': jcd, 'rno': no, 'deadline': '', '_archive_results_only': True,
            'race_name': meta.get('race_name', ''), 'racelist': {'title': meta.get('title', ''), 'boats': boats},
            'result': {'finished': bool(row[8]), 'trifecta': row[8], 'trifecta_payout': row[9],
                       'trifecta_ninki': row[10], 'kimarite': row[3], 'order': order, 'start': start},
            '_result_weather': {'wind_dir': row[4], 'wind_speed': row[5], 'wave': row[6]}}


def result_page(site, race):
    from .sitegen import Page, SLUG, VENUES, SITE_NAME, bt, combo, yen, e
    d, jcd, no = race['date'], race['jcd'], race['rno']
    page = Page(f'race/{d}/{SLUG[jcd]}-{no}.html')
    back = page.u(f'races/{d}.html') + '#v' + jcd
    rows = []
    for b in race['racelist']['boats']:
        st = '—' if b['st'] is None else f'{b["st_flag"]}{abs(b["st"]):.2f}'
        exhibit = '—' if b['exhibit_time'] is None else f'{b["exhibit_time"]:.2f}'
        values = [('着順', str(b['place'])), ('進入', b['course'] or '—'), ('ST', st), ('展示', exhibit), ('号機', b['motor_no'] if b['motor_no'] is not None else '—')]
        rows.append(f'<li class="archive-boat"><header>{bt(b["frame"])}<a href="{page.u("racer/" + b["toban"] + ".html")}">{e(b["name"])}</a><small>{e(b["class"])}</small></header>'
                    '<div>' + ''.join(f'<span><small>{label}</small><b class="num">{e(str(value))}</b></span>' for label, value in values) + '</div></li>')
    res, w = race['result'], race['_result_weather']
    title = f'{iso(d)} {VENUES[jcd]["name"]}{no}R'
    result = combo(res['trifecta']) + ' ' + yen(res['trifecta_payout']) if res['trifecta'] else '組番・払戻未保存'
    body = (f'<p><a href="{back}">← {iso(d)}の開催に戻る</a></p><h1>{e(title)}</h1>'
            '<p class="archive-note">保存のある出走・結果・展示タイムを表示しています。当時の予想・オッズ・詳細展示は未保存です。</p>'
            f'<section id="kekka" class="panel"><h2>結果</h2><div class="archive-combo">{result}</div><ul class="archive-boats">{"".join(rows)}</ul>'
            f'<p class="sub">決まり手 {e(res.get("kimarite") or "未保存")}・風 {e(str(w["wind_dir"]))} {w["wind_speed"]}m・波 {w["wave"]}cm</p>'
            f'<a href="https://www.boatrace.jp/owpc/pc/race/raceresult?hd={d}&amp;jcd={jcd}&amp;rno={no}" target="_blank" rel="noopener">公式結果を確認 →</a></section>')
    site.put(page.path, page.render(title + ' 出走・結果｜' + SITE_NAME, '保存済みの公式競走成績。', body,
                                   [(f'races/{d}.html', iso(d) + 'の開催'), ('', str(no) + 'R')]))


def build(site):
    from .sitegen import DATA, Page, SLUG, VENUES, SITE_NAME, e
    today = site.idx.get('date') or site.now.strftime('%Y%m%d')
    first, _ = bounds(today)
    for (date, jcd, no), row in saved_results(DATA, today).items():
        if jcd not in VENUES:
            continue
        existing = site.day_races.setdefault(date, [])
        if not any(r['jcd'] == jcd and r['rno'] == no for r in existing):
            race = result_race(site, row)
            existing.append(race)
            result_page(site, race)
    choices = list(days(today))
    for date in choices:
        if date == today:
            continue
        page = Page(f'races/{date}.html')
        rs = site.day_races.get(date, [])
        meta_path = DATA / 'day-index' / (date + '.json')
        meta = json.loads(meta_path.read_text(encoding='utf-8')) if meta_path.exists() else {}
        venues = {v['jcd']: {**v, 'races': []} for v in meta.get('venues', []) if v.get('cancelled')}
        for race in sorted(rs, key=lambda r: (r['jcd'], r['rno'])):
            jcd = race['jcd']
            if jcd not in VENUES:
                continue
            v = venues.setdefault(jcd, {'jcd': jcd, 'name': VENUES[jcd]['name'], 'title': (race.get('racelist') or {}).get('title', ''), 'races': []})
            res = race.get('result') or {}
            v['races'].append({'rno': race['rno'], 'deadline': race.get('deadline', ''),
                               'result': res.get('trifecta') if res.get('finished') else None,
                               'payout': res.get('trifecta_payout'), 'hit': race.get('hit')})
        tiles, sections = [], []
        for jcd, v in sorted(venues.items()):
            full = sum(not r.get('_archive_results_only') for r in rs if r['jcd'] == jcd)
            count = len(v['races'])
            tiles.append(f'<a class="archive-venue-link" href="#v{jcd}"><b>{e(v["name"])}</b><span>{"中止" if v.get("cancelled") else str(count) + "R"}</span></a>')
            note = '詳細の保存あり' if full == count and count else '出走・結果中心' if not full else '詳細と出走・結果の保存あり'
            sections.append(f'<details class="archive-venue" id="v{jcd}"><summary><b>{e(v["name"])}</b><span>{count}R</span><small>{note}</small></summary>'
                            f'<div class="archive-venue-body"><p class="sub">{e(v.get("title", ""))}</p><div class="rcards">{site.race_cards(page, date, jcd, v)}</div></div></details>')
        prev = (datetime.strptime(date, '%Y%m%d') - timedelta(days=1)).strftime('%Y%m%d')
        nxt = (datetime.strptime(date, '%Y%m%d') + timedelta(days=1)).strftime('%Y%m%d')
        prev_link = f'<a href="{page.u("races/" + prev + ".html")}">← 前日</a>' if prev >= first else '<span>← 前日</span>'
        next_link = f'<a href="{page.u("index.html") + "#held-races" if nxt == today else page.u("races/" + nxt + ".html")}">翌日 →</a>'
        body = (f'<h1>{iso(date)}の開催</h1>{date_picker(page, today, date)}'
                f'<nav class="archive-day-nav">{prev_link}{next_link}</nav>'
                '<p class="archive-note">過去1か月の保存済み情報です。予想・展示・オッズは保存のある項目を表示します。</p>'
                + (f'<div class="archive-venues">{"".join(tiles)}</div>{"".join(sections)}' if sections else
                   '<p class="panel empty">この日の保存データはありません。別の日付を選んでください。</p>'))
        site.put(page.path, page.render(iso(date) + 'の開催・レース｜' + SITE_NAME, '保存済みの過去レースを日付で確認。', body,
                                       [('races.html', '過去の開催'), ('', iso(date))],
                                       script=f'<script src="{page.asset("day-browser.js")}" defer></script>', noindex=True))
    page = Page('races.html')
    links = ''.join(f'<a href="{page.u("index.html") + "#held-races" if date == today else page.u("races/" + date + ".html")}"><b>{iso(date)}</b><span>{"今日" if date == today else str(len(site.day_races.get(date, []))) + "R保存"}</span></a>' for date in reversed(choices))
    body = f'<h1>過去の開催</h1>{date_picker(page, today, today)}<p class="archive-note">{iso(first)}から今日まで。保存のない項目は復元せずに表示します。</p><div class="archive-dates">{links}</div>'
    site.put(page.path, page.render('日付から過去1か月の開催を見る｜' + SITE_NAME, '過去1か月の保存済みレース。', body,
                                   [('', '過去の開催')], script=f'<script src="{page.asset("day-browser.js")}" defer></script>', noindex=True))
