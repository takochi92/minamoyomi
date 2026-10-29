"""Display-only finals labels, matched to the motor actually used in a race.

No R-number inference and no prediction inputs. Read saved official results;
do not fetch official web pages as part of the five-minute update.
"""
from __future__ import annotations

import gzip
import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path


def norm(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(value or '')))


def individual_final(name, title='', jcd=''):
    label = re.sub(r'\d{3,4}m$', '', norm(name))
    label = re.sub(r'進入固定$', '', label).rstrip('☆★')
    if re.fullmatch(r'(?:[A-Z0-9]+|[A-Z]戦)?優勝戦', label):
        return True
    title = norm(title)
    # This event has individual and team titles. The winning boat here is
    # the individual winner; never infer the winning TEAM from first place.
    if label == '団体・優勝戦':
        return 'レディース' in title and 'ルーキーズ' in title
    if label in ('賞金女王決定', '賞金女王決定戦'):
        return 'クイーンズクライマックス' in title
    if label == '決勝戦':
        return 'BBCトーナメント' in title
    if label == 'ファイナル':
        return '3Days' in title and 'バトルトーナメント' in title
    if label == '王将位決定戦':
        return jcd == '12' and '全大阪王将戦' in title
    # Official, abbreviated programme names. Require venue/event context.
    if jcd == '09' and label in ('ツッキー優勝', 'ツッピー優勝'):
        return 'W優勝戦' in title
    return jcd == '20' and label == '県内選手権優' and '福岡県内選手権' in title


def place(value):
    text = str(value).strip()
    return int(text) if text.isdigit() else text


def participants(entries):
    out = {}
    for entry in entries:
        if len(entry) <= 8 or entry[2] not in range(1, 7) or entry[8] is None:
            continue
        result = place(entry[5])
        if result in ('K0', 'K1', '欠', '欠場'):
            continue
        out[(int(entry[0]), str(entry[1]), str(entry[8]))] = result
    return out


@lru_cache(maxsize=4)
def archive_index(signatures):
    finals, known = {}, set()
    for name, _mtime, _size in signatures:
        try:
            with gzip.open(name, 'rt', encoding='utf-8') as source:
                for line in source:
                    row = json.loads(line)
                    if len(row) <= 12 or not isinstance(row[12], dict):
                        continue
                    meta = row[12]
                    if not meta.get('race_name'):
                        continue
                    key = (row[0], str(row[1]), int(row[2]))
                    known.add(key)
                    if individual_final(meta['race_name'], meta.get('title'), key[1]):
                        finals[key] = participants(row[11])
        except (OSError, EOFError, ValueError, TypeError):
            continue
    return finals, known


class MotorFinals:
    def __init__(self, finals=None, known=()):
        self.finals = dict(finals or {})
        self.known = set(known)

    @classmethod
    def load(cls, root, data, start, through):
        signatures = []
        for path in sorted((Path(root) / 'scraper/database/races').glob('*.jsonl.gz')):
            if start[:6] <= path.name[:6] <= through[:6]:
                stat = path.stat()
                signatures.append((str(path), stat.st_mtime_ns, stat.st_size))
        finals, known = archive_index(tuple(signatures))
        index = cls(finals, known)
        # Recent saved HTML-derived results provide names before the monthly
        # official archive catches up. Only finished results are eligible.
        for folder in sorted((Path(data) / 'races').glob('*')):
            if not folder.is_dir() or not start <= folder.name <= through:
                continue
            for path in folder.glob('*.json'):
                try:
                    race = json.loads(path.read_text(encoding='utf-8'))
                    result = race.get('result') or {}
                    if not result.get('finished'):
                        continue
                    rl = race.get('racelist') or {}
                    name = race.get('race_name') or rl.get('race_name')
                    if not name:
                        continue
                    key = (race['date'], str(race['jcd']), int(race['rno']))
                    index.known.add(key)
                    if not individual_final(name, rl.get('title'), key[1]):
                        index.finals.pop(key, None)
                        continue
                    starts = {int(e['frame']): e.get('course') for e in result.get('start', [])}
                    order = {int(e['frame']): e['place'] for e in result.get('order', [])}
                    entries = [[b['frame'], b.get('toban', ''), starts.get(b['frame']),
                                None, '', order.get(b['frame']), None, None, b.get('motor_no')]
                               for b in rl.get('boats', []) if b['frame'] in order]
                    index.finals[key] = participants(entries)
                except (OSError, ValueError, KeyError, TypeError):
                    continue
        return index

    def award(self, jcd, motor_no, row):
        entries = self.finals.get((row['date'], str(jcd), int(row['rno'])), {})
        result = entries.get((int(row['frame']), str(row['toban']), str(motor_no)))
        stored = place(row['place'])
        if result is None or stored in ('K0', 'K1', '欠', '欠場'):
            return ''
        # A victory requires matching first place in both official sources.
        # Incident spellings can differ (e.g. K-file S0 versus HTML 転),
        # but do not change this matched boat's participation in the final.
        if result == 1 or stored == 1:
            return 'champion' if result == stored == 1 else ''
        return 'finalist'

    def period_award(self, jcd, motor_no, rows):
        awards = {self.award(jcd, motor_no, row) for row in rows}
        return 'champion' if 'champion' in awards else 'finalist' if 'finalist' in awards else ''


def for_site(site, root, data, motors):
    if not hasattr(site, '_motor_finals'):
        first = [m['history_first'] for ms in motors.values() for m in ms.values() if m.get('history_first')]
        last = [m['history_as_of'] for ms in motors.values() for m in ms.values() if m.get('history_as_of')]
        if first and last:
            from .build_cache import hydrate
            hydrate(root, 'scraper/database/races')
            site._motor_finals = MotorFinals.load(root, data, min(first), max(last))
        else:
            site._motor_finals = MotorFinals()
    return site._motor_finals
