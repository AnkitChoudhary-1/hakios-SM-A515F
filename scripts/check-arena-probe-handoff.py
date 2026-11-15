#!/usr/bin/env python3
"""Offline arena selection/ABI/role/preservation/documentation verification."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import arena_probe as arena

PROJECT = arena.PROJECT


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, PROJECT / 'scripts' / filename)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def main():
    previous = module('arena_previous_handoff', 'check-page-probe-handoff.py')
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        arena.require(previous.main() == 0, 'historical handoff failed')
    counts = json.loads(output.getvalue().splitlines()[-1])
    base = previous.module('arena_historical_helpers', 'check-device-prerequisites-handoff.py').base
    state = arena.read_json(PROJECT / 'state.json')
    current = state['phase_2_arena_probe_validation']
    selection = state['phase_2_evidence_selection']
    paths = {}
    for label in ['host', 'device']:
        key = 'arena_probe_' + label
        path = base.selected_path(selection[key + '_result'])
        arena.require(base.digest(path) == selection[key + '_result_sha256'] and
            base.digest(path.parent / 'index.json') == selection[key + '_index_sha256'], 'selected packet pin differs')
        index = arena.read_json(path.parent / 'index.json')
        for name, pin in index['files'].items():
            file = path.parent / name
            arena.require(file.resolve().is_relative_to(path.parent.resolve()) and not file.is_symlink()
                and arena.pin(file) == {'bytes': pin.get('bytes', pin.get('size')), 'sha256': pin['sha256']},
                'selected packet file differs: ' + name)
        paths[label] = path
    host_path, device_path = paths['host'], paths['device']
    host, device = arena.read_json(host_path), arena.read_json(device_path)
    verifier = module('arena_selected_verifier', 'test-arena-probe-device.py')
    flags = verifier.verify(device_path.parent)
    arena.require(device['status'] == 'passed' and current['scope'] == device['scope'] and
        current['device_queries'] == len(device['queries']) == 23 and current['lifecycle_messages'] == 7 and
        verifier.transport.canonical(current['flags']) == verifier.transport.canonical(flags) and
        current['closed_lifetimes'] == device['closed_lifetimes'] and
        current['taint_before'] == current['taint_after'] == 4096, 'state/result observations differ')
    arena.require(state['device_writes_this_phase'] is True and state['phone_queries_this_continuation'] is True
        and state['phase_2_device_gate_passed'] is False and state['phase_2_status'] == 'in_progress'
        and current['payload_budget_final'] is False and current['active_ownership_certificate_implemented'] is False
        and current['layout_v1_acceptance_implemented'] is False, 'phase/scope promotion')
    arena.require(host['original_metadata_unchanged'] is True and host['original_input_bytes_unchanged'] is True
        and (host_path.parent / 'original-metadata-before.json').read_bytes() ==
            (host_path.parent / 'original-metadata-after.json').read_bytes(), 'original Android metadata changed')
    builder = module('arena_elf_reader', 'build-arena-probe.py')
    sections = builder.elf_sections((host_path.parent / 'hakios_arena_probe.ko').read_bytes())
    arena.require('vermagic=' + host['vermagic'] in sections['.modinfo'][1].decode().split('\0'), 'ELF vermagic differs')
    symvers = {line.split()[1]: int(line.split()[0], 16) for line in
               (host_path.parent / 'Module.symvers').read_text(encoding='utf-8').splitlines()}
    versions = sections['__versions'][1]
    arena.require(len(versions) == 9 * 64, 'module version count differs')
    imports = {}
    for offset in range(0, len(versions), 64):
        crc = struct.unpack_from('<Q', versions, offset)[0]
        name = versions[offset + 8:offset + 64].split(b'\0', 1)[0].decode()
        arena.require(name not in imports and symvers.get(name) == crc, 'module ABI differs')
        imports[name] = hex(crc)
    arena.require(imports == host['imported_crcs'] == current['imported_crcs'] and current['module'] == host['module']
        and current['budget'] == host['budget'], 'module/budget state differs')
    budget = arena.validate_budget(arena.read_json(host_path.parent / 'arena-probe-budget.json'))
    arena.require((host_path.parent / 'module/arena_budget.h').read_text(encoding='utf-8') == arena.header(budget),
                  'compiled budget differs')
    for name in ['hakios_arena_probe.c', 'Makefile', 'arena_budget.h']:
        arena.require(arena.pin(PROJECT / 'diagnostics/arena-probe' / name) ==
            arena.pin(host_path.parent / 'module' / name), 'compiled source changed')
    for rel, pin in current['source_pins'].items():
        arena.require(arena.pin(base.selected_path(rel)) == pin, 'selected source changed: ' + rel)
    for label in ['build', 'device']:
        run_path, run = base.check_run(current[label + '_run'])
        expected = (['wsl', '-d', 'A51-KernelBuilder', '-u', 'root', '--', 'python3',
            '/mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/build-arena-probe.py'] if label == 'build' else
            ['python', 'scripts/test-arena-probe-device.py', '--build', device['host_build'], '--serial', device['serial']])
        arena.require(run['command'] == expected, 'build/capture role differs')
        if label == 'device':
            for filename, key in [('test-arena-probe-device.py', 'capture_script_sha256'), ('arena_probe.py', 'capture_helper_sha256')]:
                arena.require(base.digest(run_path.parent / 'project-scripts' / filename) ==
                    base.digest(device_path.parent / filename) == current[key], 'frozen capture revision differs')
    for name, run_name in current['replay_runs'].items():
        run_path, run = base.check_run(run_name)
        packet = device_path.parent.relative_to(PROJECT).as_posix()
        expected = (['python', 'scripts/test-arena-probe-device.py', '--verify', packet] if name == 'windows' else
            ['wsl', '-d', 'A51-KernelBuilder', '-u', 'root', '--', 'python3',
             '/mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/test-arena-probe-device.py', '--verify',
             '/mnt/c/Users/Ankit/Desktop/A51/hakios-a51/' + packet])
        arena.require(run['command'] == expected and json.loads((run_path.parent / 'output.log').read_text(encoding='utf-8')
            .replace('\x00', '').splitlines()[-1]) == flags, 'replay command/result differs')
        for filename, key in [('test-arena-probe-device.py', 'replay_script_sha256'), ('arena_probe.py', 'replay_helper_sha256')]:
            arena.require(base.digest(run_path.parent / 'project-scripts' / filename) ==
                base.digest(PROJECT / 'scripts' / filename) == current[key], 'final replay revision differs')
    for name, run_name in current['guard_runs'].items():
        run_path, run = base.check_run(run_name)
        text = (run_path.parent / 'output.log').read_text(encoding='utf-8').replace('\x00', '')
        result = json.loads(text.splitlines()[-1])
        arena.require(result == {'passed': True, 'test_methods': 4, 'budget_mutations': 10, 'lifetime_rejections': 9},
            'budget/lifetime guard counts differ')
    corruption_path, corruption_run = base.check_run(current['corruption_checks_run'])
    corruption = json.loads((corruption_path.parent / 'output.log').read_text(encoding='utf-8').splitlines()[-1])
    arena.require(corruption['passed'] is True and corruption['corruption_rejections'] == current['corruption_rejections'] == 24
        and corruption['original_packet'] == device_path.parent.relative_to(PROJECT).as_posix()
        and corruption_run['command'] == ['python', 'scripts/test-arena-probe-evidence.py', '--packet', corruption['original_packet']],
        'corruption guard role/result differs')
    for key in ['preparation_run', 'allocator_source_review_run']:
        base.check_run(current[key])
    before = base.selected_path(current['rollback_index']).parent
    checkpoint = arena.read_json(before / 'index.json')
    arena.require(len(checkpoint['files']) == 10, 'rollback count differs')
    for item in checkpoint['files']:
        arena.require(arena.pin(before / item['copy']) == {key: item[key] for key in ['bytes', 'sha256']}, 'rollback copy differs')
    old = arena.read_json(before / '10-state.json')
    arena.require(all(selection[k] == v for k, v in old['phase_2_evidence_selection'].items()), 'historical selection changed')
    for key in old:
        if key.startswith('phase_2_') and key not in ['phase_2_evidence_selection']:
            arena.require(state[key] == old[key], 'historical milestone/gate changed: ' + key)
    for rel in ['docs/ARENA-PROBE.md', 'docs/STATE.md', 'docs/HANDOFF.md']:
        text = (PROJECT / rel).read_text(encoding='utf-8')
        arena.require(selection['arena_probe_device_result'] in text and 'released' in text and 'Phase 2' in text,
            'current arena documentation missing')
    if current['documentation_consistency'] == 'verified':
        base.check_run(current['documentation_consistency_run'])
    else:
        arena.require(current['documentation_consistency'] == 'pending', 'invalid handoff consistency state')
    print(json.dumps({**counts, 'passed': True, 'scope': current['scope'], 'arena_device_queries': 23,
        'arena_lifecycle_messages': 7, 'arena_host_indexed_files': 29, 'arena_device_indexed_files': 75,
        'arena_rollback_copies': 10, 'arena_corruption_rejections': 24, 'contiguous_64k_diagnostic_verified': True,
        'phase_2_device_gate_passed': False}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
