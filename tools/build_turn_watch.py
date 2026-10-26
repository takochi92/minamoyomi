"""Build a private viewing-only page from existing PTS review evidence. No fetch/publish."""
from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import math
import re
from datetime import date
from pathlib import Path

from tools.compare_bow_reviews import compare
from scraper.turn_measurement import digest

ASSETS = Path(__file__).with_name('turn_watch')


def make_bundle(bundle, evidence=None):
    date.fromisoformat(bundle['date'])
    if bundle.get('venue') != 'heiwajima' or type(bundle.get('race')) is not int or not 1 <= bundle['race'] <= 12:
        raise ValueError('unsupported_race')
    if bundle.get('source_clock') != 'decoded_pts':
        raise ValueError('decoded_pts_required')
    source = bundle['source_details']
    base = source['time_base']
    if len(base) != 2 or any(type(v) is not int or v <= 0 for v in base):
        raise ValueError('invalid_time_base')
    anchors = {}
    if evidence:
        manifest, config, reviews = evidence
        if (source['sha256'] != manifest['source']['sha256']
                or base != manifest['source']['time_base']
                or bundle['size'] != manifest['image_size']
                or bundle['gates'] != config['gates']
                or bundle['method'] != config['method']
                or any(bundle[k] != config[k] for k in ('date', 'race', 'venue'))):
            raise ValueError('review_source_or_race_mismatch')
        report = compare(manifest, config, reviews)
        for row in report['results']:
            if row['status'] != 'repeated_ai_video_measurement':
                continue
            frames = {f['index']: f for c in bundle['clips'] if c['boat'] == row['boat'] for f in c['frames']}
            for gate, event in row['events'].items():
                # A matching container alone cannot bind indices from another crop.
                for review in event['reviews']:
                    for frame in review['frames']:
                        if frames.get(frame['index'], {}).get('pts') != frame['pts']:
                            raise ValueError('review_frame_export_mismatch')
                anchors[f'{row["boat"]}:{gate}'] = {
                    'time': event['mean_time'], 'basis': 'two_review_mean',
                    'reviews': report['reviews'], 'source_sha256': source['sha256']}
    clips = []
    seen = set()
    for clip in bundle['clips']:
        boat = clip['boat']
        if type(boat) is not int or not 1 <= boat <= 6 or boat in seen:
            raise ValueError('invalid_boat')
        seen.add(boat)
        frames = []
        for f in clip['frames']:
            if (type(f.get('pts')) is not int or type(f.get('index')) is not int
                    or str(f['index']) not in bundle['images']
                    or not math.isfinite(f['time'])
                    or abs(f['time'] - f['pts'] * base[0] / base[1]) > 1e-7):
                raise ValueError('invalid_frame_pts')
            frames.append({k: f[k] for k in ('index', 'pts', 'time')})
        if not frames or any(not 0 < b['time']-a['time'] <= .12 or b['index'] != a['index']+1
                             for a, b in zip(frames, frames[1:])):
            raise ValueError('missing_or_reversed_frames')
        scenes = {'turn': [f['index'] for f in frames]}
        for gate in 'ABC':
            event = next((e for e in bundle['events'] if e['boat'] == boat and e['gate'] == gate), None)
            scenes[gate] = [f['index'] for f in event['frames']] if event else []
            if any(i not in scenes['turn'] for i in scenes[gate]):
                raise ValueError('scene_outside_clip')
        clips.append({'boat': boat, 'frames': frames, 'scenes': scenes})
    return {'schema': 1, 'kind': 'turn-watch', 'date': bundle['date'], 'race': bundle['race'],
            'venue': bundle['venue'], 'size': bundle['size'], 'gates': bundle['gates'],
            'source': {'sha256': source['sha256'], 'time_base': base, 'clock': 'decoded_pts'},
            'clips': clips, 'anchors': anchors, 'images': {},
            'publication_ready': False, 'prediction_used': False}


def build(source, destination, evidence_dir=None):
    source, destination = Path(source), Path(destination)
    text = source.read_text(encoding='utf-8')
    marker = re.search(r'<script type="application/json" id="bundle">(.*?)</script>', text, re.S)
    if not marker:
        raise ValueError('review_bundle_missing')
    original = json.loads(marker[1])
    evidence = None
    if evidence_dir:
        directory = Path(evidence_dir)
        load = lambda name: json.loads((directory/name).read_text(encoding='utf-8'))
        evidence = (load('window-frames-manifest.json'), load('config.json'),
                    [load('review-1.json'), load('review-2.json')])
    bundle = make_bundle(original, evidence)
    media = {}
    for key in {str(f['index']) for c in bundle['clips'] for f in c['frames']}:
        value = original['images'][key]
        if value.startswith('data:image/webp;base64,'):
            data = base64.b64decode(value.split(',', 1)[1], validate=True)
        else:
            if not re.fullmatch(r'frames/[a-f0-9]{64}\.webp', value):
                raise ValueError('local_webp_required')
            path = (source.parent/value).resolve()
            if source.parent.resolve() not in path.parents:
                raise ValueError('invalid_frame_path')
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != path.stem:
                raise ValueError('frame_fingerprint_changed')
        if not 12 <= len(data) < 25*1024*1024 or data[:4] != b'RIFF' or data[8:12] != b'WEBP':
            raise ValueError('invalid_webp')
        embedded = 'data:image/webp;base64,' + base64.b64encode(data).decode()
        if digest(embedded) != original.get('image_digests', {}).get(key):
            raise ValueError('review_image_fingerprint_changed')
        name = hashlib.sha256(data).hexdigest()+'.webp'
        media[name] = data
        bundle['images'][key] = 'frames/'+name
    payload = json.dumps(bundle, ensure_ascii=False, allow_nan=False).replace('<', '\\u003c')
    page = (ASSETS/'watch.html').read_text(encoding='utf-8')
    page = page.replace('__LABEL__', html.escape(f"平和島 {bundle['date']} {bundle['race']}R"))
    page = page.replace('__BUNDLE__', payload)
    destination.mkdir(parents=True, exist_ok=False)
    (destination/'frames').mkdir()
    for name, data in media.items():
        (destination/'frames'/name).write_bytes(data)
    for name in ('watch.js', 'watch.css'):
        (destination/name).write_bytes((ASSETS/name).read_bytes())
    (destination/'index.html').write_text(page, encoding='utf-8')
    return {'images': len(media), 'anchors': len(bundle['anchors']),
            'html_bytes': len(page.encode()), 'external_publication_performed': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--evidence-dir', type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.destination, args.evidence_dir)))
