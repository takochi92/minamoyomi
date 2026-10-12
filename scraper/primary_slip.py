"""締切前に採用券を一つに固定。結果を見て券を足さない。"""
from datetime import datetime, timedelta, timezone

from . import arechu

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
    final = bool(tk.get('final')) if ana else bool((race.get('reco') or {}).get('final'))
    source = ''
    # 荒れ注意（A級1号艇で万舟が出やすい条件）のレースは、無難な本線をやめて穴予想に一本化する。
    # 券の種類は「穴予想」（ana）と同じ扱いにして、的中・投資・払戻もほかのレースと同じ集計に入れる。
    ar = arechu.from_race(race)
    if ar:
        ana, selected, source = True, ar['tickets'], 'arechu'
        final = p.get('stage') == '直前'
    race['primary_slip'] = {'policy': POLICY, 'kind': 'ana' if ana else 'standard',
                            'tickets': selected, 'amount': 100, 'selected_at': now.isoformat(),
                            'model_version': p.get('version'), 'model_revision': p.get('model_revision'),
                            'stage': p.get('stage'), 'final': final}
    if source:
        race['primary_slip']['source'] = source
    return True
