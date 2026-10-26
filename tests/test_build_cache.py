import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scraper.build_cache import BuildCache, safe_path


def site(root):
    return SimpleNamespace(output_root=root, files={}, bins={}, _streamed=set(), racers={})


def test_generated_cache_preserves_all_kinds_and_rebuilds_changed_inputs(tmp_path):
    directory = tmp_path / 'cache'
    first = site(tmp_path / 'first')
    first.output_root.mkdir()
    calls = []

    def produce():
        calls.append(1)
        first.files['race/past.html'] = 'fixed past prediction'
        first.files['racer/1.html'] = ''
        first._streamed.add('racer/1.html')
        p = first.output_root / 'racer/1.html'
        p.parent.mkdir(exist_ok=True)
        p.write_text('player history', encoding='utf-8')
        first.bins['img/test.svg'] = b'<svg/>'
        first.racers = {'1': {'name': 'test'}}

    cache = BuildCache(directory, 'sources-1')
    cache.phase(first, 'players', ['today'], produce, racer=True)
    restored = site(tmp_path / 'restored')
    warm = BuildCache(directory, 'sources-1')
    warm.phase(restored, 'players', ['today'], lambda: pytest.fail('must reuse'), racer=True)
    assert warm.hits == 1 and not warm.changed
    assert restored.files == first.files and restored.bins == first.bins
    assert restored.racers == first.racers
    assert (restored.output_root / 'racer/1.html').read_text() == 'player history'
    assert restored._streamed == {'racer/1.html'}
    changed = BuildCache(directory, 'sources-2')
    changed.phase(site(tmp_path / 'new'), 'players', ['today'], lambda: calls.append(2))
    assert calls == [1, 2] and changed.misses == 1


def test_missing_or_corrupt_public_archive_is_rebuilt_not_partially_restored(tmp_path):
    original = site(tmp_path / 'out')
    p = original.output_root / 'data/players/1.json'
    p.parent.mkdir(parents=True)
    p.write_text('[1,2]', encoding='utf-8')
    cache = BuildCache(tmp_path / 'cache', 'source')
    cache.phase(original, 'archive', [], lambda: ['data/players/1.json'], archive=True)
    cached = tmp_path / 'cache/archive/files/data/players/1.json'
    cached.write_text('[9,9]', encoding='utf-8')  # Same length; checksum must catch it.
    target = site(tmp_path / 'target')
    calls = []
    def rebuild():
        assert not (target.output_root / 'data/players/1.json').exists()
        calls.append(1)
    cache.phase(target, 'archive', [], rebuild, archive=True)
    assert calls == [1]


def test_phase_context_change_invalidates_today_programmes(tmp_path):
    cache = BuildCache(tmp_path / 'cache', 'same-model')
    cache.phase(site(tmp_path / 'a'), 'players', ['20261026', '09:00', 'player-a'], lambda: None)
    calls = []
    cache.phase(site(tmp_path / 'b'), 'players', ['20261026', '09:05', 'player-b'], lambda: calls.append(1))
    assert calls == [1]


@pytest.mark.parametrize('path', ['../outside', '/absolute', 'C:/outside', 'a\\outside', '.'])
def test_cache_paths_cannot_escape(path):
    with pytest.raises(ValueError):
        safe_path(path)


def test_past_day_cache_keeps_day_results_and_current_day_is_always_rendered(tmp_path, monkeypatch):
    from scraper import sitegen
    data = tmp_path / 'data'
    for day in ('20261025', '20261026'):
        p = data / 'races' / day / '0101.json'
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps({'date': day, 'jcd': '01', 'rno': 1,
                                 'racelist': {'boats': [1]}, 'prediction': {'version': 31}}))
    monkeypatch.setattr(sitegen, 'DATA', data)
    from datetime import datetime
    def make():
        s = sitegen.Site.__new__(sitegen.Site)
        s.now = datetime(2026, 10, 26, 10, tzinfo=sitegen.JST)
        s.idx = {'date': '20261026', 'venues': []}
        s.output_root = tmp_path / 'output'
        s.files = {}; s.bins = {}; s._streamed = set()
        s.build_cache = BuildCache(tmp_path / 'cache', 'same-source')
        s.race_page = lambda d, j, r: s.put(f'race/{d}/1.html', json.dumps(r['prediction']))
        return s
    first = make(); first.races()
    second = make(); seen = []
    second.race_page = lambda d, j, r: (seen.append(d), second.put(f'race/{d}/1.html', json.dumps(r['prediction'])))
    second.races()
    assert seen == ['20261026']
    assert second.files == first.files and second.day_races == first.day_races
    p = data / 'races/20261025/0101.json'
    r = json.loads(p.read_text()); r['prediction']['version'] = 32
    p.write_text(json.dumps(r))
    third = make(); third.races()
    assert '32' in third.files['race/20261025/1.html']


def test_sparse_archive_can_be_hydrated_and_source_key_covers_unfetched_files(tmp_path, monkeypatch):
    import subprocess
    from scraper.build_cache import hydrate, source_revision
    repo = tmp_path / 'repository'; repo.mkdir()
    def git(*args, **kwargs):
        return subprocess.run(['git', *args], cwd=repo, check=True, capture_output=True, **kwargs)
    git('init')
    for name in ('scraper/sitegen.py', 'scraper/database/player_history/1.json.gz',
                 'scraper/database/races/202610.jsonl.gz', 'history/202610.jsonl.gz'):
        p = repo / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text('source-' + name)
    git('add', '.')
    git('-c', 'user.name=Test', '-c', 'user.email=test@example.test', 'commit', '-m', 'fixture')
    before = source_revision(repo)
    git('sparse-checkout', 'set', '--no-cone', '--stdin',
        input=b'/*\n!/scraper/database/player_history/\n!/scraper/database/races/\n')
    assert not (repo / 'scraper/database/player_history/1.json.gz').exists()
    assert source_revision(repo) == before
    monkeypatch.setenv('SITEGEN_SPARSE', '1')
    hydrate(repo, 'scraper/database/player_history', 'scraper/database/races')
    assert (repo / 'scraper/database/player_history/1.json.gz').exists()
    assert source_revision(repo) == before
    (repo / 'scraper/sitegen.py').write_text('changed')
    assert source_revision(repo) != before
