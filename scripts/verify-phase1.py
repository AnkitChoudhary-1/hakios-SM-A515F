#!/usr/bin/env python3
"""Verify Phase 1 evidence in WSL; optionally retain a checksum-indexed bundle.

Run through run.py. This reads retained inputs and Git identities, never the phone.
The evidence selection is explicit in manifests/phase-1-evidence.json.
"""
import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path, PureWindowsPath

PROJECT = Path(__file__).resolve().parents[1]


def load(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def project_path(relative, root=PROJECT):
    path = (root / relative).resolve()
    require(path.is_relative_to(root.resolve()), 'path outside project/bundle: ' + str(relative))
    return path


def input_path(value):
    # Windows inventory paths are read through the WSL mount; source stays in /opt.
    if re.match(r'^[A-Za-z]:[\\/]', value):
        win = PureWindowsPath(value)
        return Path('/mnt') / win.drive[0].lower() / Path(*win.parts[1:])
    return Path(value)


def git(path, *args):
    return subprocess.check_output(['git', '-C', str(path), *args], text=True).strip()


def artifact_identities(records):
    require(len(records) == 4, 'expected exactly four build artifacts')
    result = {r['path']: (r['size'], r['sha256']) for r in records}
    require(len(result) == 4, 'duplicate artifact paths')
    root = '/opt/a51-hakios/src/hakios-xnu-kernel/'
    require(set(result) == {root + p for p in
            ('hakios-kernel', 'xnuloader/loader.efi', 'userland/hello', 'qemu/payload.bin')},
            'unexpected artifact set')
    return result


def verify_bundle(folder):
    index = load(folder / 'index.json')
    require(index['schema_version'] == 1 and index['files'], 'invalid/empty bundle index')
    seen = set()
    for record in index['files']:
        path = project_path(record['path'], folder)
        require(record['path'] != 'index.json' and record['path'] not in seen,
                'duplicate/self-referential bundle entry')
        seen.add(record['path'])
        require(path.is_file(), 'missing bundle file: ' + record['path'])
        require(path.stat().st_size == record['size'] and digest(path) == record['sha256'],
                'bundle file changed: ' + record['path'])
    return len(seen)


def verify_evidence(selection):
    retained = set()
    counts = {}
    notes = []

    def selected(relative):
        path = project_path(relative)
        require(path.is_file(), 'missing evidence: ' + relative)
        retained.add(path)
        return path

    for relative in selection['passed_runs']:
        meta_path = selected(relative + '/metadata.json')
        meta = load(meta_path)
        require(meta.get('status') == 'passed' and meta.get('exit_code') == 0,
                'run did not pass: ' + relative)
        selected(relative + '/output.log')
        retained.update(p for p in (meta_path.parent / 'project-scripts').glob('*') if p.is_file())
        for label in ('started', 'finished'):
            utc = dt.datetime.fromisoformat(meta[label]['utc'])
            ist = dt.datetime.fromisoformat(meta[label]['ist'])
            require(utc == ist, 'timestamp instants disagree: ' + relative)
            if utc.utcoffset() != dt.timedelta(0):
                notes.append(relative + ': historical utc field uses a non-UTC offset; normalize the aware timestamp')
    counts['passed_runs'] = len(selection['passed_runs'])

    build_path = selected(selection['build_manifest'])
    build = load(build_path)
    require(build['build_exit_code'] == 0, 'captured build failed')
    require(input_path(build['snapshot']).resolve() == build_path.parent, 'build snapshot path mismatch')
    retained.update(p for p in build_path.parent.iterdir() if p.is_file())
    identities = artifact_identities(build['artifacts'])
    for value, (size, sha) in identities.items():
        path = input_path(value)
        require(path.is_file() and path.stat().st_size == size and digest(path) == sha,
                'current artifact differs from accepted build: ' + value)
    counts['build_artifacts'] = len(identities)

    spec = importlib.util.spec_from_file_location('qemu_acceptance', PROJECT / 'scripts/qemu-open.py')
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)
    for relative in selection['qemu_results']:
        path = selected(relative)
        result = load(path)
        serial_path = selected(str((path.parent / 'serial.log').relative_to(PROJECT)))
        require(input_path(result['serial_log']).resolve() == serial_path, 'serial path mismatch')
        require(input_path(result['build_snapshot']).resolve() == build_path.parent, 'QEMU build mismatch')
        require(artifact_identities(result['artifacts']) == identities, 'QEMU artifact identity mismatch')
        actual = validator.validate_serial(serial_path.read_text(errors='replace'), result['runner_exit_code'])
        require(actual == (result['markers'], result['panic_lines'], result['expected_init_exit_panic'], result['passed'])
                and actual[3] is True, 'raw serial/result acceptance mismatch: ' + relative)
    counts['qemu_transcripts'] = len(selection['qemu_results'])

    pins = load(selected('manifests/source-lock.json'))['repositories']
    require(len(pins) == 9, 'expected nine source pins')
    for repo in pins:
        path = input_path(repo['path'])
        require(git(path, 'rev-parse', 'HEAD') == repo['commit'], 'source pin drift: ' + repo['path'])
        if not repo['generated_overlay']:
            require(not git(path, 'status', '--short'), 'source modified: ' + repo['path'])
    counts['source_pins'] = len(pins)

    deps = load(selected('manifests/dependencies.json'))
    for asset in deps['assets'].values():
        path = input_path(asset['path'])
        require(path.stat().st_size == asset['size'] and digest(path) == asset['sha256'],
                'dependency archive changed: ' + asset['path'])
    for repo in deps['repositories'].values():
        path = input_path(repo['path'])
        require(git(path, 'rev-parse', 'HEAD') == repo['commit'] and not git(path, 'status', '--short'),
                'SDK source drift/modification: ' + repo['path'])
    counts['dependency_archives'] = len(deps['assets'])
    counts['sdk_pins'] = len(deps['repositories'])

    inventory = load(selected(selection['inventory']))
    require(inventory['phone_writes'] is False and len(inventory['connected_devices']) == 1,
            'missing read-only connected inventory')
    queries = inventory['device_queries']
    require(len(queries) == 19 and all(q.get('exit_code') == 0 for q in queries), 'basic inventory incomplete')
    counts['historical_device_queries'] = len(queries)
    file_count = 0

    def verify_record(record):
        nonlocal file_count
        archived = selection['historical_input_copies'].get(record['path'])
        path = selected(archived) if archived else input_path(record['path'])
        require(path.is_file() and digest(path) == record['sha256'], 'retained input changed: ' + record['path'])
        if 'size' in record:
            require(path.stat().st_size == record['size'], 'retained input size changed: ' + record['path'])
        file_count += 1

    for record in inventory['retained_inputs']:
        verify_record(record)
    hardware = load(selected('manifests/hardware-inputs.json'))
    require(hardware['phone_writes'] is False and len(hardware['linux_reference_groups']) == 8,
            'hardware trace scope/group mismatch')
    for group in hardware['linux_reference_groups'].values():
        require(group['files'], 'empty hardware reference group')
        for record in group['files']:
            verify_record(record)
    research = load(selected('manifests/research-audit.json'))
    for tree in research['trees'].values():
        verify_record({'path': tree['tree_file'], 'sha256': tree['sha256']})
        listing = load(input_path(tree['tree_file']))
        require(not listing.get('truncated') and listing['sha'] == tree['commit'], 'research tree identity mismatch')
    counts['retained_input_hashes'] = file_count
    counts['hardware_reference_groups'] = len(hardware['linux_reference_groups'])

    state = load(selected('state.json'))
    require(state['phase_1_status'] == 'complete' and not state['outstanding_phase_1_checks'],
            'current Phase 1 decision is not synchronized')
    require(all(state[k] is False for k in ('a51_xnu_boot_verified', 'no_flash_a51_launch_verified', 'device_writes_this_phase')),
            'unsupported device claims in state')
    for relative, marker in selection['documentation_markers'].items():
        require(marker in selected(relative).read_text(encoding='utf-8'), 'stale documentation: ' + relative)
    return counts, notes, retained


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', help='new bundle directory relative to the project; never overwritten')
    parser.add_argument('--verify-bundle', help='verify an existing bundle index without live inputs')
    args = parser.parse_args()
    require(not (args.bundle and args.verify_bundle), 'choose one bundle operation')
    if args.verify_bundle:
        count = verify_bundle(project_path(args.verify_bundle))
        print('Verified bundle files:', count)
        return
    selection = load(PROJECT / 'manifests/phase-1-evidence.json')
    counts, notes, retained = verify_evidence(selection)
    result = {'schema_version': 1, 'verified_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
              'passed': True, 'counts': counts, 'notes': notes,
              'scope': 'retained Phase 1 evidence and current host inputs; no live device validation'}
    if args.bundle:
        folder = project_path(args.bundle)
        require(not folder.exists(), 'bundle already exists: ' + str(folder))
        for directory in ('docs', 'scripts', 'manifests'):
            retained.update(p for p in (PROJECT / directory).iterdir() if p.is_file())
        retained.update((PROJECT / 'README.md', PROJECT / 'runs/events.jsonl'))
        folder.mkdir(parents=True)
        for source in sorted(retained):
            dest = folder / source.relative_to(PROJECT)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
        (folder / 'verification.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
        files = [{'path': p.relative_to(folder).as_posix(), 'size': p.stat().st_size, 'sha256': digest(p)}
                 for p in sorted(folder.rglob('*')) if p.is_file()]
        index = {'schema_version': 1, 'created_utc': result['verified_utc'], 'files': files,
                 'limits': 'SHA-256 detects changes against this index, not independent authentication. '
                           'The active recorder run is finalized after the bundle and is outside its ledger snapshot. '
                           'Large /opt artifacts and external Android backups remain at their recorded paths.'}
        (folder / 'index.json').write_text(json.dumps(index, indent=2) + '\n', encoding='utf-8')
        result['bundle_files_verified'] = verify_bundle(folder)
        print('Bundle:', folder, flush=True)
    print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    main()
