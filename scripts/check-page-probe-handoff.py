#!/usr/bin/env python3
"""Verify Android diagnostic selection and historical gates without a phone."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, PROJECT / 'scripts' / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def main():
    previous = module('page_historical_handoff', 'check-device-prerequisites-handoff.py')
    base = previous.base
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        base.require(previous.main() == 0, 'historical handoff failed')
    counts = json.loads(out.getvalue().splitlines()[-1])
    state = base.read_json(PROJECT / 'state.json')
    selection = state['phase_2_evidence_selection']
    current = state['phase_2_page_probe_validation']
    host_path = base.selected_path(selection['page_probe_host_result'])
    device_path = base.selected_path(selection['page_probe_device_result'])
    for label, path in [('host', host_path), ('device', device_path)]:
        base.require(base.digest(path) == selection['page_probe_' + label + '_result_sha256'], 'result pin drift')
        index = base.read_json(path.parent / 'index.json')
        base.require(base.digest(path.parent / 'index.json') == selection['page_probe_' + label + '_index_sha256'], 'index pin drift')
        for name, expected in index['files'].items():
            file = path.parent / name
            base.require(file.resolve().is_relative_to(path.parent.resolve()) and not file.is_symlink(), 'packet path escapes')
            size = expected.get('bytes', expected.get('size'))
            base.require(file.stat().st_size == size and base.digest(file) == expected['sha256'], 'packet file changed')
    host = base.read_json(host_path)
    device = base.read_json(device_path)
    verifier = module('page_device_verifier', 'test-page-probe-device.py')
    flags = verifier.verify(device_path.parent)
    base.require(device['status'] == 'passed' and current['flags'] == flags and
        current['device_queries'] == len(device['queries']) == 20 and
        state['device_writes_this_phase'] is True and not state['phase_2_device_gate_passed'], 'current diagnostic status mismatch')
    base.require(host['original_metadata_unchanged'] and host['original_input_bytes_unchanged'] and
        host['status'] == 'passed' and host['host_abi_candidate_verified'] and len(host['imported_crcs']) == 9,
        'host ABI candidate mismatch')
    base.require((host_path.parent / 'original-metadata-before.json').read_bytes() ==
        (host_path.parent / 'original-metadata-after.json').read_bytes(), 'original tree metadata changed')
    compiler = module('page_build_reader', 'build-page-probe.py')
    sections = compiler.elf_sections((host_path.parent / 'hakios_page_probe.ko').read_bytes())
    base.require('vermagic=' + host['vermagic'] in sections['.modinfo'][1].decode().split('\0'), 'ELF identity drift')
    for rel in ['diagnostics/page-probe/hakios_page_probe.c', 'diagnostics/page-probe/Makefile']:
        base.require(base.digest(PROJECT / rel) == base.digest(host_path.parent / 'module' / Path(rel).name), 'compiled module source changed')
    for key, marker in [('build_run', 'ABI_CANDIDATE_VERIFIED imports=9'),
                        ('device_run', 'PAGE_PROBE_DEVICE_VERIFIED')]:
        run_path, run = base.check_run(current[key])
        base.require(marker in (run_path.parent / 'output.log').read_text(encoding='utf-8'), 'run lacks success evidence')
        if key == 'build_run':
            base.require(run['command'] == ['wsl', '-d', 'A51-KernelBuilder', '-u', 'root', '--',
                'python3', '/mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/build-page-probe.py'], 'build command role differs')
        else:
            base.require(run['command'] == ['python', 'scripts/test-page-probe-device.py', '--build',
                device['host_build'], '--serial', device['serial']], 'capture command role differs')
            base.require(base.digest(run_path.parent / 'project-scripts/test-page-probe-device.py') ==
                base.digest(device_path.parent / 'test-page-probe-device.py') == current['capture_script_sha256'], 'capture revision drift')
    for host_name, run_name in current['replay_runs'].items():
        run_path, run = base.check_run(run_name)
        base.require('--verify' in run['command'] and '--serial' not in run['command'] and
            '"same_android_boot_verified": true' in (run_path.parent / 'output.log').read_text(encoding='utf-8'), 'replay role differs')
        base.require(base.digest(run_path.parent / 'project-scripts/test-page-probe-device.py') ==
            base.digest(PROJECT / 'scripts/test-page-probe-device.py') == current['replay_script_sha256'], 'replay revision drift')
    before = PROJECT / 'evidence/phase-2/page-probe-docs/20261111T1255Z/before'
    checkpoint = base.read_json(before / 'index.json')
    for item in checkpoint['files']:
        path = before / item['copy']
        base.require(path.stat().st_size == item['size'] and base.digest(path) == item['sha256'], 'rollback copy changed')
    old = base.read_json(before / '09-state.json')
    base.require(all(selection[k] == v for k, v in old['phase_2_evidence_selection'].items()), 'historical selections changed')
    for key in ['phase_2_source_trace_validation', 'phase_2_loader_prototype_validation',
                'phase_2_runtime_map_validation', 'phase_2_entry_route_review', 'phase_2_connected_device_validation']:
        base.require(state[key] == old[key], 'historical milestone mutated: ' + key)
    guide = (PROJECT / 'docs/PAGE-PROBE.md').read_text(encoding='utf-8')
    state_doc = (PROJECT / 'docs/STATE.md').read_text(encoding='utf-8')
    base.require(selection['page_probe_device_result'] in guide and selection['page_probe_device_result'] in state_doc and
        '4096' in guide and 'released' in guide and 'Phase 2' in guide, 'device result missing in docs')
    print(json.dumps({**counts, 'phone_queries': True, 'phone_writes': True,
        'diagnostic_device_queries': 20, 'diagnostic_lifecycle_messages': 7,
        'module_import_crcs': 9, 'module_load_unload_verified': True,
        'failed_init_cleanup_verified': True, 'same_android_boot_verified': True,
        'diagnostic_rollback_copies': len(checkpoint['files']), 'phase_2_device_gate_passed': False}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
