#!/usr/bin/env python3
"""One-time isolated builder derivation; retains existing completed diagnostics."""
import datetime as dt
import json
from pathlib import Path
import arena_probe as arena

PROJECT = Path(__file__).resolve().parents[1]


def change(source, old, new):
    arena.require(source.count(old) == 1, 'ambiguous derivation anchor: ' + old[:60])
    return source.replace(old, new)


def main():
    targets = ['scripts/build-ownership-probe.py', 'diagnostics/ownership-probe/arena_budget.h']
    arena.require(all(not (PROJECT / p).exists() for p in targets), 'one-time targets already exist')
    budget_path = PROJECT / 'manifests/arena-probe-budget.json'
    budget = arena.validate_budget(arena.read_json(budget_path))
    digest = arena.pin(budget_path)['sha256']
    header = arena.header(budget) + '#define OP_PLAN_SHA "' + digest + '"\n'
    source_path = PROJECT / 'scripts/build-arena-probe.py'
    source = source_path.read_text(encoding='utf-8')
    builder = source.replace('arena-probe', 'ownership-probe').replace('arena_probe', 'ownership_probe').replace('ARENA_PROBE', 'OWNERSHIP_PROBE')
    builder = builder.replace('import ownership_probe as arena', 'import arena_probe as arena')
    builder = builder.replace('manifests/ownership-probe-budget.json', 'manifests/arena-probe-budget.json')
    builder = builder.replace('ownership-probe-budget.json', 'arena-probe-budget.json')
    builder = change(builder, "== arena.header(budget), 'budget header drift'",
        "== arena.header(budget) + '#define OP_PLAN_SHA \\\"' + arena.pin(budget_path)['sha256'] + '\\\"\\n', 'budget header drift'")
    builder = change(builder, "    compiler = command(['clang', '--version'], 'compiler').decode()\n",
        "    compiler = command(['clang', '--version'], 'compiler').decode()\n")
    builder = change(builder, "    module = build / 'module'\n    shutil.copytree(PROJECT / 'diagnostics/ownership-probe', module)\n",
        "    module = build / 'module'\n    shutil.copytree(PROJECT / 'diagnostics/ownership-probe', module)\n"
        "    native = build / 'ownership-native'\n"
        "    command(['clang', '-std=c99', '-Wall', '-Wextra', '-Werror', '-pedantic', '-O1', '-g',\n"
        "             '-fsanitize=address,undefined', '-fno-omit-frame-pointer',\n"
        "             str(module / 'test_ownership.c'), '-o', str(native)], 'native-compile')\n"
        "    command([str(native)], 'native-tests', 30)\n")
    (PROJECT / targets[0]).write_text(builder, encoding='utf-8')
    (PROJECT / targets[1]).write_text(header, encoding='utf-8')
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder = PROJECT / 'evidence/phase-2/ownership-probe-preparation' / stamp
    folder.mkdir(parents=True)
    record = {'created': targets, 'source': {'path': source_path.relative_to(PROJECT).as_posix(),
        'pin': arena.pin(source_path)}, 'budget_pin': arena.pin(budget_path),
        'outputs': {p: arena.pin(PROJECT / p) for p in targets}, 'no_phone_access': True}
    (folder / 'result.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'preparation': folder.relative_to(PROJECT).as_posix(), 'plan_sha256': digest}))


if __name__ == '__main__':
    main()
