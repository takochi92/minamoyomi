"""Repeat frozen development races from local originals; never a holdout benchmark."""
import argparse
import hashlib
import json
from pathlib import Path
from tools.automatic_turn_v2 import analyze_video


def fingerprint(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def summarize(result):
    learned = result.get('learned_bow_review', {})
    tracks = result.get('continuous_actor_review', {})
    return {
        'source_container_sha256': result['source_container_sha256'],
        'frame_binding': result['frame_binding'],
        'total_elapsed_seconds': result['total_elapsed_seconds'],
        'stage_elapsed_seconds': result['stage_elapsed_seconds'],
        'coarse_candidates': sum(r['status'] == 'automatic_candidate' for r in result['results']),
        'learned_results': [{k: row.get(k) for k in ('boat', 'status', 'reasons',
                            'entry_video_seconds', 'exit_video_seconds')}
                            for row in learned.get('results', [])],
        'tracking_diagnostics': [{k: r.get(k) for k in
            ('boat', 'state', 'seed_attempts', 'entry_connected_seed_count',
             'excluded_disconnected_seeds', 'seed_stop_diagnostics')}
            for r in tracks.get('tracks', [])],
        'denominator': 6, 'dataset_role': 'development',
        'independent_identity_accuracy_verified': False,
        'real_time_scale_verified': False, 'publication_ready': False, 'prediction_used': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--media-root', type=Path, required=True)
    parser.add_argument('--models', type=Path, required=True)
    parser.add_argument('--scene-model', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    if root/'site' == output or root/'site' in output.parents:
        raise ValueError('private_storage_required')
    paths = {'detector_path': args.models/'yolox-s.onnx', 'colour_model': args.models/'colour-v2.json',
             'bow_model': args.models/'bow-v2.npz', 'scene_model': args.scene_model,
             'keypoint_weights': args.models/'bow-heatmap-bound-v1.pt'}
    settings = {'dataset_role': 'development', 'races': [3, 5],
                'model_sha256': {k: fingerprint(v) for k,v in paths.items()},
                'code_sha256': {str(p.relative_to(root)).replace('\\','/'): fingerprint(p)
                               for p in [*sorted((root/'tools').glob('*.py')),
                                         root/'scraper/exhibition_model/pilot-v1.json', root/'scraper/turn_measurement.py']},
                'publication_ready': False, 'prediction_used': False}
    output.mkdir(parents=True, exist_ok=False)
    (output/'settings.json').write_text(json.dumps(settings, indent=2), encoding='utf-8')
    for race in settings['races']:
        print(f'Starting development race {race}; all six boats, original video', flush=True)
        result = analyze_video(args.media_root/f'{race:02}'/'replay.ts', output/'temp', **paths)
        (output/f'{race:02}-private-result.json').write_text(json.dumps(result), encoding='utf-8')
        summary = summarize(result)
        (output/f'{race:02}-summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
        print(json.dumps({'race': race, 'elapsed': result['total_elapsed_seconds'],
                          'stages': result['stage_elapsed_seconds'],
                          'learned_result_keys': list(result.get('learned_bow_review', {}))}), flush=True)


if __name__ == '__main__':
    main()
