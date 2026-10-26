"""Audit local turn evidence without promoting research to official data.

Position perturbation is sensitivity analysis, NOT measured annotation error.
One person's second pass or a second method is not an independent reviewer.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def crossing_sensitivity(before, after, gate, position_error_px=3):
    """Conservative directed crossing bounds under stated image-point error."""
    if not math.isfinite(position_error_px) or position_error_px < 0:
        raise ValueError('invalid_position_error')
    axis, other = ('x', 'y') if gate['axis'] == 'x' else ('y', 'x')
    values = [before[k] for k in ('x', 'y', 'time')] + [after[k] for k in ('x', 'y', 'time')]
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values):
        raise ValueError('nonfinite_sample')
    if not 0 < after['time'] - before['time'] <= .12:
        return {'status': 'remeasure', 'reason': 'frame_interval'}
    direction, line = gate['direction'], gate['value']
    a, b = direction * (before[axis] - line), direction * (after[axis] - line)
    error = position_error_px
    if not a + error < 0 <= b - error:
        return {'status': 'remeasure', 'reason': 'position_error_can_change_bracketing'}
    if any(not gate['segment'][0] + error <= p[other] <= gate['segment'][1] - error for p in (before, after)):
        return {'status': 'remeasure', 'reason': 'position_error_can_leave_gate'}
    times = [before['time'] + (-x) / (y-x) * (after['time']-before['time'])
             for x in (a-error, a+error) for y in (b-error, b+error)]
    time = before['time'] + (-a)/(b-a)*(after['time']-before['time'])
    return {'status': 'bounded_under_assumption', 'time': time, 'low': min(times), 'high': max(times),
            'assumed_position_error_px': error}


def audit(manifest, annotations, config, *, independent_reviews=(), editing_speed_evidence=None,
          heldout_results=(), point_error_px=3):
    frames, source = manifest['frames'], manifest['source']
    base = source['time_base']
    times = [r['pts'] * base[0] / base[1] for r in frames]
    gaps = [b-a for a, b in zip(times, times[1:])]
    clock_ok = bool(gaps) and all(0 < gap <= .12 for gap in gaps)
    duplicate_count = sum(a.get('sha256') == b.get('sha256') for a, b in zip(frames, frames[1:]))
    rows = []
    for boat in range(1, 7):
        events, reasons = {}, []
        for gate in 'ABC':
            key = f'{boat}:{gate}'
            try:
                samples = []
                for side in ('before', 'after'):
                    i = annotations['pairs'][key][side]
                    if type(i) is not int or not 0 <= i < len(frames):
                        raise ValueError('invalid_frame_id')
                    label = annotations['labels'][f'{boat}:{i}']
                    bow, stern = label['bow'], label['stern']
                    samples.append({'time': times[i], 'x': (bow[0]+stern[0])/2, 'y': (bow[1]+stern[1])/2})
                events[gate] = crossing_sensitivity(*samples, config['gates'][gate], position_error_px=point_error_px)
                if events[gate]['status'] == 'remeasure': reasons.append(gate+':'+events[gate]['reason'])
            except (KeyError, IndexError, TypeError, ValueError):
                reasons.append(gate+':missing_or_invalid_annotation')
        if not reasons and not events['A']['time'] < events['B']['time'] < events['C']['time']:
            reasons.append('invalid_A_B_C_order')
        row = {'boat': boat, 'gate_sensitivity': events, 'reasons': reasons,
               'status': 'remeasure' if reasons else 'single_reviewer_research_only'}
        if not reasons:
            for name, first, last in [('entry', 'A', 'B'), ('exit', 'B', 'C')]:
                lo, hi = events[last]['low']-events[first]['high'], events[last]['high']-events[first]['low']
                row[name] = {'seconds': round(events[last]['time']-events[first]['time'], 1),
                             'sensitivity_low': lo, 'sensitivity_high': hi,
                             'tenths_stable_under_assumption': round(lo, 1) == round(hi, 1)}
        rows.append(row)
    # Named reviewer strings alone do not establish reviewer identity or work.
    distinct_reviews = {r['reviewer_id'] for r in independent_reviews
                        if r.get('independence_verified') is True and r.get('all_hull_points_checked') is True
                        and r.get('reviewer_id') and r.get('evidence_sha256') == source['sha256']}
    holdouts = {r['race_id']: r for r in heldout_results if r.get('race_id') and r.get('unused_for_tuning') is True}
    dates = {r.get('date') for r in holdouts.values() if r.get('date')}
    blockers = []
    if source.get('clock') != 'decoded_pts' or not clock_ok: blockers.append('decoded_clock_invalid')
    if len(distinct_reviews) < 2: blockers.append('independent_hull_review_not_complete')
    if not editing_speed_evidence or editing_speed_evidence.get('verified') is not True:
        blockers.append('real_time_scale_not_verified')
    if len(holdouts) < 20 or len(dates) < 3:
        blockers.append('heldout_races_not_complete')
    if any(row['reasons'] for row in rows): blockers.append('crossings_need_remeasurement')
    if any(not metric['tenths_stable_under_assumption'] for row in rows for key, metric in row.items()
           if key in ('entry', 'exit')):
        blockers.append('reported_tenths_sensitive_to_point_position')
    return {'kind': 'turn-validation-audit-v1', 'source_sha256': source['sha256'], 'frame_count': len(frames),
            'pts_strict_and_continuous': clock_ok, 'duplicate_decoded_frames': duplicate_count,
            'rows': rows, 'independent_reviews': len(distinct_reviews), 'heldout_races': len(holdouts),
            'heldout_dates': len(dates), 'blockers': blockers,
            'publication_ready': False, 'prediction_used': False,
            'note': '感度分析は実測誤差ではない。この監査単体は公開を許可しない。'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('manifest', 'annotations', 'config', 'output'):
        parser.add_argument('--'+name, required=True, type=Path)
    args = parser.parse_args()
    read = lambda path: json.loads(path.read_text(encoding='utf-8'))
    result = audit(read(args.manifest), read(args.annotations), read(args.config))
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: result[key] for key in ('frame_count', 'pts_strict_and_continuous', 'independent_reviews',
                                                  'heldout_races', 'blockers', 'publication_ready')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
