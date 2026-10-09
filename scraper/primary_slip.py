"""締切前に採用券を一つに固定。結果を見て券を足さない。"""
from datetime import datetime, timedelta, timezone

POLICY = 'single_slip_v1'
JST = timezone(timedelta(hours=9))


def standard_tickets(race):
    bets = (race.get('prediction') or {}).get('bets') or {}
    return list(dict.fromkeys(b['combo'] for b in bets.get('main', []) + bets.get('sub', [])))


def tickets(race):
    saved = race.get('primary_slip')
    return list(saved['tickets']) if saved and saved.get('policy') == POLICY else standard_tickets(race)


def prepare(race, now):
    if now.tzinfo is None:
        raise ValueError('timezone-aware timestamp required')
    dl = datetime.strptime(race['date']+' '+race['deadline'], '%Y%m%d %H:%M').replace(tzinfo=JST)
    if now >= dl or (race.get('result') or {}).get('finished'):
        return False
    p = race.get('prediction') or {}
    if not p.get('bets'):
        return False
    tp, tk = p.get('tsuke_pick') or {}, race.get('tsuke') or {}
    # 既存の厳選穴条件のみ。別の穴候補を足し合わせない。
    ana = p.get('stage') == '直前' and tk.get('active') and bool(tp.get('bets'))
    selected = list(dict.fromkeys(tp['bets'])) if ana else standard_tickets(race)
    race['primary_slip'] = {'policy': POLICY, 'kind': 'ana' if ana else 'standard',
                            'tickets': selected, 'amount': 100, 'selected_at': now.isoformat(),
                            'model_version': p.get('version'), 'model_revision': p.get('model_revision'),
                            'stage': p.get('stage'), 'final': bool(tk.get('final')) if ana else bool((race.get('reco') or {}).get('final'))}
    return True
