#!/usr/bin/env python3
"""Inspect and preserve the existing Phase 3 source without changing its checkout."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

PROJECT = Path('/mnt/c/Users/Ankit/Desktop/A51/hakios-a51')
COMMON = Path('/opt/a51-hakios/src/hakios-xnu-kernel')
NATIVE = COMMON / 'xnu-src/xnu-8796.121.2'
EXPECTED_HEADS = {'common': '63fc2b4633bac3af8e57dadab9f5a8d4cb940438',
                  'native': 'c54f35ca767986246321eb901baf8f5ff7923f6a'}


def digest(path: Path) -> dict:
    raw = path.read_bytes()
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def source_inventory(root: Path, excluded: set[str]) -> dict:
    result = {}
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [name for name in dirs if name not in excluded and name != '.git']
        for name in dirs + files:
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                result[relative] = {'symlink': os.readlink(path)}
            elif path.is_file() and name not in excluded:
                result[relative] = {**digest(path), 'mode': path.stat().st_mode & 0o777}
    return result


def prepare() -> int:
    """Preserve complete source state, then make a separate clean-output build tree."""
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    packet = PROJECT / 'evidence/phase-3/source-preservation' / stamp
    root = Path('/opt/a51-hakios/experimental/phase3-port') / stamp
    packet.mkdir(parents=True, exist_ok=False)
    root.mkdir(parents=True, exist_ok=False)
    commands = []

    def run(name: str, argv: list[str], timeout=300) -> str:
        print('COMMAND ' + name, flush=True)
        start = dt.datetime.now(dt.timezone.utc).isoformat()
        proc = subprocess.run(argv, capture_output=True, timeout=timeout)
        (packet / (name + '.stdout')).write_bytes(proc.stdout)
        (packet / (name + '.stderr')).write_bytes(proc.stderr)
        commands.append({'name': name, 'argv': argv, 'started_utc': start,
                         'finished_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
                         'exit_code': proc.returncode})
        if proc.returncode:
            raise RuntimeError(name + ': ' + proc.stderr.decode(errors='replace'))
        return proc.stdout.decode(errors='replace')

    trees = [('common', COMMON, root, {'xnu-src', 'xnu-deps', '.git'}),
             ('native', NATIVE, root / 'xnu-src/xnu-8796.121.2', {'BUILD', '.git'})]
    records = {}
    for name, original, target, excluded in trees:
        head = run(name + '-head', ['git', '-C', str(original), 'rev-parse', 'HEAD']).strip()
        if head != EXPECTED_HEADS[name]:
            raise ValueError('unexpected source HEAD: ' + name)
        origin = run(name + '-origin', ['git', '-C', str(original), 'remote', 'get-url', 'origin']).strip()
        run(name + '-status', ['git', '-C', str(original), 'status', '--short'])
        run(name + '-tracked-adaptations', ['git', '-C', str(original), 'diff', '--binary', 'HEAD'])
        before = source_inventory(original, excluded)
        (packet / (name + '-source-files.json')).write_text(json.dumps(before, indent=2) + '\n')
        archive = packet / (name + '-source.tar')
        run(name + '-snapshot', ['tar', '-C', str(original),
            *['--exclude=./' + e for e in sorted(excluded)], '--exclude=.git',
            '-cf', str(archive), '.'])
        target.parent.mkdir(parents=True, exist_ok=True)
        # root already exists but is empty; git accepts it. Never share Git metadata.
        run(name + '-clone', ['git', 'clone', '--local', '--no-hardlinks', str(original), str(target)])
        run(name + '-upstream-origin', ['git', '-C', str(target), 'remote', 'set-url', 'origin', origin])
        run(name + '-restore-adaptations', ['tar', '-C', str(target), '-xf', str(archive)])
        restored = source_inventory(target, excluded)
        if before != restored or before != source_inventory(original, excluded):
            raise ValueError('source preservation mismatch: ' + name)
        records[name] = {'original': str(original), 'isolated': str(target),
                         'head': head, 'origin': origin, 'files': len(before),
                         'archive': archive.name, **digest(archive),
                         'source_bytes_verified': True, 'original_unchanged': True}

    # Dependencies are copied, including their symlink provenance; setup/download is not run.
    deps_before = source_inventory(COMMON / 'xnu-deps', {'.git'})
    run('copy-dependencies', ['cp', '-a', '--reflink=auto', str(COMMON / 'xnu-deps') + '/.', str(root / 'xnu-deps')])
    if deps_before != source_inventory(root / 'xnu-deps', {'.git'}):
        raise ValueError('dependency copy mismatch')
    (packet / 'dependency-files.json').write_text(json.dumps(deps_before, indent=2) + '\n')
    result = {'schema_version': 1, 'scope': 'isolated_phase3_source_preservation',
              'root': str(root), 'packet': str(packet.relative_to(PROJECT)),
              'trees': records, 'dependency_files': len(deps_before),
              'commands': commands, 'native_build_output_copied': False,
              'device_operations': False}
    (packet / 'source.py').write_bytes(Path(__file__).read_bytes())
    (packet / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    (packet / 'index.json').write_text(json.dumps([
        {'path': str(p.relative_to(packet)), **digest(p)}
        for p in sorted(packet.rglob('*')) if p.is_file()], indent=2) + '\n')
    active = PROJECT / 'manifests/phase3-workspace.json'
    active.write_text(json.dumps({**result, 'result_pin': digest(packet / 'result.json')}, indent=2) + '\n')
    print(json.dumps({'root': str(root), 'packet': str(packet.relative_to(PROJECT)),
                      'source_preservation_verified': True}, indent=2), flush=True)
    return 0


def inspect() -> int:
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    packet = PROJECT / 'evidence/phase-3/source-inspection' / stamp
    packet.mkdir(parents=True, exist_ok=False)
    commands = []

    def run(name: str, argv: list[str], ok=(0,)) -> str:
        result = subprocess.run(argv, capture_output=True, timeout=60)
        (packet / f'{name}.stdout').write_bytes(result.stdout)
        (packet / f'{name}.stderr').write_bytes(result.stderr)
        commands.append({'name': name, 'argv': argv, 'exit_code': result.returncode})
        if result.returncode not in ok:
            raise RuntimeError(f'{name} failed: {result.stderr.decode(errors="replace")}')
        return result.stdout.decode(errors='replace')

    provenance = {}
    for name, root in [('common', COMMON), ('native', NATIVE)]:
        provenance[name] = {
            'root': str(root),
            'head': run(f'{name}-head', ['git', '-C', str(root), 'rev-parse', 'HEAD']).strip(),
            'status': run(f'{name}-status', ['git', '-C', str(root), 'status', '--short']),
            'remotes': run(f'{name}-remotes', ['git', '-C', str(root), 'remote', '-v']),
        }
        instructions = run(f'{name}-instructions', [
            'rg', '--files', '--hidden', '--no-ignore', '-g', 'AGENTS.md',
            '-g', '!**/.git/**', '-g', '!**/BUILD/**', str(root)], ok=(0, 1)).splitlines()
        provenance[name]['instruction_files'] = instructions
        for i, source in enumerate(instructions):
            (packet / f'{name}-AGENTS-{i}.md').write_bytes(Path(source).read_bytes())
        run(f'{name}-tracked-adaptations', ['git', '-C', str(root), 'diff', '--binary', 'HEAD'])

    sources = [
        ('Makefile', COMMON / 'Makefile'),
        ('xnu-build.sh', COMMON / 'xnu/build.sh'),
        ('xnu-export.sh', COMMON / 'xnu/export.sh'),
        ('qemu-run.sh', COMMON / 'qemu/run.sh'),
        ('hello.c', COMMON / 'userland/src/hello.c'),
        ('userland-make.sh', COMMON / 'userland/make.sh'),
        ('a51-device.conf', COMMON / 'devices/a51/device.conf'),
        ('a51-defconfig', COMMON / 'devices/a51/configs/a51_defconfig'),
        ('BCM2837.h', NATIVE / 'pexpert/pexpert/arm64/BCM2837.h'),
        ('gic_v3_irq.c', NATIVE / 'osfmk/arm64/gic_v3_irq.c'),
        ('generic_arm64_support.c', NATIVE / 'osfmk/arm64/generic_arm64_support.c'),
        ('start.s', NATIVE / 'osfmk/arm64/start.s'),
        ('loader_return.c', NATIVE / 'osfmk/arm64/loader_return.c'),
        ('pe_serial.c', NATIVE / 'pexpert/arm/pe_serial.c'),
        ('pe_identify_machine.c', NATIVE / 'pexpert/arm/pe_identify_machine.c'),
        ('bsd_init.c', NATIVE / 'bsd/kern/bsd_init.c'),
        ('ramfs_vfsops.c', NATIVE / 'bsd/miscfs/ramfs/ramfs_vfsops.c'),
    ]
    source_index = []
    for name, source in sources:
        if source.is_file():
            target = packet / 'sources' / name
            target.parent.mkdir(exist_ok=True)
            target.write_bytes(source.read_bytes())
            source_index.append({'source': str(source), 'snapshot': str(target.relative_to(packet)), **digest(target)})
        else:
            source_index.append({'source': str(source), 'available': False})

    run('dependency-repositories', ['rg', '--files', '--hidden', '--no-ignore',
        '-g', 'HEAD', '-g', '**/.git/HEAD', str(COMMON / 'xnu-deps')], ok=(0, 1))
    run('native-user-timer-hooks', ['rg', '-n', '-e', 'raw-hello', '-e', 'ramdisk',
        '-e', 'rtclock_intr', '-e', 'gic_v3_irq', '-e', 'platform_init',
        str(NATIVE / 'bsd/kern/bsd_init.c'), str(NATIVE / 'pexpert/arm/pe_identify_machine.c'),
        str(NATIVE / 'osfmk/arm64/gic_v3_irq.c'), str(NATIVE / 'osfmk/arm/rtclock.c')], ok=(0, 1))
    result = {'schema_version': 1, 'scope': 'read_only_source_inspection',
              'provenance': provenance, 'commands': commands, 'sources': source_index,
              'device_operations': False}
    (packet / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    (packet / 'source.py').write_bytes(Path(__file__).read_bytes())
    index = [{'path': str(p.relative_to(packet)), **digest(p)}
             for p in sorted(packet.rglob('*')) if p.is_file()]
    (packet / 'index.json').write_text(json.dumps(index, indent=2) + '\n')
    print(json.dumps({'packet': str(packet.relative_to(PROJECT)), 'provenance': provenance,
                      'captured_sources': len(source_index)}, indent=2), flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['inspect', 'prepare'])
    args = parser.parse_args()
    return inspect() if args.action == 'inspect' else prepare()


if __name__ == '__main__':
    raise SystemExit(main())
