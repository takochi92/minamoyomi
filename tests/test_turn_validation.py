import copy

import pytest

from tools.validate_turn_measurements import crossing_sensitivity, audit


def test_position_uncertainty_can_invalidate_an_apparently_clean_crossing():
    gate = {'axis': 'x', 'direction': 1, 'value': 10, 'segment': [0, 100]}
    a, b = {'x': 9, 'y': 50, 'time': 1}, {'x': 12, 'y': 50, 'time': 1.05}
    assert crossing_sensitivity(a, b, gate)['reason'] == 'position_error_can_change_bracketing'
    assert crossing_sensitivity(a, b, gate, 0)['time'] == pytest.approx(1+1/60)


def test_directed_interval_bound_and_segment_are_checked():
    gate = {'axis': 'y', 'direction': -1, 'value': 10, 'segment': [0, 100]}
    a, b = {'x': 50, 'y': 20, 'time': 1}, {'x': 50, 'y': 0, 'time': 1.1}
    r = crossing_sensitivity(a, b, gate, 2)
    assert r['time'] == pytest.approx(1.05)
    assert r['low'] < r['time'] < r['high']
    assert crossing_sensitivity(a, {**b, 'time': 1.3}, gate)['reason'] == 'frame_interval'
    assert crossing_sensitivity({**a, 'x': 0}, b, gate)['reason'] == 'position_error_can_leave_gate'
    with pytest.raises(ValueError): crossing_sensitivity(a, b, gate, float('nan'))


def test_a_second_self_review_and_repeated_race_cannot_fill_validation_counts():
    manifest = {'source': {'time_base': [1, 30], 'clock': 'decoded_pts', 'sha256': 'a'*64},
                'frames': [{'pts': i, 'sha256': str(i)} for i in range(6)]}
    original = copy.deepcopy(manifest)
    config = {'gates': {g: {'axis': 'x', 'value': 10, 'direction': 1, 'segment': [0, 100]} for g in 'ABC'}}
    result = audit(manifest, {'labels': {}, 'pairs': {}}, config,
                   independent_reviews=[{'reviewer_id': 'same-assistant', 'all_hull_points_checked': True,
                                         'evidence_sha256': 'a'*64}]*2,
                   heldout_results=[{'race_id': 'same', 'date': '20261026', 'unused_for_tuning': True}]*30)
    assert result['independent_reviews'] == 0 and result['heldout_races'] == 1
    assert not result['publication_ready'] and not result['prediction_used']
    assert 'real_time_scale_not_verified' in result['blockers']
    assert manifest == original


def test_audit_is_not_an_independent_authority_to_publish_even_with_complete_inputs():
    manifest = {'source': {'time_base': [1, 30], 'clock': 'decoded_pts', 'sha256': 'a'*64},
                'frames': [{'pts': i, 'sha256': str(i)} for i in range(6)]}
    config = {'gates': {g: {'axis': 'x', 'value': 15, 'direction': 1, 'segment': [0, 100]} for g in 'ABC'}}
    labels, pairs = {}, {}
    for boat in range(1, 7):
        for i in range(6):
            x = 0 if i % 2 == 0 else 20
            labels[f'{boat}:{i}'] = {'bow': [x, 50], 'stern': [x+10, 50]}
        for i, gate in enumerate('ABC'):
            pairs[f'{boat}:{gate}'] = {'before': i*2, 'after': i*2+1}
    out = audit(manifest, {'labels': labels, 'pairs': pairs}, config, point_error_px=0,
                independent_reviews=[{'reviewer_id': name, 'all_hull_points_checked': True,
                                      'independence_verified': True, 'evidence_sha256': 'a'*64} for name in ('a', 'b')],
                heldout_results=[{'race_id': str(i), 'date': str(i%3), 'unused_for_tuning': True} for i in range(20)],
                editing_speed_evidence={'verified': True})
    assert out['blockers'] == [] and out['independent_reviews'] == 2
    assert not out['publication_ready']
    reversed_pairs = copy.deepcopy(pairs)
    reversed_pairs['1:A'], reversed_pairs['1:C'] = reversed_pairs['1:C'], reversed_pairs['1:A']
    invalid = audit(manifest, {'labels': labels, 'pairs': reversed_pairs}, config, point_error_px=0)
    assert 'invalid_A_B_C_order' in invalid['rows'][0]['reasons']
    assert 'entry' not in invalid['rows'][0] and 'exit' not in invalid['rows'][0]
