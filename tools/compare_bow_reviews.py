"""Recompute two blind AI bow reviews from source frame PTS.

This measures same-race inter-review agreement, not ground-truth accuracy,
real-time calibration, out-of-sample accuracy or predeadline availability.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

from scraper.turn_measurement import BOW_METHOD, MAX_PAIR_GAP, crossing, digest


def compare(manifest, config, reviews, *, frames_dir=None, tolerance_seconds=.1):
    if len(reviews) != 2 or len({r.get('reviewer') for r in reviews}) != 2 or any(not r.get('reviewer') for r in reviews):
        raise ValueError('Two separately identified reviews are required')
    if not math.isfinite(tolerance_seconds) or not 0 <= tolerance_seconds <= .1:
        raise ValueError('Invalid review agreement tolerance')
    source = manifest['source']
    if (source.get('clock') != 'decoded_pts' or config.get('method') != BOW_METHOD
            or config.get('venue') != 'heiwajima' or config.get('turn') != '1-mark'):
        raise ValueError('Heiwajima bow method with decoded PTS is required')
    size = manifest['image_size']
    if size != config['image_size']:
        raise ValueError('Image coordinate systems differ')
    for review in reviews:
        if review.get('method') != BOW_METHOD or review.get('source_sha256') != source['sha256'] or review.get('size') != size:
            raise ValueError('Review method, source or dimensions differ')
    base = source['time_base']
    if len(base) != 2 or any(type(v) is not int or v <= 0 for v in base):
        raise ValueError('Invalid time base')
    frames = manifest['frames']
    windows = {(w['boat'], w['gate']): set(w['indices']) for w in manifest['windows']}
    if set(windows) != {(boat, gate) for boat in range(1, 7) for gate in 'ABC'}:
        raise ValueError('Six boats and three gate windows are required')
    checked = set()
    directory = Path(frames_dir).resolve() if frames_dir else None
    results = []
    for boat in range(1, 7):
        events, errors = {}, []
        for gate in 'ABC':
            key, attempts = f'{boat}:{gate}', []
            for review in reviews:
                try:
                    pair = review['pairs'][key]
                    samples, evidence = [], []
                    for side in ('before', 'after'):
                        index = pair[side]
                        if type(index) is not int or index not in windows[(boat, gate)]:
                            raise ValueError('frame_outside_target_window')
                        frame = frames[str(index)]
                        if type(frame['pts']) is not int or frame['pts'] < 0:
                            raise ValueError('invalid_pts')
                        label = review['labels'][f'{boat}:{index}']
                        point = label.get('bow')
                        if (label.get('obstructed') is True or not isinstance(point, list) or len(point) != 2
                                or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
                                       or not 0 <= v < size[i] for i, v in enumerate(point))):
                            raise ValueError('bow_missing_or_obstructed')
                        if directory and index not in checked:
                            path = (directory/frame['file']).resolve()
                            if path.parent != directory or hashlib.sha256(path.read_bytes()).hexdigest() != frame['sha256']:
                                raise ValueError('frame_fingerprint_mismatch')
                            checked.add(index)
                        samples.append({'time': frame['pts']*base[0]/base[1], 'x': point[0], 'y': point[1]})
                        evidence.append({'index': index, 'pts': frame['pts'], 'bow': point})
                    if not 0 < samples[1]['time'] - samples[0]['time'] <= MAX_PAIR_GAP:
                        raise ValueError('invalid_bracketing_interval')
                    time = crossing(*samples, config['gates'][gate])
                    if time is None:
                        raise ValueError('gate_not_bracketed')
                    attempts.append({'reviewer': review['reviewer'], 'time': time, 'frames': evidence})
                except (KeyError, ValueError, TypeError, IndexError, OSError) as error:
                    errors.append(f'{key}:{review["reviewer"]}:{str(error) if isinstance(error, ValueError) else "missing_evidence"}')
            if len(attempts) == 2:
                difference = abs(attempts[0]['time']-attempts[1]['time'])
                events[gate] = {'reviews': attempts, 'mean_time': sum(a['time'] for a in attempts)/2,
                                'difference_seconds': difference}
                if difference > tolerance_seconds:
                    errors.append(key+':review_time_disagreement')
        if len(events) == 3 and not events['A']['mean_time'] < events['B']['mean_time'] < events['C']['mean_time']:
            errors.append('invalid_A_B_C_order')
        if len(events) == 3 and any(not events['A']['reviews'][i]['time'] < events['B']['reviews'][i]['time'] < events['C']['reviews'][i]['time'] for i in range(2)):
            errors.append('invalid_reviewer_A_B_C_order')
        row = {'boat': boat, 'events': events, 'reasons': errors,
               'status': 'needs_remeasurement' if errors else 'repeated_ai_video_measurement'}
        if not errors and len(events) == 3:
            row['entry_video_seconds'] = round(events['B']['mean_time']-events['A']['mean_time'], 1)
            row['exit_video_seconds'] = round(events['C']['mean_time']-events['B']['mean_time'], 1)
            row['max_review_time_difference_seconds'] = max(g['difference_seconds'] for g in events.values())
        results.append(row)
    differences = [g['difference_seconds'] for row in results for g in row['events'].values()]
    return {'schema': 1, 'method': BOW_METHOD, 'time_basis': 'decoded_pts_video_seconds',
            'source_sha256': source['sha256'], 'image_size': size, 'gates': config['gates'],
            'reviews': [{'reviewer': r['reviewer'], 'digest': digest(r)} for r in reviews],
            'results': results, 'paired_gate_count': len(differences),
            'valid_gate_pairs': sum(d <= tolerance_seconds for d in differences),
            'max_review_time_difference_seconds': max(differences) if differences else None,
            'review_tolerance_seconds': tolerance_seconds,
            'images_fingerprint_verified': directory is not None and all(not row['reasons'] for row in results),
            'publication_ready': False, 'real_time_scale_verified': False, 'predeadline_verified': False,
            'prediction_used': False, 'note': '同一レース内の独立AI間一致。実測の正確さ・別レース精度の証明ではない。'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('manifest', 'config', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--review', type=Path, required=True, action='append')
    parser.add_argument('--frames-dir', type=Path)
    args = parser.parse_args()
    load = lambda path: json.loads(path.read_text(encoding='utf-8'))
    report = compare(load(args.manifest), load(args.config), [load(p) for p in args.review], frames_dir=args.frames_dir)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'pairs': report['valid_gate_pairs'], 'max_difference_seconds': report['max_review_time_difference_seconds'],
                      'rows': [{k: row.get(k) for k in ('boat', 'status', 'entry_video_seconds', 'exit_video_seconds', 'reasons')}
                               for row in report['results']], 'publication_ready': False}, ensure_ascii=False))


if __name__ == '__main__':
    main()
