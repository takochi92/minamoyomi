"""Display-only v5 straight-line simulation; never feeds betting probabilities."""
import hashlib
import json
import math
from functools import lru_cache

from . import slit_model_constants as C


CONSTANTS = {k: v for k, v in vars(C).items() if k.isupper()}
FINGERPRINT = hashlib.sha256(json.dumps(CONSTANTS, sort_keys=True).encode()).hexdigest()[:16]


def number(x, positive=False):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and (not positive or x > 0)


def clamp(x, a, b):
    return max(a, min(b, x))


def position(boat, t):
    dt = t - boat['st']
    if dt < 0:
        return boat['v0'] * dt
    if dt <= boat['t_acc']:
        return boat['v0'] * dt + .5 * boat['acceleration'] * dt * dt
    return C.ACC_DIST + boat['v_top'] * (dt - boat['t_acc'])


def calculate(boats, weather=None):
    """Pure calculation for validated per-course inputs; no result information."""
    weather = weather or {}
    mean_ex = sum(b['exhibit'] for b in boats) / len(boats)
    straight = all(number(b.get('straight'), True) for b in boats)
    lap = all(number(b.get('lap'), True) for b in boats)
    mean_cho = sum(b['straight'] for b in boats) / len(boats) if straight else None
    mean_lap = sum(b['lap'] for b in boats) / len(boats) if lap else None
    rough = ((number(weather.get('wind_speed')) and weather['wind_speed'] >= C.ROUGH_WIND)
             or (number(weather.get('wave_cm')) and weather['wave_cm'] >= C.ROUGH_WAVE))
    out = []
    for b in boats:
        t = b['exhibit'] * (1 - C.CHO_WEIGHT) + b['straight'] * mean_ex / mean_cho * C.CHO_WEIGHT if straight else b['exhibit']
        v = C.D / t
        residual = b['lap'] - (mean_lap + C.LAP_EX_COEF * (b['exhibit'] - mean_ex)) if lap else None
        r = clamp(C.R_BASE - C.RESIDUAL_COEF * residual, C.R_MIN, C.R_MAX) if lap else clamp(
            C.FALLBACK_R + (C.NEGATIVE_TILT_ADD if number(b.get('tilt')) and b['tilt'] < 0 else 0)
            + (C.OUTER_COURSE_ADD if b['course'] >= 4 else 0), C.R_MIN, C.R_MAX)
        v0 = r * v
        ta = C.ACC_DIST / ((v0 + v) / 2)
        sigma = b.get('sd')
        out.append({**b, 'r': r, 'v_top': v, 'v0': v0, 't_acc': ta,
                    'acceleration': (v - v0) / ta, 'arrival': b['st'] + ta + (C.D - C.ACC_DIST) / v,
                    'error_m': sigma * v * (C.ROUGH_ERROR_MULTIPLIER if rough else 1) if number(sigma) and sigma >= 0 else None})
    lead = min(b['arrival'] for b in out)
    leader = min(out, key=lambda b: b['arrival'])
    for b in out:
        gap = position(b, lead) - C.D
        b['gap'] = 0.0 if abs(gap) < 1e-8 else gap
    overlap = any(b is not leader and b['error_m'] is not None and leader['error_m'] is not None
                  and abs(b['gap']) <= b['error_m'] + leader['error_m'] for b in out)
    return {'status': 'ready', 'boats': out, 'lead_time': lead, 'rough': bool(rough), 'overlap': overlap,
            'uncertainty_missing': any(b['error_m'] is None for b in out),
            'lap_used': lap, 'straight_used': straight,
            'weather_incomplete': not (number(weather.get('wind_speed')) and number(weather.get('wave_cm'))),
            'weather': weather, 'distance': C.D, 'acc_distance': C.ACC_DIST,
            'move_seconds': C.MOVE_SECONDS, 'hold_seconds': C.HOLD_SECONDS}


@lru_cache(maxsize=1)
def references():
    from . import fstart, coursest
    return fstart.load_pairs(), coursest.load()


def build(race):
    from .predict import VENUES
    before = race.get('before') or {}
    se = before.get('start_exhibition') or []
    wait = {'status': 'waiting', 'reason': '6艇の展示タイム・進入・STが揃うまで待機します。欠損を欠場とは扱いません。'}
    if len(se) != 6 or {x.get('frame') for x in se} != set(range(1, 7)) or {x.get('course') for x in se} != set(range(1, 7)):
        return wait
    rl = {b['frame']: b for b in (race.get('racelist') or {}).get('boats') or []}
    bx = {b['frame']: b for b in before.get('boats') or []}
    timing = (race.get('start_timing') or {}).get('boats') or {}
    pairs, cst = references()
    ot = race.get('oriten') or {}
    def detail(frame, item):
        items = ot.get('items') or []
        row = (ot.get('rows') or {}).get(str(frame)) or []
        i = items.index(item) if item in items else -1
        return row[i] if 0 <= i < len(row) and number(row[i], True) else None
    out = []
    for s in sorted(se, key=lambda x: x['course']):
        f, c = s['frame'], s['course']
        b, x = rl.get(f, {}), bx.get(f, {})
        ex = x.get('exhibit_time')
        if not number(ex, True) or not b.get('toban'):
            return wait
        ref = timing.get(str(f)) or {}
        if ref.get('course') != c or ref.get('toban') != b['toban']:
            ref = {}
        if not ref:
            ps = [p for p in pairs.get(b['toban'], []) if len(p) >= 4 and p[3] < race['date']]
            cp = [p for p in ps if p[0] == c]
            ps = cp if len(cp) >= 3 else ps
            if len(ps) >= 3:
                mean = sum(p[2] / 100 for p in ps) / len(ps)
                ref = {'st': mean, 'sd': math.sqrt(sum((p[2] / 100 - mean) ** 2 for p in ps) / len(ps)), 'source': 'legacy_prior_day', 'n': len(ps)}
        sd = ref.get('sd')
        if number(ref.get('st')):
            st, source = ref['st'], ref.get('source', 'prior_day_actual_course_local')
        else:
            averages = (cst.get('r') or {}).get(b['toban'], {}).get(str(c), {})
            # Cached aggregates may only be used if their entire window is prior-day.
            window = cst.get('window', '')
            safe = bool(window and window.split('-')[-1] < race['date'])
            def avg(key):
                v = averages.get(key) or []
                return v[3] / v[4] / 100 if safe and len(v) >= 5 and v[4] else None
            av = (race.get('start_timing') or {}).get('averages', {}).get(str(f)) or {}
            options = [('course_average_blend', av.get('course') if number(av.get('course')) else avg('a')),
                       ('meeting_average_blend', av.get('meeting')), ('local_average_blend', av.get('local')),
                       ('program_average_blend', b.get('avg_st'))]
            source, average = next(((k, v) for k, v in options if number(v)), ('exhibition_only', None))
            est = s.get('st')
            if not number(est):
                return wait
            st = clamp(C.ST_EX_WEIGHT * est + (1 - C.ST_EX_WEIGHT) * average, C.ST_MIN, C.ST_MAX) if number(average) else est
            if not number(average):
                source = 'exhibition_only'
        out.append({'frame': f, 'course': c, 'name': b.get('name', ''), 'toban': b['toban'],
                    'st': st, 'sd': sd, 'st_source': source, 'st_n': ref.get('n'),
                    'exhibition_st': s.get('st'), 'exhibit': ex, 'lap': detail(f, '一周'),
                    'turn': detail(f, 'まわり足'), 'straight': detail(f, '直線'), 'tilt': x.get('tilt')})
    payload = calculate(out, before.get('weather'))
    return {**payload, 'version': C.VERSION, 'fingerprint': FINGERPRINT,
            'input_fingerprint': hashlib.sha256(json.dumps({'boats': out, 'weather': before.get('weather')}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16],
            'fukuoka': bool(VENUES.get(race.get('jcd'), {}).get('exhibition_special_measurement'))}
