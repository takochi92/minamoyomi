import json
from pathlib import Path

import pytest

from scraper import next_meetings as nm


def calendar(date='20261102', title='次回大会'):
    fields = '<select name="TTRMP010A_4"><option value="2026" selected>2026</option></select><select name="TTRMP010A_5"><option value="11" selected>11</option></select>'
    return fields + '<table>' + ''.join(
        f'<tr><th><a href="/owpc/pc/data/stadium?jcd={j:02}">場</a></th>'
        f'<td><a href="/owpc/pc/race/assen?jcd={j:02}&amp;hd={date}">{title}</a></td></tr>'
        for j in range(1, 25)) + '</table>'


def entrant_html(date='2026/11/02-2026/11/07'):
    return ('<div class="heading2"><img src="/static_extra/pc/images/text_place2_02.png">'
            '<h2 class="heading2_titleName">次回大会</h2></div>'
            f'<p class="h-alignR">{date}</p><ul>' + ''.join(
                f'<li><a href="/owpc/pc/data/racersearch/profile?toban={t}">選手</a>'
                f'<div><p class="photoGallery3_bodyNumber">{t}</p>'
                f'<p class="photoGallery3_bodyName">選手　{t}</p>'
                '<p class="photoGallery3_bodyClass">級別：<span>A2</span></p></div></li>'
                for t in reversed(range(4001, 4007))) + '</ul>')


def event():
    return {'jcd': '02', 'from': '20261102', 'title': '次回大会',
            'source': nm.BASE + 'assen?jcd=02&hd=20261102'}


def test_national_calendar_validates_all_venues_and_requested_month():
    events = nm.parse_calendar(calendar(), '20261030', '202611')
    assert len(events) == 24 and events['02']['from'] == '20261102'
    assert nm.parse_calendar(calendar('20261030'), '20261030', '202611') == {}
    with pytest.raises(ValueError, match='Incomplete national'):
        nm.parse_calendar(calendar().replace('stadium?jcd=24', 'missing?jcd=24'), '20261030')
    with pytest.raises(ValueError, match='month mismatch'):
        nm.parse_calendar(calendar(), '20261030', '202612')


def test_entrants_require_exact_venue_date_and_registration_identity():
    data = nm.parse_entrants(entrant_html(), event())
    assert data['through'] == '20261107'
    assert [r['toban'] for r in data['entrants']] == [str(t) for t in range(4001, 4007)]
    with pytest.raises(ValueError, match='another meeting'):
        nm.parse_entrants(entrant_html('2026/11/03-2026/11/08'), event())
    with pytest.raises(ValueError, match='identity missing'):
        nm.parse_entrants(entrant_html().replace('text_place2_02', 'text_place2_03'), event())
    with pytest.raises(ValueError, match='registration mismatch'):
        nm.parse_entrants(entrant_html().replace('toban=4001', 'toban=4999'), event())


def test_missing_entrants_do_not_become_an_empty_confirmed_list():
    with pytest.raises(ValueError, match='incomplete'):
        nm.parse_entrants(entrant_html().replace('photoGallery3_bodyNumber', 'not-a-number'), event())


def test_no_expired_meeting_is_advertised_as_next():
    data = {'venues': {'02': event()}}
    assert nm.upcoming(data, '02', '20261101')
    assert nm.upcoming(data, '02', '20261102') is None
    assert nm.upcoming(data, '02', '20261103') is None
    assert nm.upcoming(data, '03', '20261101') is None


def test_render_sorts_entries_preserves_zero_and_labels_win_period():
    class Page:
        def u(self, path): return '../' + path
    ev = nm.parse_entrants(entrant_html(), event())
    ev['entrants'][0]['win'] = 0
    ev['entrants'][1]['win'] = 5.43
    ev['entrants'].reverse()
    html = nm.render(Page(), ev, 'fan2604.lzh')
    assert html.index('4001') < html.index('4002') < html.index('4006')
    assert '>0.00<' in html and '>5.43<' in html and '>—<' in html
    assert '../racer/4001.html' in html and 'profile?toban=4003' in html
    assert '2026年後期の期別成績' in html and '11/2〜11/7' in html
    assert '公式の出場予定' in html and '登録番号順' in html
    assert '日程確認中' in nm.render(Page(), None, '')
    ev['win_source'] = 'fan2510.lzh'
    assert '2026年前期' in nm.render(Page(), ev, 'fan2604.lzh')


def test_total_calendar_failure_keeps_previous_file(tmp_path):
    path = tmp_path / 'next.json'
    path.write_text('{"venues":{}}')
    def fail(url): raise OSError('offline')
    # Fan source remains the real local roster; no personal data is involved.
    with pytest.raises(RuntimeError, match='previous data retained'):
        nm.refresh('20261030', fetch=fail, path=path)
    assert path.read_text() == '{"venues":{}}'


def test_partial_calendar_cannot_claim_a_later_meeting_is_the_next(tmp_path, monkeypatch):
    monkeypatch.setattr(nm, 'ROOT', tmp_path)
    (tmp_path / 'scraper').mkdir()
    (tmp_path / 'scraper/racers.json').write_text(json.dumps({'source': 'fan2604.lzh', 'racers': {}}))
    path = tmp_path / 'next.json'
    old = event()
    old['from'] = '20261031'
    old['entrants'] = []
    path.write_text(json.dumps({'venues': {'02': old}}))
    def fetch(url):
        if 'ym=202610' in url: raise OSError('unavailable current month')
        if 'ym=202611' in url: return calendar()
        raise OSError('unpublished')
    data = nm.refresh('20261030', fetch=fetch, path=path)
    assert list(data['venues']) == ['02']
    assert data['venues']['02']['from'] == '20261031'
    assert data['venues']['02']['refresh_pending']
