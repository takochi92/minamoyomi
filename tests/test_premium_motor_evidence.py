import unittest

from scraper.premium_motor_evidence import backfill, estimate, meetings, rider_correction, rider_reference


class MotorEvidenceTest(unittest.TestCase):
    def test_same_title_is_split_using_official_dates(self):
        rows = [('20261002', 'cup', ()), ('20261004', 'cup', ())]
        dates = {'cup': {'20261001': '20261002', '20261003': '20261005'}}
        actual = meetings(rows, '20261004', '', dates)
        self.assertEqual([start for _, start, _ in actual], ['20261001', '20261003'])

    def test_reference_ignores_current_meet_and_target_motor(self):
        rows = [
            ('20261001', 'first', (('turn', '12', '1000', .2),) * 2),
            ('20261004', 'second', (('turn', '13', '1000', .2),) * 2),
            ('20261007', 'third', (('turn', '14', '1000', .2),) * 2),
            ('20261010', 'ongoing', (('turn', '15', '1000', 2),) * 2),
        ]
        schedule = {'ongoing': {'20261010': '20261012'}}
        reference = rider_reference({'01': rows}, {'01': schedule}, '20261010')
        self.assertIsNone(rider_correction(reference, '01', 'turn', '12', '1000'))
        self.assertAlmostEqual(rider_correction(reference, '01', 'turn', '99', '1000'), .6 / 7)

    def test_motor_history_respects_generation_and_uses_latest_three_meetings(self):
        motors = ('12', '13', '14')
        def race(title, dates, rider):
            for date in dates:
                yield date, title, tuple(('turn', motor, rider, .1) for motor in motors)
        rows = [
            *race('retired fleet', ['20260927', '20260928', '20260929'], '9000'),
            *race('one', ['20261001', '20261002', '20261003'], '1000'),
            *race('two', ['20261006', '20261007', '20261008'], '2000'),
            *race('three', ['20261011', '20261012', '20261013'], '3000'),
            *race('four', ['20261016', '20261017', '20261018'], '4000'),
        ]
        history = {'01': {'12': {'history_boundary': '20261001', 'history_boundary_source': 'official_confirmed'}}}
        early = estimate({'01': rows}, history, {}, '20261003')
        self.assertEqual(early, {'01': {}})
        latest = estimate({'01': rows}, history, {}, '20261018')['01']['turn']['12']
        self.assertEqual(latest['meeting_starts'], ['20261006', '20261011', '20261016'])
        self.assertEqual(latest['motor_generation_start'], '20261001')
        self.assertEqual(latest['riders'], ['2000', '3000', '4000'])
        self.assertEqual(latest['raw'][0]['runs'], 9)
        self.assertEqual(backfill(estimate({'01': rows}, history, {}, '20261018'), '20261018')['venues'], {})


if __name__ == '__main__':
    unittest.main()