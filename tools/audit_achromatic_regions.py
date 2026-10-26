"""Private white/black identity diagnostic; never replaces production candidates."""
import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from tools.boat_tracking import colour_features, identify_colour, temporal_identity
from tools.extract_turn_frames import extract
from tools.frame_binding import require_frame_binding


def region_consensus(helmet, vest, candidate):
    """A partial/contradicting observation stays unknown; no remaining-number rule."""
    if candidate not in (1, 2):
        return None
    return candidate if helmet.get('boat') == vest.get('boat') == candidate else None


def audit_frames(folder, result, model):
    import cv2
    folder = Path(folder)
    manifest = json.loads((folder/'frames.json').read_text(encoding='utf-8'))
    binding = require_frame_binding(manifest, result)
    config = json.loads(Path(model).read_text(encoding='utf-8'))
    claimed = config.pop('fingerprint')
    if hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest() != claimed:
        raise ValueError('colour_model_fingerprint_changed')
    if result['colour_model_fingerprint'] != claimed:
        raise ValueError('different_colour_model')
    output = []
    for event in result['identity_observations']:
        observations = []
        for row in event['observations']:
            candidate = row['identity'].get('boat')
            if candidate not in (1, 2):
                continue
            record = {'frame': row['frame'], 'pts': row['pts'], 'original_boat': candidate,
                      'boat': None, 'reason': 'no_matching_person'}
            region = row.get('rider_region') or {}
            people = []
            for person in row['detections']:
                if person['class'] != 0 or region.get('kind') != 'person':
                    continue
                x,y,w,h = person['box']
                expected = [x+.15*w,y,.7*w,.4*h]
                if max(abs(a-b) for a,b in zip(expected,region['box'])) < 1e-5:
                    people.append(person)
            if len(people) == 1:
                frame = manifest['frames'][row['frame']]
                path = (folder/frame['file']).resolve()
                if (folder.resolve() not in path.parents or frame['pts'] != row['pts']
                        or hashlib.sha256(path.read_bytes()).hexdigest() != frame['sha256']):
                    raise ValueError('source_frame_changed')
                image = cv2.imread(str(path))
                if image is None:
                    raise ValueError('source_image_missing')
                x,y,w,h = people[0]['box']
                # Approximate anatomical regions, not independently labelled anatomy.
                boxes = {'helmet': [x+.15*w,y,.7*w,.35*h],
                         'vest': [x+.1*w,y+.35*h,.8*w,.35*h]}
                identities = {name: identify_colour(colour_features(image,box),config['prototypes'],
                              max_distance=config['max_distance'],min_margin=config['min_margin'],
                              allow_achromatic=True) for name,box in boxes.items()}
                record.update(regions=boxes, region_identities=identities,
                              boat=region_consensus(identities['helmet'],identities['vest'],candidate),
                              reason='regional_agreement' if region_consensus(identities['helmet'],identities['vest'],candidate) else 'regional_disagreement_or_unknown')
            record.update(time=row['pts']*binding['time_base'][0]/binding['time_base'][1], point=row['point'])
            observations.append(record)
        # Unknown evidence must not dilute contradictory/uncertain multi-frame evidence.
        accepted = temporal_identity(observations, min_fraction=1)
        if observations and sum(r['boat'] == accepted for r in observations)/len(observations) < .8:
            accepted = None
        output.append({'gate': event['gate'], 'peak_frame': event['peak_frame'], 'original_event_boat': event.get('boat'),
                       'regional_event_boat': accepted, 'observations': observations})
    return {'frame_binding': binding, 'colour_model_fingerprint': claimed,
            'gate_region_audit': output, 'dataset_role': 'development',
            'region_definitions': 'person-relative helmet top 35%, vest 35-70%; engineering proxies',
            'independent_identity_accuracy_verified': False,
            'publication_ready': False, 'prediction_used': False,
            'changes_existing_candidates': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('video','result','colour_model','output'):
        parser.add_argument('--'+name.replace('_','-'), type=Path, required=True)
    parser.add_argument('--reference-dir', type=Path, help='Optional prior two-review comparison, bound by original PTS and image SHA')
    args = parser.parse_args()
    public = Path(__file__).resolve().parents[1]/'site'
    if args.output.resolve() == public or public in args.output.resolve().parents:
        raise ValueError('private_storage_required')
    data = json.loads(args.result.read_text(encoding='utf-8'))
    if hashlib.sha256(args.video.read_bytes()).hexdigest() != data['source_container_sha256']:
        raise ValueError('source_video_changed')
    reference_inputs = None
    if args.reference_dir:
        manifest_paths = [args.reference_dir/name for name in ('window-frames-manifest.json', 'selected-frames-manifest.json')
                          if (args.reference_dir/name).is_file()]
        if len(manifest_paths) != 1:
            raise ValueError('one_reference_manifest_required')
        reference_inputs = (json.loads((args.reference_dir/'comparison.json').read_text(encoding='utf-8')),
                            json.loads(manifest_paths[0].read_text(encoding='utf-8')))
    probe = subprocess.run([shutil.which('ffprobe'),'-v','error','-protocol_whitelist','file,pipe',
        '-select_streams','v:0','-show_frames','-show_entries','frame=pts:stream=time_base','-of','json',str(args.video)],
        check=True,capture_output=True,text=True,timeout=120)
    meta = json.loads(probe.stdout)
    num,den = map(int,meta['streams'][0]['time_base'].split('/'))
    origin = meta['frames'][0]['pts']*num/den
    # Recreate precisely the original export, then verify every PTS/image fingerprint.
    args.output.parent.mkdir(parents=True,exist_ok=True)
    parent = args.output.parent.resolve()
    with tempfile.TemporaryDirectory(prefix='region-audit-',dir=parent) as temporary:
        temporary = Path(temporary).resolve()
        if parent not in temporary.parents:
            raise ValueError('invalid_temporary_storage')
        folder=temporary/'frames'
        extract(args.video,folder,origin+data['scene_start_relative_seconds'],origin+data['scene_end_relative_seconds'])
        report=audit_frames(folder,data,args.colour_model)
        if args.reference_dir:
            from tools.benchmark_tracked_bows import compare_by_pts_and_sha
            manifest = json.loads((folder/'frames.json').read_text(encoding='utf-8'))
            try:
                report['reference_comparison'] = compare_by_pts_and_sha(manifest, data['learned_bow_review'],
                    *reference_inputs)
                report['reference_comparison']['state'] = 'validated'
            except ValueError as error:
                # Preserve the independently completed region diagnostic, while
                # explicitly refusing unmatched timing-reference evidence.
                report['reference_comparison'] = {
                    'state': 'rejected', 'reason': str(error),
                    'reference_export_encoding': reference_inputs[1]['source'].get('export_encoding'),
                    'reference_source_sha256': reference_inputs[0]['source_sha256'],
                    'current_source_sha256': data['source_container_sha256'],
                    'timing_error_evaluated': False, 'publication_ready': False, 'prediction_used': False}
    args.output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'gate_events':len(report['gate_region_audit']),
                     'accepted_events':sum(r['regional_event_boat'] is not None for r in report['gate_region_audit']),
                     'reference_comparison_state':report.get('reference_comparison',{}).get('state'),
                     'publication_ready':False}))


if __name__ == '__main__':
    main()
