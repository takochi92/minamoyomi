"""Separate exhibition viewer shell; race pages receive only a small link."""
import html
import json
import re
import math
from datetime import datetime
from urllib.parse import urlsplit, parse_qs


def research_catalog(raw):
    """Public numeric research only; never approve or copy third-party media."""
    rows, seen = [], set()
    for row in raw.get('records', []) or []:
        if not isinstance(row, dict):
            continue
        key = (row.get('date'), row.get('jcd'), row.get('rno'))
        if not valid_date(key[0]) or key[1] != '04' or type(key[2]) is not int or not 1 <= key[2] <= 12 or key in seen:
            continue
        try:
            url = urlsplit(row.get('official_url', ''))
            query = parse_qs(url.query)
            expected = {'service':['boatcast'], 'stadium':['04heiwajima'], 'raceType':['exhibition'],
                        'raceDate':[key[0]], 'raceNumber':[f'{key[2]:02}'], 'autoplay':['0'], 'bitrate':['low']}
            if url.scheme != 'https' or url.netloc != 'front.player.boatrace-cdn.jp' or url.path != '/player/vod' or query != expected or url.fragment:
                continue
        except (ValueError, TypeError):
            continue
        item = {'date':key[0], 'jcd':key[1], 'rno':key[2], 'official_url':row['official_url']}
        ref = row.get('reference') or {}
        ref = ref if isinstance(ref, dict) else {}
        boats = ref.get('boats') or []
        boats = boats if isinstance(boats, list) and all(isinstance(b,dict) for b in boats) else []
        number = lambda n: type(n) in (int, float) and math.isfinite(n)
        if (ref.get('method') == 'heiwajima-bow-gates-v2' and ref.get('time_basis') == 'decoded_pts_video_seconds'
                and ref.get('publication_ready') is False and ref.get('prediction_used') is False
                and ref.get('predeadline_verified') is False and ref.get('review_count') == 2
                and number(ref.get('max_review_difference_seconds')) and 0 <= ref['max_review_difference_seconds'] <= .1
                and len(boats) == 6 and all(type(b.get('boat')) is int for b in boats)
                and {b.get('boat') for b in boats} == set(range(1,7))
                and all(type(b.get('boat')) is int and isinstance(b.get('name'), str) and 0 < len(b['name']) <= 30
                        and all(number(b.get(k)) and 0 < b[k] <= 30 for k in ('entry','exit')) for b in boats)):
            item['reference'] = {'boats':sorted([{'boat':b['boat'],'name':b['name'],'entry':b['entry'],'exit':b['exit']} for b in boats], key=lambda b:b['boat']),
                                 'max_review_difference_seconds':ref['max_review_difference_seconds']}
        seen.add(key); rows.append(item)
    return rows


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


def render(page, venues, date, records, *, preview=False, research=None):
    options = ''.join(f'<option value="{html.escape(j)}">{html.escape(v["name"])}</option>' for j, v in venues.items())
    config = {'date': date, 'records': records, 'preview': preview, 'research':research_catalog({'records':research or []}),
              'slugs': {j: v['slug'] for j, v in venues.items()}, 'raceBase': page.u('')}
    payload = json.dumps(config, ensure_ascii=False, allow_nan=False).replace('<', '\\u003c')
    return (f'<link rel="stylesheet" href="{page.asset("exhibition.css")}">'
            '<h1>展示解析 <small class="ev-beta">平和島・試験公開</small></h1><p class="sub">１マークの入り・出口を、映像と参考タイムで確認</p>'
            '<form id="ev-select" class="ev-select"><label>日付<input id="ev-date" type="date" required></label>'
            f'<label>場<select id="ev-venue">{options}</select></label>'
            '<label>レース<select id="ev-race">' + ''.join(f'<option value="{n}">{n}R</option>' for n in range(1, 13)) + '</select></label>'
            '<button type="submit">表示する</button></form>'
            '<nav id="ev-races" class="ev-races" aria-label="レース番号">' + ''.join(f'<button type="button" data-ev-race="{n}">{n}R</button>' for n in range(1,13)) + '</nav>'
            '<div class="ev-line"><h2 id="ev-title">映像を選択</h2><a id="ev-back" hidden>レースページへ →</a></div>'
            '<p id="ev-status" role="status"></p><section id="ev-reference" hidden aria-label="映像内の参考タイム">'
            '<p class="ev-reference-label">映像内の参考タイム <span>検証中</span></p><div id="ev-times"></div>'
            '<p class="sub">実走タイムではありません。進路や旋回半径も含むため、機力の順位には使えません。</p></section>'
            '<p id="ev-source-wrap" hidden><a id="ev-source" target="_blank" rel="noopener noreferrer">このレースの公式展示映像を見る ↗</a></p>'
            '<div id="ev-view" hidden>'
            '<iframe id="ev-frame" title="選択したレースの展示映像" sandbox="allow-scripts" loading="lazy"></iframe>'
            '<p class="sub"><a id="ev-open" target="_blank" rel="noopener">映像画面を別に開く →</a></p></div>'
            '<details class="ev-info"><summary>測り方・照合結果・出典を見る</summary><p>全艇共通の画像上の３本の固定線を艇首が通過する時刻を、原動画の前後コマから計算します。入りはA→B、出口はB→Cです。減速開始や加速完了そのものを検出した値ではありません。</p>'
            '<p id="ev-audit">未測定のレースに参考値を補いません。</p><p>別々のAIによる一致は、実際の走行時間の精度を証明するものではありません。編集速度、カメラ・画角の影響、別レースでの精度は検証中。予想・的中実績には不使用です。</p>'
            '<p>映像出典：BOATCAST。公式映像は提供元の画面を別タブで開きます。艇ろぐでの映像の再配信は行っていません。</p></details>'
            + ('<details class="ev-info"><summary>測定の確認画面（開発用）</summary><p><a id="ev-review" hidden target="_blank" rel="noopener">艇首・艇尾と通過コマを確認する →</a></p></details>' if preview else '') +
            f'<script type="application/json" id="ev-config">{payload}</script><script src="{page.asset("exhibition.js")}" defer></script>')
