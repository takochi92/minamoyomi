"""プレミアムのモーター評価が、場ごと・項目ごとにどれだけ埋まっているかを数える。

公開（レースページのプレミアムタブ）の判断材料。評価の中身（S〜D）は出さず、件数だけを出す。

  python -m scraper.premium_coverage <スナップショット.json>      # Markdown の表
  python -m scraper.premium_coverage <スナップショット.json> --json
  python -m scraper.premium_coverage --through 20261116           # その場で評価を作って数える
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .predict import VENUES

MOTOR_METRICS = ('exhibition', 'straight')               # 号機ごとの評価
PAIR_METRICS = ('turn', 'acceleration', 'overall')        # 今節の号機×選手の評価
LABELS = {'exhibition': '展示', 'straight': '伸び', 'turn': 'まわり足', 'acceleration': '立ち上がり', 'overall': '総評'}
SOURCE_MARK = {'lap_minus_turn': '算', 'unconfirmed_section': '算', 'video': '独'}


def coverage(snapshot: dict) -> dict:
    """{'through', 'venues': {jcd: {'motors': n, metric: {'motors': n, 'source': 印}}}, 'filled': 埋まっている場の数}"""
    out = {}
    for jcd in sorted(VENUES):
        field = (snapshot.get('venues') or {}).get(jcd)
        if not field:
            out[jcd] = {'motors': 0, **{m: {'motors': 0, 'source': ''} for m in LABELS}}
            continue
        motors = field.get('motors') or {}
        pairs = field.get('pairings') or {}
        row = {'motors': len(set(motors) | set(pairs))}
        for metric in MOTOR_METRICS:
            scores = [s[metric] for s in motors.values() if metric in s]
            row[metric] = {'motors': len(scores), 'source': next((SOURCE_MARK.get(s.get('source'), '') for s in scores if s.get('source')), '')}
        for metric in PAIR_METRICS:
            scores = [r[metric] for riders in pairs.values() for r in riders.values() if metric in r]
            graded = {m for m, riders in pairs.items() if any(metric in r for r in riders.values())}
            row[metric] = {'motors': len(graded), 'source': next((SOURCE_MARK.get(s.get('source'), '') for s in scores if s.get('source')), '')}
        out[jcd] = row
    filled = {m: sum(1 for r in out.values() if r[m]['motors'] > 0) for m in LABELS}
    return {'through': snapshot.get('through', ''), 'venues': out, 'filled': filled}


def markdown(report: dict) -> str:
    head = '| 場 | 台数 | ' + ' | '.join(LABELS.values()) + ' |'
    lines = [f"### プレミアムの埋まり具合（{report['through']}まで）", '',
             '数字は評価が付いた号機の数。—は空白、算は公式から算出、独は独自計測。まわり足・立ち上がり・総評は今節の分だけ。', '',
             head, '|' + '---|' * (len(LABELS) + 2)]
    for jcd, row in report['venues'].items():
        cells = []
        for metric in LABELS:
            n, mark = row[metric]['motors'], row[metric]['source']
            cells.append('—' if not n else f'{n}{mark}')
        lines.append(f"| {jcd} {VENUES[jcd]['name']} | {row['motors'] or '—'} | " + ' | '.join(cells) + ' |')
    lines += ['', '埋まっている場：' + '、'.join(f"{LABELS[m]} {n}/24" for m, n in report['filled'].items())]
    return '\n'.join(lines) + '\n'


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('snapshot', nargs='?', type=Path)
    ap.add_argument('--through', help='スナップショットが無いとき、この日までで評価を作って数える')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args(argv)
    if args.snapshot:
        snapshot = json.loads(args.snapshot.read_text(encoding='utf-8'))
    elif args.through:
        from . import motor_generation, premium_motor
        records, history, schedules = premium_motor.load_inputs()
        periods = motor_generation.live_periods(premium_motor.ROOT / 'site' / 'data', args.through)
        snapshot = premium_motor.build(records, history, args.through, schedules, periods['venues'],
                                       None, premium_motor.load_rider_profiles())
        for venue in periods['pending']:
            snapshot['venues'].pop(venue, None)
    else:
        ap.error('スナップショットのファイルか --through を指定してください')
    report = coverage(snapshot)
    sys.stdout.write(json.dumps(report, ensure_ascii=False, indent=1) + '\n' if args.json else markdown(report))


if __name__ == '__main__':
    main()
