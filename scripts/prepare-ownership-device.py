#!/usr/bin/env python3
"""One-time derivation preserving the completed arena device collector."""
import datetime as dt
import json
from pathlib import Path
import arena_probe as arena

PROJECT = Path(__file__).resolve().parents[1]


def change(source, old, new):
    arena.require(source.count(old) == 1, 'ambiguous derivation anchor: ' + old[:80])
    return source.replace(old, new)


def main():
    target = PROJECT / 'scripts/test-ownership-probe-device.py'
    arena.require(not target.exists(), 'one-time target exists')
    original = PROJECT / 'scripts/test-arena-probe-device.py'
    source = original.read_text(encoding='utf-8')
    value = source.replace('arena-probe', 'ownership-probe').replace('arena_probe', 'ownership_probe').replace('ARENA_PROBE', 'OWNERSHIP_PROBE').replace('HAKIOS_ARENA', 'HAKIOS_OWNER')
    value = value.replace('import ownership_probe as arena', 'import arena_probe as arena\nimport ownership_probe as ownership')
    value = value.replace('ownership-probe-budget.json', 'arena-probe-budget.json')
    start, end = value.index('def transaction_script('), value.index('def command_roles(')
    value = value[:start] + 'transaction_script = ownership.transaction_script\n\n\n' + value[end:]
    value = value.replace('def command_roles(normal, failure, path):', 'def command_roles(normal, second, failure, path):')
    value = value.replace('transaction_script(normal, failure, path)', 'transaction_script(normal, second, failure, path)')
    value = value.replace("normal + '|' + failure", "normal + '|' + second + '|' + failure")
    value = value.replace("command_roles(record['normal_run_id'], record['failure_run_id'], record['device_path'])",
        "command_roles(record['normal_run_id'], record['second_run_id'], record['failure_run_id'], record['device_path'])")
    value = value.replace('command_roles(normal, failure, path)', 'command_roles(normal, second, failure, path)')
    value = value.replace("normal, failure = record['normal_run_id'], record['failure_run_id']",
        "normal, second, failure = record['normal_run_id'], record['second_run_id'], record['failure_run_id']")
    value = value.replace("normal, failure = secrets.token_hex(8), secrets.token_hex(8)",
        "normal, second, failure = secrets.token_hex(8), secrets.token_hex(8), secrets.token_hex(8)")
    value = value.replace("'failure_run_id': failure", "'second_run_id': second, 'failure_run_id': failure")
    value = value.replace("closed = arena.lifetimes(logs, normal, failure)",
        "closed = ownership.reconstruct(reconstructed['transaction'][0].decode(), logs, normal, second, failure)")
    value = value.replace("record['closed_lifetimes'] = arena.lifetimes(logs.decode(), normal, failure)",
        "record['closed_lifetimes'] = ownership.reconstruct(transaction_output.decode(), logs.decode(), normal, second, failure)")
    value = value.replace('arena.flags()', 'ownership.flags()')
    start = value.index("    markers = [line for line in transaction.splitlines()")
    end = value.index("    host = arena.read_json", start)
    value = value[:start] + value[end:]
    start = value.index("    transport.require('ARENA_TRANSACTION hold_checks=2'")
    end = value.index("    transport.require(record['device_path']", start)
    value = value[:start] + value[end:]
    value = change(value, "'arena-probe-budget.json', 'ownership_probe.py', 'test-ownership-probe-device.py'", 
        "'arena-probe-budget.json', 'arena_probe.py', 'ownership_probe.py', 'test-ownership-probe-device.py'")
    value = value.replace('len(root_entries) == 8', 'len(root_entries) == 9')
    value = change(value, "shutil.copy2(PROJECT / 'scripts/ownership_probe.py', folder / 'ownership_probe.py')",
        "shutil.copy2(PROJECT / 'scripts/ownership_probe.py', folder / 'ownership_probe.py')\n"
        "    shutil.copy2(PROJECT / 'scripts/arena_probe.py', folder / 'arena_probe.py')")
    value = change(value, "for name in ['hakios_ownership_probe.c', 'arena_budget.h', 'Makefile']:",
        "for name in ['hakios_ownership_probe.c', 'arena_budget.h', 'ownership_core.h', 'test_ownership.c', 'Makefile']:")
    value = change(value, "== arena.header(budget),\n        'compiled budget binding mismatch')",
        "== arena.header(budget) + '#define OP_PLAN_SHA \\\"' + ownership.PLAN + '\\\"\\n',\n        'compiled budget binding mismatch')")
    value = change(value, "        query('transaction', transaction, timeout=35)",
        "        transaction_output = query('transaction', transaction, timeout=35)")
    value = value.replace('normal_and_failed_init_cleanup=true', 'three_lifetimes_closed=true binding_verified=true')
    target.write_text(value, encoding='utf-8')
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder = PROJECT / 'evidence/phase-2/ownership-device-preparation' / stamp
    folder.mkdir(parents=True)
    (folder / 'result.json').write_text(json.dumps({'source': arena.pin(original),
        'source_path': original.relative_to(PROJECT).as_posix(), 'output': arena.pin(target),
        'output_path': target.relative_to(PROJECT).as_posix(), 'phone_access': False}, indent=2) + '\n')
    print('OWNERSHIP_DEVICE_PREPARATION ' + folder.relative_to(PROJECT).as_posix())


if __name__ == '__main__':
    main()
