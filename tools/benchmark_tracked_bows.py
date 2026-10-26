"""Compare frozen proposals with existing AI reviews without selecting by accuracy."""
import argparse,hashlib,json,math
from pathlib import Path
from tools.frame_binding import require_frame_binding


def compare(manifest,automatic,reference,selected):
    binding=require_frame_binding(manifest,automatic)
    if (reference['source_sha256']!=binding['source_sha256'] or selected['source']['sha256']!=binding['source_sha256']
            or selected['source']['time_base']!=binding['time_base']):raise ValueError('reference_source_mismatch')
    for index,row in selected['frames'].items():
        actual=manifest['frames'][int(index)]
        if any(actual[key]!=row[key] for key in ('pts','sha256')):raise ValueError('reference_export_mismatch')
    refs={r['boat']:r for r in reference['results']};rows=[];errors=[]
    for boat in range(1,7):
        matches=[r for r in automatic['results'] if r['boat']==boat]
        if len(matches)!=1:raise ValueError('six_unique_result_slots_required')
        result=matches[0];events={}
        for gate in 'ABC':
            event=result['events'].get(gate)
            if event is None:continue
            target=refs[boat]['events'][gate]['mean_time'];error=event['time']-target
            if not math.isfinite(error):raise ValueError('nonfinite_event')
            events[gate]={'candidate_time':event['time'],'reference_ai_mean_time':target,'signed_error_seconds':error}
            errors.append(abs(error))
        row={'boat':boat,'status':result['status'],'reasons':result['reasons'],'gate_errors':events}
        if result['status']=='automatic_candidate':
            if set(events)!=set('ABC'):raise ValueError('incomplete_accepted_candidate')
            ref=refs[boat]['events']
            row['entry_error_seconds']=result['entry_video_seconds']-(ref['B']['mean_time']-ref['A']['mean_time'])
            row['exit_error_seconds']=result['exit_video_seconds']-(ref['C']['mean_time']-ref['B']['mean_time'])
        rows.append(row)
    return {'scope':'development_comparison_to_prior_two_AI_reviews_not_real_world_accuracy',
            'frame_binding':binding,'boats_total':6,'complete_candidates':sum(r['status']=='automatic_candidate' for r in rows),
            'detected_gates':len(errors),'expected_gates':18,'max_gate_error_seconds':max(errors) if errors else None,
            'results':rows,'publication_ready':False,'prediction_used':False,'heldout':False,
            'reference_reviews_are_not_ground_truth':True}


def compare_by_pts_and_sha(manifest, automatic, reference, selected):
    """Explicitly rebind review frames from a different crop using exact PTS+SHA.

    Never reuse another export's frame index, shift by a guessed offset, or match
    on container alone. Every selected source image must exist unchanged.
    """
    require_frame_binding(manifest, automatic)
    actual = {row['pts']: (index, row) for index, row in enumerate(manifest['frames'])}
    rebound, mapping = {}, []
    for old_index, row in selected['frames'].items():
        matched = actual.get(row['pts'])
        if matched is None or matched[1]['sha256'] != row['sha256']:
            raise ValueError('reference_pts_or_image_mismatch')
        index, _ = matched
        rebound[str(index)] = row
        mapping.append({'review_index': int(old_index), 'current_index': index,
                        'pts': row['pts'], 'sha256': row['sha256']})
    result = compare(manifest, automatic, reference, {**selected, 'frames': rebound})
    result['review_frame_mapping'] = mapping
    result['mapping_basis'] = 'exact_original_pts_and_image_sha256_not_index_reuse'
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('manifest','automatic','reference','selected','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    inputs=[json.loads(getattr(args,name).read_text(encoding='utf-8')) for name in ('manifest','automatic','reference','selected')]
    result=compare(*inputs)
    result['input_sha256']={name:hashlib.sha256(getattr(args,name).read_bytes()).hexdigest() for name in ('automatic','reference','selected')}
    args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('results','frame_binding','input_sha256')}))
