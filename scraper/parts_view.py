"""Compact display of saved official pre-race parts; no prediction inputs."""
import html
import re


def block(race, boat_badge):
    before = race.get('before') or {}
    boats = {b['frame']: b for b in before.get('boats', [])
             if isinstance(b, dict) and type(b.get('frame')) is int and 1 <= b['frame'] <= 6}
    rows, complete = [], True
    for frame in range(1, 7):
        boat = boats.get(frame, {})
        parts, prop = boat.get('parts'), boat.get('propeller')
        complete &= (isinstance(parts, list) and all(isinstance(x, str) for x in parts)
                     and isinstance(prop, str))
        items = [x.strip() for x in parts if isinstance(x, str) and x.strip()] if isinstance(parts, list) else []
        if isinstance(prop, str) and prop.strip():
            items.append('新ペラ' if prop.strip() == '新' else 'プロペラ：' + prop.strip())
        if items:
            rows.append(f'<div class="parts-tiny-row">{boat_badge(frame)}'
                        f'<span>{html.escape("／".join(items))}</span></div>')
    if not rows:
        status = '記載なし' if complete else '未取得'
        return (f'<section class="parts-tiny parts-status" aria-label="部品交換">'
                f'<span>部品交換</span><small>{status}</small></section>')
    status = f'{len(rows)}艇' + ('・一部未取得' if not complete else '')
    source = ''
    day, venue, number = race.get('date', ''), race.get('jcd', ''), race.get('rno')
    if (isinstance(day, str) and re.fullmatch(r'\d{8}', day)
            and isinstance(venue, str) and re.fullmatch(r'(0[1-9]|1\d|2[0-4])', venue)
            and type(number) is int and 1 <= number <= 12):
        url = f'https://www.boatrace.jp/owpc/pc/race/beforeinfo?hd={day}&jcd={venue}&rno={number}'
        source = f' <a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener">公式 ↗</a>'
    return ('<details class="parts-tiny"><summary><span>部品交換</span>'
            f'<small>{status}</small></summary>'
            '<div class="parts-tiny-body" tabindex="0" role="region" aria-label="部品交換の詳細">'
            + ''.join(rows)
            + '<p>このレースの公式掲載内容。記載のある艇のみ。節間の累積履歴ではありません。'
            + source + '</p></div></details>')
