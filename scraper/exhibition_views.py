"""Separate exhibition viewer shell; race pages receive only a small link."""
import html
import json
import re
from datetime import datetime


def valid_date(value):
    try:
        return bool(re.fullmatch(r'\d{8}', value) and datetime.strptime(value, '%Y%m%d'))
    except (TypeError, ValueError):
        return False


def catalog(raw, *, preview=False):
    rows, seen = [], set()
    for row in raw.get('records', []):
        key = (row.get('date'), row.get('jcd'), row.get('rno'))
        asset = row.get('asset', '')
        if (not valid_date(key[0]) or key[1] not in {f'{n:02}' for n in range(1, 25)}
                or type(key[2]) is not int or not 1 <= key[2] <= 12 or key in seen):
            continue
        if (not isinstance(asset, str) or not re.fullmatch(r'data/exhibition/[A-Za-z0-9_/-]+\.html', asset)
                or '..' in asset or '//' in asset):
            continue
        if not preview and (row.get('publish') is not True or row.get('rights_verified') is not True):
            continue
        seen.add(key)
        rows.append({'date': key[0], 'jcd': key[1], 'rno': key[2], 'asset': asset,
                     'status': '公開' if row.get('publish') is True else '確認用'})
    return rows


def render(page, venues, date, records, *, preview=False):
    options = ''.join(f'<option value="{html.escape(j)}">{html.escape(v["name"])}</option>' for j, v in venues.items())
    config = {'date': date, 'records': records, 'preview': preview,
              'slugs': {j: v['slug'] for j, v in venues.items()}, 'raceBase': page.u('')}
    payload = json.dumps(config, ensure_ascii=False, allow_nan=False).replace('<', '\\u003c')
    return (f'<link rel="stylesheet" href="{page.asset("exhibition.css")}">'
            '<h1>展示映像</h1><p class="sub">場とレースを選んで、１マークの入り・出口を見比べる</p>'
            '<form id="ev-select" class="ev-select"><label>日付<input id="ev-date" type="date" required></label>'
            f'<label>場<select id="ev-venue">{options}</select></label>'
            '<label>レース<select id="ev-race">' + ''.join(f'<option value="{n}">{n}R</option>' for n in range(1, 13)) + '</select></label>'
            '<button type="submit">映像を見る</button></form>'
            '<div class="ev-line"><h2 id="ev-title">映像を選択</h2><a id="ev-back" hidden>レースページへ →</a></div>'
            '<p id="ev-status" role="status"></p><div id="ev-view" hidden>'
            '<iframe id="ev-frame" title="選択したレースの展示映像" sandbox="allow-scripts" loading="lazy"></iframe>'
            '<p class="sub"><a id="ev-open" target="_blank" rel="noopener">映像画面を別に開く →</a></p></div>'
            '<details class="ev-info"><summary>映像・計測について</summary><p>現在は平和島で検証中。未収録のレースや未確認のタイムは表示しません。'
            '映像内の区間タイムには旋回経路や操縦の違いも含まれ、機力だけを示す数値ではありません。</p></details>'
            + ('<details class="ev-info"><summary>測定の確認画面（開発用）</summary><p><a id="ev-review" hidden target="_blank" rel="noopener">艇首・艇尾と通過コマを確認する →</a></p></details>' if preview else '') +
            f'<script type="application/json" id="ev-config">{payload}</script><script src="{page.asset("exhibition.js")}" defer></script>')
