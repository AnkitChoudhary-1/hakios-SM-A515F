#!/usr/bin/env python3
"""Check current ownership milestone plus every preserved previous handoff."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import re
import struct
import arena_probe as arena
import ownership_probe as ownership

PROJECT = Path(__file__).resolve().parents[1]


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, PROJECT / 'scripts' / filename)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def main():
    previous = module('ownership_previous', 'check-arena-probe-handoff.py')
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        arena.require(previous.main() == 0, 'historical handoff failed')
    old_counts = json.loads(output.getvalue().splitlines()[-1])
    state = arena.read_json(PROJECT / 'state.json')
    current = state['phase_2_ownership_probe_validation']
    selection = state['phase_2_evidence_selection']
    verifier = module('ownership_current_device', 'test-ownership-probe-device.py')
    transport = verifier.transport
    paths, records, indexes = {}, {}, {}
    for label in ['host', 'device']:
        key = 'ownership_probe_' + label
        path = transport.inside(PROJECT, selection[key + '_result'])
        arena.require(arena.pin(path)['sha256'] == selection[key + '_result_sha256'] and
            arena.pin(path.parent / 'index.json')['sha256'] == selection[key + '_index_sha256'], 'selected packet changed')
        index = arena.read_json(path.parent / 'index.json')
        for rel, pin in index['files'].items():
            expected = {'bytes': pin.get('bytes', pin.get('size')), 'sha256': pin['sha256']}
            file = transport.inside(path.parent, rel)
            arena.require(not file.is_symlink() and arena.pin(file) == expected, 'packet pin changed: ' + rel)
        paths[label], records[label], indexes[label] = path, arena.read_json(path), index
    host, device = records['host'], records['device']
    flags = verifier.verify(paths['device'].parent)
    arena.require(host['status'] == device['status'] == 'passed' and
        transport.canonical(current['flags']) == transport.canonical(flags) and
        transport.canonical(current['closed_lifetimes']) == transport.canonical(device['closed_lifetimes']), 'state observations changed')
    arena.require(state['phase_1_status'] == 'complete' and state['phase_2_status'] == 'in_progress' and
        state['phase_2_device_gate_passed'] is False and state['a51_xnu_boot_verified'] is False and
        state['no_flash_a51_launch_verified'] is False and current['external_ownership_certificate_implemented'] is False and
        current['runtime_loader_layout_acceptance_implemented'] is False, 'phase/placement promotion')
    arena.require(host['original_metadata_unchanged'] is True and host['original_input_bytes_unchanged'] is True and
        (paths['host'].parent / 'original-metadata-before.json').read_bytes() ==
        (paths['host'].parent / 'original-metadata-after.json').read_bytes(), 'Android metadata changed')
    builder = module('ownership_elf_reader', 'build-ownership-probe.py')
    sections = builder.elf_sections((paths['host'].parent / 'hakios_ownership_probe.ko').read_bytes())
    arena.require('vermagic=' + host['vermagic'] in sections['.modinfo'][1].decode().split('\0'), 'ELF vermagic mismatch')
    versions = sections['__versions'][1]
    arena.require(len(versions) == 17 * 64, 'ABI count mismatch')
    symvers = {line.split()[1]: int(line.split()[0], 16) for line in
        (paths['host'].parent / 'Module.symvers').read_text(encoding='utf-8').splitlines()}
    imports = {}
    for offset in range(0, len(versions), 64):
        crc = struct.unpack_from('<Q', versions, offset)[0]
        name = versions[offset + 8:offset + 64].split(b'\0', 1)[0].decode()
        arena.require(name not in imports and symvers.get(name) == crc, 'ABI CRC mismatch')
        imports[name] = hex(crc)
    arena.require(imports == current['imported_crcs'] == host['imported_crcs'] and
        current['module'] == host['module'] and current['budget'] == host['budget'], 'ABI/module state mismatch')
    for name in ['Makefile', 'hakios_ownership_probe.c', 'ownership_core.h', 'test_ownership.c', 'arena_budget.h']:
        arena.require(arena.pin(PROJECT / 'diagnostics/ownership-probe' / name) ==
            arena.pin(paths['host'].parent / 'module' / name), 'compiled source changed: ' + name)
    native = (paths['host'].parent / 'native-tests.log').read_text().strip()
    arena.require(native == 'OWNERSHIP_CORE_GUARDS assertions=1408 parser_cases=801 state_cases=115 layout_cases=51', 'native guard counts mismatch')
    for rel, pin in current['source_pins'].items():
        arena.require(arena.pin(transport.inside(PROJECT, rel)) == pin, 'current source changed: ' + rel)
    binding_path = verifier.binding_path(device)
    arena.require(arena.pin(binding_path) == current['capture_binding_pin'], 'capture binding changed')
    binding = arena.read_json(binding_path)
    capture_run = arena.read_json(transport.inside(PROJECT, binding['capture_run']))
    arena.require(capture_run['status'] == 'passed' and capture_run['exit_code'] == 0, 'capture run not complete')
    first, last = device['queries'][0], device['queries'][-1]
    arena.require(transport.time_pair(capture_run['started']) <= transport.time_pair(first['started']) and
        transport.time_pair(last['finished']) <= transport.time_pair(capture_run['finished']), 'capture run timing changed')
    for key, rel in current['verification_runs'].items():
        run_path = transport.inside(PROJECT, rel)
        run = arena.read_json(run_path)
        arena.require(run['status'] == 'passed' and type(run['exit_code']) is int and run['exit_code'] == 0 and
            transport.time_pair(run['started']) <= transport.time_pair(run['finished']), 'unfinished/failed selected run: ' + key)
        if key.startswith(('replay_', 'guards_')):
            for name in ['ownership_probe.py', 'test-ownership-probe-device.py', 'test-ownership-probe-evidence.py']:
                arena.require(arena.pin(run_path.parent / 'project-scripts' / name) ==
                    arena.pin(PROJECT / 'scripts' / name), 'final replay source mismatch')
            result = json.loads((run_path.parent / 'output.log').read_text(encoding='utf-8').replace('\x00', '').splitlines()[-1])
            if key.startswith('replay_'):
                arena.require(transport.canonical(result) == transport.canonical(flags), 'replay flags mismatch')
            else:
                arena.require(result['passed'] is True and result['corruption_cases'] == result['corruption_rejections'] == 44 and
                    result['accepted_corruptions'] == [] and result['original_packet_reverified'] is True and
                    result['original_packet'] == paths['device'].parent.relative_to(PROJECT).as_posix(), 'guard result mismatch')
    before = transport.inside(PROJECT, current['rollback_index']).parent
    checkpoint = arena.read_json(before / 'index.json')
    arena.require(len(checkpoint['files']) == 12, 'rollback count mismatch')
    for item in checkpoint['files']:
        arena.require(arena.pin(before / item['copy']) == item['pin'], 'rollback pin changed')
    baseline = arena.read_json(before / '11-state.json')
    arena.require(all(selection[k] == v for k, v in baseline['phase_2_evidence_selection'].items()), 'historical selection changed')
    for key in baseline:
        if key.startswith('phase_2_') and key != 'phase_2_evidence_selection':
            arena.require(state[key] == baseline[key], 'historical milestone changed: ' + key)
    for rel in ['README.md', 'docs/STATE.md', 'docs/HANDOFF.md', 'docs/OWNERSHIP-PROBE.md']:
        text = (PROJECT / rel).read_text(encoding='utf-8')
        arena.require(selection['ownership_probe_device_result'] in text and 'released' in text and 'Phase 2' in text,
            'ownership documentation missing: ' + rel)
    counts = {**old_counts, 'passed': True, 'scope': current['scope'], 'ownership_device_queries': 23,
        'ownership_lifecycle_messages': 21, 'ownership_status_observations': 10,
        'ownership_allocations_released': 3, 'ownership_successful_bindings': 3,
        'ownership_rejected_requests': 7, 'ownership_native_assertions': 1408,
        'ownership_import_crcs': 17, 'ownership_guards_per_host': 44,
        'ownership_host_indexed_files': len(indexes['host']['files']),
        'ownership_device_indexed_files': len(indexes['device']['files']),
        'ownership_rollback_copies': 12, 'phase_2_device_gate_passed': False}
    if current['documentation_consistency'] == 'verified':
        run_path = transport.inside(PROJECT, current['documentation_consistency_run'])
        run = arena.read_json(run_path)
        arena.require(run['status'] == 'passed' and type(run['exit_code']) is int and run['exit_code'] == 0 and
            run['command'] == ['python', 'scripts/check-ownership-probe-handoff.py'] and
            transport.time_pair(run['started']) <= transport.time_pair(run['finished']), 'documentation run not complete or wrong role')
        result = json.loads((run_path.parent / 'output.log').read_text(encoding='utf-8').splitlines()[-1])
        arena.require(result == current['documentation_consistency_counts'] and result['passed'] is True and
            result['scope'] == current['scope'] and result['phase_2_device_gate_passed'] is False and
            all(result[key] == value for key, value in counts.items() if key.startswith('ownership_')),
            'selected documentation result/counts changed')
        arena.require(arena.pin(run_path.parent / 'project-scripts/check-ownership-probe-handoff.py') ==
            arena.pin(Path(__file__)), 'selected documentation checker changed')
    else:
        arena.require(current['documentation_consistency'] == 'pending', 'invalid documentation state')
    print(json.dumps(counts, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
