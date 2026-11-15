#!/usr/bin/env python3
"""One-time derivation of a new diagnostic; keep historical page tools intact."""
import datetime as dt
import json
from pathlib import Path
import arena_probe as arena

PROJECT = Path(__file__).resolve().parents[1]


def change(text, old, new):
    arena.require(text.count(old) == 1, 'derivation anchor missing/ambiguous: ' + old[:70])
    return text.replace(old, new)


def main():
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    evidence = PROJECT / 'evidence/phase-2/arena-probe-preparation' / stamp
    evidence.mkdir(parents=True)
    targets = ['manifests/arena-probe-budget.json', 'diagnostics/arena-probe/arena_budget.h',
               'scripts/build-arena-probe.py', 'scripts/test-arena-probe-device.py']
    arena.require(all(not (PROJECT / rel).exists() for rel in targets), 'one-time outputs already exist')
    value = arena.budget()
    builder_source = (PROJECT / 'scripts/build-page-probe.py').read_text(encoding='utf-8')
    device_source = (PROJECT / 'scripts/test-page-probe-device.py').read_text(encoding='utf-8')
    builder = builder_source.replace('page-probe', 'arena-probe').replace('page_probe', 'arena_probe').replace('PAGE_PROBE', 'ARENA_PROBE')
    builder = change(builder, 'import subprocess\n', 'import subprocess\nimport arena_probe as arena\n')
    builder = change(builder, '    before = inventory(ORIGINAL)\n',
        "    budget_path = PROJECT / 'manifests/arena-probe-budget.json'\n"
        "    budget = arena.validate_budget(arena.read_json(budget_path))\n"
        "    require((PROJECT / 'diagnostics/arena-probe/arena_budget.h').read_text(encoding='utf-8') == arena.header(budget), 'budget header drift')\n"
        "    shutil.copy2(budget_path, evidence / 'arena-probe-budget.json')\n"
        "    record['budget'] = pin(evidence / 'arena-probe-budget.json')\n"
        "    before = inventory(ORIGINAL)\n")
    device = device_source.replace('page-probe', 'arena-probe').replace('page_probe', 'arena_probe').replace('PAGE_PROBE', 'ARENA_PROBE').replace('HAKIOS_PAGE', 'HAKIOS_ARENA').replace('PAGE_TRANSACTION', 'ARENA_TRANSACTION')
    device = change(device, 'import shutil\n', 'import shutil\nimport arena_probe as arena\n')
    device = device.replace('one order-zero page', 'one 64 KiB order-four arena')
    device = device.replace('one_page_allocation_selfcheck_release_verified', 'contiguous_64k_diagnostic_lifetime_verified')
    start, end = device.index('    def lifecycle('), device.index('    for key in [', device.index('    def lifecycle('))
    device = device[:start] + "    closed = arena.lifetimes(logs, normal, failure)\n    transport.require(record['closed_lifetimes'] == closed, 'closed lifetime mismatch')\n" + device[end:]
    device = change(device, "    return flags\n",
        "    transport.require('ARENA_TRANSACTION hold_checks=2' in transaction and\n"
        "        len(re.findall(r'^hakios_arena_probe \\d+ 0 - Live ', transaction, re.M)) == 2, 'held module records missing')\n"
        "    transport.require(record['device_path'] == '/data/local/tmp/hakios-arena-probe-' + normal + '.ko', 'wrong temporary path')\n"
        "    transport.require(record['push']['status'] == 'ok' and record['push']['exit_code'] == 0, 'transfer did not succeed')\n"
        "    arena.validate_budget(arena.read_json(folder / 'arena-probe-budget.json'))\n"
        "    transport.require(arena.pin(folder / 'arena-probe-budget.json') == host['budget'], 'budget binding mismatch')\n"
        "    return flags\n")
    device = change(device, "    shutil.copy2(module, folder / 'hakios_arena_probe.ko')\n",
        "    shutil.copy2(module, folder / 'hakios_arena_probe.ko')\n"
        "    shutil.copy2(build_folder / 'arena-probe-budget.json', folder / 'arena-probe-budget.json')\n"
        "    shutil.copy2(PROJECT / 'scripts/arena_probe.py', folder / 'arena_probe.py')\n")
    device = change(device, "        query('path_absent', 'test ! -e ' + path)\n",
        "        query('meminfo_before', 'cat /proc/meminfo')\n"
        "        query('buddyinfo_before', 'cat /proc/buddyinfo')\n"
        "        query('path_absent', 'test ! -e ' + path)\n")
    device = change(device, "grep '^{NAME} ' /proc/modules || exit 22\n",
        "grep '^{NAME} ' /proc/modules || exit 22\nsleep 1\ngrep '^{NAME} ' /proc/modules || exit 26\nprintf 'ARENA_TRANSACTION hold_checks=2\\\\n'\n")
    device = change(device, "        query('logs_after',", "        logs = query('logs_after',")
    device = change(device, "        query('path_absent_after',",
        "        query('meminfo_after', 'cat /proc/meminfo')\n        query('path_absent_after',")
    device = change(device, "        record['status'] = 'captured_pending_verification'",
        "        record['closed_lifetimes'] = arena.lifetimes(logs.decode(), normal, failure)\n        record['status'] = 'captured_pending_verification'")
    (PROJECT / targets[0]).write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    (PROJECT / targets[1]).write_text(arena.header(value), encoding='utf-8')
    (PROJECT / targets[2]).write_text(builder, encoding='utf-8')
    (PROJECT / targets[3]).write_text(device, encoding='utf-8')
    record = {'created': targets, 'budget': value, 'derived_from': {
        'scripts/build-page-probe.py': arena.pin(PROJECT / 'scripts/build-page-probe.py'),
        'scripts/test-page-probe-device.py': arena.pin(PROJECT / 'scripts/test-page-probe-device.py')},
        'outputs': {rel: arena.pin(PROJECT / rel) for rel in targets}}
    (evidence / 'result.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'created': targets, 'reference': value['reference'], 'arena_bytes': value['arena_bytes'],
                      'preparation': evidence.relative_to(PROJECT).as_posix()}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
