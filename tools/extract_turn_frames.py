"""Extract real presentation timestamps from a LOCAL video, with no resampling.

No remote protocols, inferred constant FPS, or network downloader. The clock is
the input video's clock; origin, editing speed and race identity remain separate
checks. In particular a generated slow demo is not an original racing record.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path


def extract(video, output, start, end):
    video, output = Path(video).resolve(), Path(output).resolve()
    if not video.is_file() or video.suffix.lower() not in {'.mp4', '.mkv', '.mov', '.webm', '.avi', '.ts', '.m4v'}:
        raise ValueError('A local video container is required')
    if not all(math.isfinite(v) for v in (start, end)) or not 0 <= start < end or end-start > 45:
        raise ValueError('Select a finite interval of at most 45 seconds')
    ffmpeg, ffprobe = shutil.which('ffmpeg'), shutil.which('ffprobe')
    if not ffmpeg or not ffprobe:
        raise RuntimeError('ffmpeg and ffprobe are required for offline measurement')
    # Decode timestamps in display order. Do not derive time from frame count.
    command = [ffprobe, '-v', 'error', '-protocol_whitelist', 'file,pipe', '-select_streams', 'v:0',
               '-show_streams', '-show_frames', '-show_entries', 'stream=time_base,width,height:frame=pts,width,height',
               '-of', 'json', str(video)]
    result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=120)
    data = json.loads(result.stdout)
    stream = data['streams'][0]
    base = Fraction(stream['time_base'])
    size = [stream['width'], stream['height']]
    frames = []
    previous = None
    for frame in data['frames']:
        pts = frame.get('pts')
        if type(pts) is not int:
            raise ValueError('Missing decoded frame PTS')
        if previous is not None and pts <= previous:
            raise ValueError('Repeated or reversed decoded PTS')
        previous = pts
        timestamp = float(pts * base)
        if start <= timestamp < end:
            if [frame['width'], frame['height']] != size:
                raise ValueError('Video dimensions changed')
            frames.append({'id': str(len(frames)), 'file': f'frame-{len(frames):06}.png', 'pts': pts})
    if not frames or len(frames) > 2700:
        raise ValueError('Empty interval or excessive frame count')
    hasher = hashlib.sha256()
    with video.open('rb') as source:
        for chunk in iter(lambda: source.read(1024*1024), b''):
            hasher.update(chunk)
    output.mkdir(parents=True, exist_ok=False)
    # -copyts preserves the original time origin. select drops only frames
    # outside the requested interval; passthrough does not invent held frames.
    command = [ffmpeg, '-v', 'error', '-nostdin', '-protocol_whitelist', 'file,pipe', '-copyts', '-i', str(video),
               '-map', '0:v:0', '-an', '-vf', f'select=gte(t\\,{start})*lt(t\\,{end})',
               '-fps_mode', 'passthrough', '-threads', '2', '-start_number', '0', str(output/'frame-%06d.png')]
    subprocess.run(command, capture_output=True, text=True, check=True, timeout=180)
    if len(list(output.glob('frame-*.png'))) != len(frames):
        raise ValueError('Decoded images do not match the timestamp sequence')
    for frame in frames:
        frame['sha256'] = hashlib.sha256((output/frame['file']).read_bytes()).hexdigest()
    manifest = {'schema': 2, 'image_size': size, 'source': {
        'clock': 'decoded_pts', 'sha256': hasher.hexdigest(), 'filename': video.name,
        'time_base': [base.numerator, base.denominator], 'origin_verified': False,
        'editing_speed_verified': False}, 'frames': frames, 'publication_ready': False}
    (output/'frames.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--start', type=float, required=True)
    parser.add_argument('--end', type=float, required=True)
    args = parser.parse_args()
    result = extract(args.video, args.output, args.start, args.end)
    print(json.dumps({'frames': len(result['frames']), 'clock': result['source']['clock'], 'publication_ready': False}))


if __name__ == '__main__':
    main()
