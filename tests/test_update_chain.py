from datetime import datetime, timezone

from tools.update_chain import decide, operating, parse

NOW = parse('2026-11-16T05:00:00Z')


def run(id, status, created):
    return {'id': id, 'status': status, 'created_at': created}


def test_operating_hours_match_the_external_watchdog():
    assert operating(datetime(2026, 11, 16, 5, 0, tzinfo=timezone.utc))        # 14:00 JST
    assert operating(datetime(2026, 11, 16, 16, 30, tzinfo=timezone.utc))      # 1:30 JST
    assert not operating(datetime(2026, 11, 16, 18, 0, tzinfo=timezone.utc))   # 3:00 JST
    assert not operating(datetime(2026, 11, 16, 14, 0, tzinfo=timezone.utc))   # 23:00 JST


def test_dispatch_when_nothing_else_is_waiting():
    runs = [run(2, 'in_progress', '2026-11-16T04:55:00Z'), run(1, 'completed', '2026-11-16T04:50:00Z')]
    assert decide(runs, '2', NOW) == ('dispatch', [])


def test_never_double_dispatch():
    # 外の監視がもう起動した（待ち・実行中・直前の起動）
    assert decide([run(3, 'queued', '2026-11-16T04:59:00Z')], '2', NOW)[0] == 'skip-busy'
    assert decide([run(3, 'in_progress', '2026-11-16T04:30:00Z')], '2', NOW)[0] == 'skip-busy'
    assert decide([run(3, 'completed', '2026-11-16T04:57:00Z')], '2', NOW)[0] == 'skip-recent'


def test_ghost_runs_are_cancelled_and_do_not_block():
    # 2026-11-16 #10473：ジョブ0件のまま queued で残った
    runs = [run(10473, 'queued', '2026-11-16T03:41:36Z'), run(1, 'completed', '2026-11-16T04:50:00Z')]
    assert decide(runs, '2', NOW) == ('dispatch', [10473])
    # 10〜30分始まらない待ちは、まだ消さないが、起動は止めない
    assert decide([run(9, 'pending', '2026-11-16T04:40:00Z')], '2', NOW) == ('dispatch', [])
