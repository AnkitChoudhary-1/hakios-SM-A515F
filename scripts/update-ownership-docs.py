#!/usr/bin/env python3
"""One-time UTF-8 documentation checkpoint and selection for P2-016."""
import json
from pathlib import Path
import shutil
import arena_probe as arena

PROJECT = Path(__file__).resolve().parents[1]
DEST = PROJECT / 'evidence/phase-2/ownership-probe-docs/20261111-p2-016'
HOST = 'evidence/phase-2/ownership-probe-build/20261111T141326924789Z/result.json'
DEVICE = 'evidence/phase-2/ownership-probe-device/20261111T141913580938Z/result.json'


def run(rel):
    value = arena.read_json(PROJECT / rel)
    arena.require(value['status'] == 'passed' and value['exit_code'] == 0, 'selected run unfinished: ' + rel)
    return value


def main():
    arena.require(not DEST.exists(), 'one-time documentation checkpoint already exists')
    runs = {
        'preparation': 'runs/20261111T140939323784Z-phase2-ownership-preparation/metadata.json',
        'device_preparation': 'runs/20261111T141729568054Z-phase2-ownership-device-preparation/metadata.json',
        'build': 'runs/20261111T141321024873Z-phase2-ownership-build/metadata.json',
        'device': 'runs/20261111T141913031415Z-phase2-ownership-device/metadata.json',
        'capture_binding': 'runs/20261111T142825554580Z-phase2-ownership-capture-source-binding/metadata.json',
        'replay_windows': 'runs/20261111T142931911234Z-phase2-ownership-replay-windows/metadata.json',
        'replay_wsl': 'runs/20261111T142933816801Z-phase2-ownership-replay-wsl/metadata.json',
        'guards_windows': 'runs/20261111T143055227188Z-phase2-ownership-final-corruption-guards-windows/metadata.json',
        'guards_wsl': 'runs/20261111T143146512460Z-phase2-ownership-final-corruption-guards-wsl/metadata.json'}
    for rel in runs.values():
        run(rel)
    originals = ['README.md', 'docs/STATE.md', 'docs/INDEX.md', 'docs/HANDOFF.md', 'docs/BUILD.md',
        'docs/FILE-MAP.md', 'docs/ARENA-PROBE.md', 'docs/PAYLOAD-LAYOUT.md', 'docs/ENTRY-CONTRACT.md',
        'docs/IMPLEMENTATION-LOG.md', 'state.json', '../hakios-assessment/ROADMAP.md']
    before = DEST / 'before'
    before.mkdir(parents=True)
    checkpoint = []
    for number, rel in enumerate(originals, 1):
        original = PROJECT / rel
        name = f'{number:02d}-' + original.name
        shutil.copy2(original, before / name)
        checkpoint.append({'original': str(original.resolve()), 'relative': rel, 'copy': name,
            'pin': arena.pin(before / name)})
    (before / 'index.json').write_text(json.dumps({'files': checkpoint}, indent=2) + '\n', encoding='utf-8')
    shutil.copy2(Path(__file__), DEST / 'sync.py')
    host, device = arena.read_json(PROJECT / HOST), arena.read_json(PROJECT / DEVICE)
    state = arena.read_json(PROJECT / 'state.json')
    arena.require('phase_2_ownership_probe_validation' not in state, 'state already synchronized')
    selection = state['phase_2_evidence_selection']
    packets = {}
    for label, rel in [('host', HOST), ('device', DEVICE)]:
        path = PROJECT / rel
        key = 'ownership_probe_' + label
        selection[key + '_result'] = rel
        selection[key + '_result_sha256'] = arena.pin(path)['sha256']
        selection[key + '_index_sha256'] = arena.pin(path.parent / 'index.json')['sha256']
        index = arena.read_json(path.parent / 'index.json')
        packets[label] = {'files': len(index['files']),
            'bytes': sum(v.get('bytes', v.get('size')) for v in index['files'].values())}
    sources = ['diagnostics/ownership-probe/' + name for name in
        ['Makefile', 'hakios_ownership_probe.c', 'ownership_core.h', 'test_ownership.c', 'arena_budget.h']]
    sources += ['scripts/' + name for name in ['prepare-ownership-probe.py', 'build-ownership-probe.py',
        'prepare-ownership-device.py', 'ownership_probe.py', 'test-ownership-probe-device.py',
        'register-ownership-capture.py', 'test-ownership-probe-evidence.py', 'check-ownership-probe-handoff.py',
        'update-ownership-docs.py']]
    binding = 'evidence/phase-2/ownership-probe-bindings/' + device['nonce'] + '.json'
    current = {'scope': device['scope'], 'status': 'implemented_and_verified_android_diagnostic',
        'flags': device['flags'], 'closed_lifetimes': device['closed_lifetimes'], 'device_queries': 23,
        'lifecycle_messages': 21, 'status_observations': 10, 'successful_bindings': 3, 'rejected_requests': 7,
        'native_assertions': 1408, 'native_parser_cases': 801, 'native_state_cases': 115, 'native_layout_cases': 51,
        'corruption_rejections_per_host': 44, 'module': host['module'], 'budget': host['budget'],
        'imported_crcs': host['imported_crcs'], 'taint_before': 4096, 'taint_after': 4096,
        'packet_counts': packets, 'verification_runs': runs,
        'capture_binding': binding, 'capture_binding_pin': arena.pin(PROJECT / binding),
        'source_pins': {rel: arena.pin(PROJECT / rel) for rel in sources},
        'rollback_index': (before / 'index.json').relative_to(PROJECT).as_posix(),
        'external_ownership_certificate_implemented': False, 'runtime_loader_layout_acceptance_implemented': False,
        'actual_cross_boot_device_test': False, 'documentation_consistency': 'pending'}
    state['phase_2_ownership_probe_validation'] = current
    state['active_task'] = 'phase_2_internal_android_allocation_plan_binding_verified_resolve_standalone_a51_entry_platform_logs_return'
    state['next_action'] = 'define_bounded_a51_diagnostic_adapter_execution_and_fault_contract_then_resolve_standalone_entry_cpu_dma_cache_mmu_interrupt_logs_and_return'
    (PROJECT / 'state.json').write_text(json.dumps(state, indent=2) + '\n', encoding='utf-8')
    link = '[allocation/plan diagnostic](C:/Users/Ankit/Desktop/A51/hakios-a51/docs/OWNERSHIP-PROBE.md)'
    common = ('\n\n## Executed lifetime-bound plan diagnostic (P2-016)\n\n'
        'The ' + link + ' passed on the A51: three fixed 64 KB plan bindings, seven rejected wrong/stale/released requests, '
        'ten state observations and 21 ordered kernel messages. All 23 rooted commands and the transfer succeeded. '
        'All three sequential allocations were cleared and released; Android kept the same boot and the module/file are absent. '
        'SELinux was Enforcing and existing taint stayed 4096. Native ASan/UBSan checks passed 1,408 assertions; '
        'all 17 import CRCs and exact vermagic matched. Windows/WSL replay and all 44 corruption guards per host passed.\n\n'
        'Selected host result: `' + HOST + '`. Selected device result: `' + DEVICE + '`. '
        'The fixed plan is checked inside the allocation owner under one mutex; a receipt is historical once its callback returns. '
        'No external allocation certificate, loader-layout acceptance, copied payload or standalone execution is established. '
        'Current released addresses cannot authorize future placement. Phase 1 remains complete, Phase 2 in progress, '
        'and standalone launch/platform/fault-log/return gates remain false.\n\n'
        'Next: define the bounded A51 diagnostic adapter execution/fault contract, then resolve standalone entry, '
        'CPU/MMU/cache/DMA/interrupt transitions, recoverable payload/fault logs and demonstrated return. '
        'See the new guide for exact commands, source provenance, failed offline checks and rollback.\n')
    for rel in originals:
        if rel in ['state.json', 'docs/IMPLEMENTATION-LOG.md']:
            continue
        path = PROJECT / rel
        text = path.read_text(encoding='utf-8')
        if rel in ['README.md', 'docs/STATE.md']:
            old = 'Latest result: the Android [64 KB arena diagnostic](C:/Users/Ankit/Desktop/A51/hakios-a51/docs/ARENA-PROBE.md) passed on the A51; standalone HakiOS launch remains pending.'
            arena.require(text.count(old) == 1, 'latest result anchor missing')
            text = text.replace(old, 'Latest result: the Android ' + link + ' passed on the A51; standalone HakiOS launch remains pending.')
        if rel == 'docs/STATE.md':
            old = '- Active task: host/QEMU prototype, offline runtime-observation importer and pinned entry-route source review are verified; establish the A51 launch/ownership/platform/log/return contract and implement its adapter next.'
            arena.require(text.count(old) == 1, 'active task anchor missing')
            text = text.replace(old, '- Active task: internal Android allocation checks and fixed plan binding are verified; define the bounded A51 diagnostic adapter execution/fault contract, then resolve standalone entry, platform transitions, payload/fault logs and return.')
        if rel == '../hakios-assessment/ROADMAP.md':
            old = 'No phone write or device payload execution occurred.'
            arena.require(text.count(old) == 1, 'roadmap historical-scope anchor missing')
            text = text.replace(old, 'The historical host/QEMU prototype made no phone write or device payload execution. P2-014 through P2-016 subsequently executed temporary Android allocation diagnostics with verified cleanup; standalone payload execution and the Phase 2 device gate remain unpassed.')
        path.write_text(text + common, encoding='utf-8')
    log = ('\n\n## P2-016 - Live allocation checks and fixed diagnostic plan binding\n\n'
        'Date: 11 November 2026. Purpose: prevent saved allocation logs from being used as present ownership, '
        'and test a bounded offset plan against the actual Android allocation owner under one mutex. '
        'Status: internal diagnostic implemented and verified on A51; external loader ownership and standalone Phase 2 gate remain unresolved.\n\n'
        'New files: ' + ', '.join('`' + p + '`' for p in sources) + ', `docs/OWNERSHIP-PROBE.md`. '
        'Documentation/state changed: ' + ', '.join('`' + p + '`' for p in originals) + '. '
        'Twelve exact before copies and original paths are indexed under `' + current['rollback_index'] + '`; '
        'the UTF-8 synchronization source and after hashes are retained in this milestone folder. '
        'Previous page/arena/prototype/upstream inputs and all 264 Phase 1 bundle files are preserved.\n\n'
        'Implementation: generated fixed budget SHA, fresh 128-bit kernel allocation token, exact-next sequence 1..65535, '
        'explicit-count bounded ASCII sysfs grammar, pointer/active/whole-partition/pattern checks and binding under one mutex. '
        'Release invalidates active/bound state before clear/free; failed requests do not advance state. '
        'Module sysfs attributes use exact installed callback signatures; publication is outside the callback lock and '
        'removal drains callbacks before locking. One order-4 NOWAIT/zero/NOWARN/NOMEMALLOC allocation at a time. '
        'No thread/timer/DMA/MMIO/executable memory placement or physical transition was added.\n\n'
        'Verification: selected `' + HOST + '` and `' + DEVICE + '`. Native sanitizer output: 1,408 assertions, '
        '801 parser/115 state/51 layout cases. Exact vermagic, 17 matching CRCs and unchanged original Android metadata/ten content pins. '
        'Three successful bindings, seven expected rejections, ten status observations, 21 globally ordered lifecycle logs, '
        '23 rooted commands and one transfer; all three allocations cleared/freed and module/file removed on the same Android boot. '
        'Root u:r:su:s0, SELinux Enforcing, taint 4096 to 4096. '
        'Historical span [0x88ad0000,0x88ae0000) reused with distinct identities, now released. '
        'Module SHA-256 `' + host['module']['sha256'] + '`. Packet counts: ' + json.dumps(packets, sort_keys=True) + '.\n\n'
        'Passed exact run selections: ' + ', '.join('`' + p + '`' for p in runs.values()) + '. '
        'Windows/native WSL replay passed; 44 corruption cases were rejected per host. '
        'External capture/source binding pins recorder snapshots and original host/module bytes, separately from mutable fixture indexes. '
        'Frozen capture source remains unchanged; later offline verification revisions are independently retained.\n\n'
        'Failure/recovery: static review caught incompatible kobject callback types and publication-under-lock failure-drain deadlock '
        'before the accepted build; corrected code is the only device-tested module. First recorded corruption suite '
        '`runs/20261111T142356179678Z-phase2-ownership-evidence-corruption-guards-windows/metadata.json` failed with six accepted mutations '
        '(38/44 rejected). Added external source/host association, transaction interleaving order, monotonic dmesg times and canonical numbers/boot identities; '
        'the interleaving fixture itself was corrected to preserve individual list order. Failed fixtures and nested-virtualization warnings remain preserved. '
        'No phone retest or packet mutation was needed for these replay fixes.\n\n'
        'Documentation review corrected the roadmap current-status sentence to scope its no-write statement to historical host/QEMU work and include the executed Android diagnostics; the current STATE active-task line now names the completed internal binding and remaining standalone contract. The completion checker also requires the selected successful run to invoke the ownership checker and retain its P2-016 result counts.\n\n'
        'Limits: token is public allocation identity, not authentication. Host transitions are modeled; actual cross-boot, '
        'concurrent stress, CPU fault handling/watchdog, runtime arbitrary loader-layout acceptance, standalone entry/platform handoff, '
        'persistent payload/fault logs and return after leaving Android remain unverified/unimplemented. '
        'No flash/repartition/boot/recovery/DTBO change/reboot/QEMU payload copy or XNU execution. '
        'Rollback: restore indexed before copies, revert separate new diagnostic/scripts/docs, retain all evidence/runs and Phase 1 files. '
        'No phone restore needed; ordinary cleanup passed. Never reuse released addresses or force module loading/unloading. '
        'Next: bounded diagnostic adapter execution/fault contract, then standalone A51 entry/platform/log/return implementation.\n')
    path = PROJECT / 'docs/IMPLEMENTATION-LOG.md'
    path.write_text(path.read_text(encoding='utf-8') + log, encoding='utf-8')
    guide = PROJECT / 'docs/OWNERSHIP-PROBE.md'
    guide.write_text(guide.read_text(encoding='utf-8') + '\nFinal offline checks: Windows and WSL both rejected all 44 mutations. '
        'Selected replay/guard runs are recorded in state.json and the P2-016 implementation-log entry.\n', encoding='utf-8')
    changes = {'updated': {rel: arena.pin(PROJECT / rel) for rel in originals},
        'new_files': {rel: arena.pin(PROJECT / rel) for rel in sources + ['docs/OWNERSHIP-PROBE.md']},
        'packet_counts': packets}
    (DEST / 'changes.json').write_text(json.dumps(changes, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'documentation_checkpoint': DEST.relative_to(PROJECT).as_posix(),
        'rollback_copies': len(checkpoint), 'packet_counts': packets, 'documentation_consistency': 'pending'}, sort_keys=True))


if __name__ == '__main__':
    main()
