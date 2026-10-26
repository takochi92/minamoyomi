"""Disposable cache of generated PUBLIC files; never a prediction input.

Git blob IDs cover even sparse, unhydrated archive inputs. Daily race inputs
are hashed separately. A missing/incomplete entry always rebuilds from source.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import time

VERSION = 'public-build-v1'


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                   separators=(',', ':')).encode()).hexdigest()


def source_revision(root):
    root = Path(root)
    # No credentials/configuration from .git are saved in the cache.
    paths = ['scraper', 'history', 'site', 'requirements.txt']
    raw = subprocess.check_output(['git', 'ls-tree', '-rz', 'HEAD', '--', *paths], cwd=root)
    entries = {}
    for row in raw.split(b'\0'):
        if not row:
            continue
        info, name = row.split(b'\t', 1)
        name = name.decode()
        if name.startswith('site/data/'):
            continue
        entries[name] = info.decode().split()[2]
    # Also respect local edits when benchmarking/testing before a commit.
    dirty = subprocess.check_output(['git', 'diff', 'HEAD', '--name-only', '-z', '--', *paths], cwd=root)
    added = subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard', '-z', '--', *paths], cwd=root)
    for name in (dirty + added).decode().split('\0'):
        if not name or name.startswith('site/data/'):
            continue
        p = root / name
        entries[name] = hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else 'deleted'
    return digest(entries)


def hydrate(root, *folders):
    if os.environ.get('SITEGEN_SPARSE') == '1':
        subprocess.run(['git', 'sparse-checkout', 'add', *('/' + x + '/' for x in folders)],
                       cwd=root, check=True)


def safe_path(name):
    p = PurePosixPath(name)
    if p.is_absolute() or '..' in p.parts or '\\' in name or ':' in name or not p.parts:
        raise ValueError('Invalid generated cache path')
    return name


def restore_file(source, target):
    """Generated restored outputs are read-only for the remainder of this build.

    Hard links avoid copying gigabytes of unchanged public JSON. Publishing
    only reads these files. A different filesystem falls back to a normal copy.
    Replace the target atomically; never truncate another link to cache data.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + '.build-cache-tmp')
    temporary.unlink(missing_ok=True)
    try:
        os.link(source, temporary)
    except OSError:
        shutil.copyfile(source, temporary)
    temporary.replace(target)


class BuildCache:
    def __init__(self, directory, revision):
        self.directory = Path(directory)
        self.revision = revision
        self.changed = False
        self.hits = self.misses = 0
        self.used = set()

    def phase(self, site, name, extra, produce, *, archive=False, racer=False):
        key = digest([VERSION, self.revision, extra])
        self.used.add(name)
        folder = self.directory / safe_path(name)
        if folder.resolve() == self.directory.resolve() or not folder.resolve().is_relative_to(self.directory.resolve()):
            raise ValueError('Cache entry escaped cache directory')
        manifest_path = folder / 'manifest.json'
        started = time.monotonic()
        before = set(site.files)
        binaries = dict(site.bins)
        streamed = set(site._streamed)
        try:
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            if manifest['key'] != key:
                raise ValueError('Changed inputs')
            if racer and not isinstance(manifest.get('racers'), dict):
                raise ValueError('Missing roster state')
            # Validate the whole entry before restoring any file.
            for row in manifest['files']:
                p = folder / 'files' / safe_path(row['path'])
                if row['kind'] not in ('stream', 'archive', 'text', 'binary'):
                    raise ValueError('Invalid cache kind')
                if not (site.output_root / row['path']).resolve().is_relative_to(site.output_root.resolve()):
                    raise ValueError('Output escaped public directory')
                if not p.is_file() or not p.resolve().is_relative_to(folder.resolve()):
                    raise ValueError('Incomplete cache')
                with p.open('rb') as f:
                    if hashlib.file_digest(f, 'sha256').hexdigest() != row['sha256']:
                        raise ValueError('Incomplete cache')
            for row in manifest['files']:
                path = row['path']
                src, dest = folder / 'files' / path, site.output_root / path
                kind = row['kind']
                if kind in ('stream', 'archive'):
                    restore_file(src, dest)
                    if kind == 'stream':
                        site.files[path] = ''
                        site._streamed.add(path)
                elif kind == 'text':
                    site.files[path] = src.read_text(encoding='utf-8')
                else:
                    site.bins[path] = src.read_bytes()
            if racer:
                site.racers = manifest['racers']
            self.hits += 1
            print(f'build-cache {name}: hit {time.monotonic()-started:.2f}s', flush=True)
            return
        except (OSError, ValueError, KeyError, TypeError):
            for path in set(site.files) - before:
                del site.files[path]
            site._streamed = streamed
            site.bins = dict(binaries)
        self.misses += 1
        outputs = produce() or []
        rows = []
        for path in sorted(set(site.files) - before):
            kind = 'stream' if path in site._streamed else 'text'
            rows.append((path, kind))
        rows.extend((p, 'binary') for p, value in site.bins.items() if binaries.get(p) != value)
        rows.extend((p, 'archive') for p in outputs)
        # This directory is exclusively our disposable cache entry. No source
        # files or public output files are removed on invalidation.
        if folder.exists():
            shutil.rmtree(folder)
        (folder / 'files').mkdir(parents=True)
        manifest = {'key': key, 'files': []}
        for path, kind in rows:
            safe_path(path)
            dest = folder / 'files' / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            if kind in ('stream', 'archive'):
                shutil.copyfile(site.output_root / path, dest)
            elif kind == 'text':
                dest.write_text(site.files[path], encoding='utf-8')
            else:
                dest.write_bytes(site.bins[path])
            with dest.open('rb') as f:
                sha = hashlib.file_digest(f, 'sha256').hexdigest()
            manifest['files'].append({'path': path, 'kind': kind, 'sha256': sha})
        if racer:
            manifest['racers'] = site.racers
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')
        self.changed = True
        print(f'build-cache {name}: rebuilt {time.monotonic()-started:.2f}s', flush=True)

    def finish(self):
        if self.directory.is_dir():
            for folder in self.directory.iterdir():
                if folder.is_dir() and folder.name.startswith('races-') and folder.name not in self.used:
                    if not folder.resolve().is_relative_to(self.directory.resolve()):
                        raise ValueError('Cache cleanup escaped cache directory')
                    shutil.rmtree(folder)
                    self.changed = True
        output = os.environ.get('GITHUB_OUTPUT')
        if output:
            with open(output, 'a', encoding='utf-8') as f:
                f.write(f'cache_changed={str(self.changed).lower()}\n')
        print(f'build-cache total: {self.hits} hits / {self.misses} rebuilds', flush=True)
