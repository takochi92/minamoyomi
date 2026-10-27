"""Daily official prize-money snapshot, independent of betting predictions."""
from datetime import datetime
import argparse
import hashlib
import re
from urllib.parse import urlparse, parse_qs
from bs4 import BeautifulSoup
from .database_sources import BASE, JST, session, fetch, read_json, write_json

STORE = BASE / 'prizes'


def parse_omura(raw, year):
    soup = BeautifulSoup(raw, 'html.parser')
    text = soup.get_text(' ', strip=True)
    dates = re.findall(r'期間\s*[：:]\s*(\d{4})年\s*(\d+)月\s*(\d+)日\s*[～〜~]\s*(\d{4})年\s*(\d+)月\s*(\d+)日', text)
    if not dates or len(set(dates)) != 1:
        raise ValueError('Official ranking period missing or inconsistent')
    y, m, day, ey, em, ed = map(int, dates[0])
    start, end = datetime(y,m,day), datetime(ey,em,ed)
    if y != year or ey != year or start > end:
        raise ValueError('Official ranking year mismatch')
    rows = {}
    for node in soup.select('[data-rank]'):
        anchor = node.find_parent('a')
        if anchor is None:
            raise ValueError('Official ranking link missing')
        url = urlparse(anchor.get('href', ''))
        toban = parse_qs(url.query).get('toban', [''])[0]
        info, money = anchor.select_one('.racer_info'), anchor.select_one('.prizemoney')
        name = info.select_one('span') if info else None
        if url.hostname not in {'www.boatrace.jp','boatrace.jp'} or not re.fullmatch(r'\d{4}',toban) or name is None or money is None:
            raise ValueError('Official ranking row incomplete')
        amount = re.fullmatch(r'[¥￥]\s*([\d,]+)', money.get_text(strip=True))
        rank = int(node['data-rank'])
        if amount is None:
            raise ValueError('Official prize money invalid')
        row = {'rank':rank,'toban':toban,'name':re.sub(r'\s','',name.get_text()),'amount':int(amount[1].replace(',',''))}
        if rank in rows and rows[rank] != row:
            raise ValueError('Conflicting official ranking duplicate')
        rows[rank] = row
    ranked = [rows[k] for k in sorted(rows)]
    if len(ranked) < 18 or sorted(rows) != list(range(1,len(rows)+1)) or len({r['toban'] for r in ranked}) != len(ranked):
        raise ValueError('Official ranking incomplete')
    if any(a['amount'] < b['amount'] for a,b in zip(ranked,ranked[1:])):
        raise ValueError('Official prize order inconsistent')
    return {'year':year,'from':start.strftime('%Y%m%d'),'through':end.strftime('%Y%m%d'),'players':ranked}


def refresh(year=None):
    now = datetime.now(JST);year = year or now.year
    # Only a published official page is read; a missing new-year page keeps
    # the last snapshot instead of relabelling old figures as current.
    source = f'https://omurakyotei.jp/special/{year}grandprix/prize_ranking/'
    raw = fetch(session(), source)
    report = parse_omura(raw,year)
    if report['through'] > now.strftime('%Y%m%d'):
        raise ValueError('Official ranking date is in the future')
    path = STORE / 'latest.json'
    previous = read_json(path,{}) or {}
    if previous.get('through','') > report['through']:
        raise ValueError('Official ranking snapshot would regress')
    report.update(source=source,checked_at=now.isoformat(),sha256=hashlib.sha256(raw).hexdigest())
    write_json(path,report)
    print('official prizes:',report['through'],len(report['players']),'players',flush=True)


if __name__ == '__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--year',type=int)
    refresh(ap.parse_args().year)
