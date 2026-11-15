#!/usr/bin/env python3
"""Apply exact pinned early-entry adaptation ONLY to an isolated WSL clone.

Run via scripts/run.py. Never compiles, configures or contacts a phone.
"""
import argparse
import datetime as dt
import difflib
import hashlib
import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
PINS = {
    'arch/arm64/kernel/head.S': 'fcf3c3937a06b1bb5a31a9b92d852f340dad3ea505ca50b4f1e9dfcef8292cf1',
    'arch/arm64/kernel/setup.c': 'eafab4dca1a22c24bd1c26fb0976eed77d639e96ceff6c6692f205911ce68b7b',
    'arch/arm64/kernel/Makefile': 'a628d655b96f4cff1432a39bf0d79cf2ff8d0d6d1545700f37064f5dcdbb834d',
}
FILES = ['hakios_early_entry.S', 'hakios_early_entry.h', 'hakios_early_report.c']


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(ok, message):
    if not ok:
        raise ValueError(message)


def once(text, old, new):
    require(text.count(old) == 1, 'patch context must occur exactly once: ' + old)
    return text.replace(old, new, 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--evidence', required=True, type=Path)
    args = parser.parse_args()
    root = args.source.resolve(strict=True)
    require(os.name == 'posix' and root.is_relative_to(Path('/opt/a51-hakios')),
            'source must resolve beneath /opt/a51-hakios; original Android tree forbidden')
    require(not root.is_relative_to(Path('/opt/a51-everline')), 'original source forbidden')
    instructions = []
    for parent in [root, *root.parents]:
        p = parent / 'AGENTS.md'
        if p.is_file():
            instructions.append({'path': str(p), 'sha256': sha(p.read_bytes())})
            print('LOCAL_INSTRUCTIONS ' + str(p) + '\n' + p.read_text())
    for rel in ['arch', 'arch/arm64', 'arch/arm64/kernel']:
        p = root / rel / 'AGENTS.md'
        if p.is_file():
            instructions.append({'path': str(p), 'sha256': sha(p.read_bytes())})
            print('LOCAL_INSTRUCTIONS ' + str(p) + '\n' + p.read_text())
    originals = {}
    for rel, expected in PINS.items():
        path = root / rel
        require(path.is_file() and not path.is_symlink(), 'source file must be regular: ' + rel)
        require(path.resolve(strict=True).is_relative_to(root), 'source path escapes isolated clone: ' + rel)
        data = path.read_bytes()
        require(sha(data) == expected, 'pinned source mismatch: ' + rel)
        originals[rel] = data
    config = root / '.config'
    config_pin = sha(config.read_bytes()) if config.is_file() else None
    updated = {rel: data.decode('utf-8') for rel, data in originals.items()}
    updated['arch/arm64/kernel/head.S'] = once(updated['arch/arm64/kernel/head.S'],
        'ENTRY(stext)\n\tbl\tpreserve_boot_args',
        'ENTRY(stext)\n\t/* Host-validated experimental diagnostic, before Linux boot-arg saving. */\n'
        '\tb\thakios_early_entry\n\t.global hakios_early_entry_continue\n'
        'hakios_early_entry_continue:\n\tbl\tpreserve_boot_args')
    updated['arch/arm64/kernel/setup.c'] = once(updated['arch/arm64/kernel/setup.c'],
        '#include <asm/mmu_context.h>\n',
        '#include <asm/mmu_context.h>\n#include "hakios_early_entry.h"\n')
    updated['arch/arm64/kernel/setup.c'] = once(updated['arch/arm64/kernel/setup.c'],
        'void __init setup_arch(char **cmdline_p)\n{\n',
        'void __init setup_arch(char **cmdline_p)\n{\n\thakios_early_report();\n')
    updated['arch/arm64/kernel/Makefile'] = once(updated['arch/arm64/kernel/Makefile'],
        '# Object file lists.\n',
        '# Object file lists.\narm64-obj-y += hakios_early_entry.o hakios_early_report.o\n')
    # The following := would overwrite an earlier +=: insert after the complete initial list.
    updated['arch/arm64/kernel/Makefile'] = updated['arch/arm64/kernel/Makefile'].replace(
        'arm64-obj-y += hakios_early_entry.o hakios_early_report.o\n', '', 1)
    updated['arch/arm64/kernel/Makefile'] = once(updated['arch/arm64/kernel/Makefile'],
        '\t\t\t   smp.o smp_spin_table.o smccc-call.o\n',
        '\t\t\t   smp.o smp_spin_table.o smccc-call.o\n'
        '\narm64-obj-y += hakios_early_entry.o hakios_early_report.o\n')
    for name in FILES:
        require((HERE / name).is_file(), 'candidate absent: ' + name)
        require((root / 'arch/arm64/kernel').resolve(strict=True).is_relative_to(root),
                'adaptation directory escapes isolated clone')
        require(not (root / 'arch/arm64/kernel' / name).exists(), 'existing adaptation: ' + name)
    evidence = args.evidence.resolve()
    require(not evidence.is_relative_to(root), 'evidence must be outside source')
    evidence.mkdir(parents=True, exist_ok=False)
    diff = ''
    changed = {}
    for rel, text in updated.items():
        original = evidence / 'original' / rel
        original.parent.mkdir(parents=True, exist_ok=True)
        original.write_bytes(originals[rel])
        data = text.encode('utf-8')
        diff += ''.join(difflib.unified_diff(originals[rel].decode().splitlines(True),
            text.splitlines(True), fromfile='a/' + rel, tofile='b/' + rel))
        (root / rel).write_bytes(data)
        changed[rel] = {'before_sha256': PINS[rel], 'after_sha256': sha(data)}
    for name in FILES:
        rel = 'arch/arm64/kernel/' + name
        data = (HERE / name).read_bytes()
        (root / rel).write_bytes(data)
        diff += ''.join(difflib.unified_diff([], data.decode().splitlines(True),
            fromfile='/dev/null', tofile='b/' + rel))
        changed[rel] = {'before_sha256': None, 'after_sha256': sha(data)}
    require((sha(config.read_bytes()) if config.is_file() else None) == config_pin,
            'source configuration changed unexpectedly')
    (evidence / 'early-entry.patch').write_text(diff, encoding='utf-8')
    report = {'schema_version': 1, 'status': 'prepared', 'scope': 'isolated-host-source-only',
        'created_utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'source': str(root),
        'source_lineage': '468ab8343364e4d3a267e670fa6a22fd4197a805; not a verified Git HEAD',
        'files': changed, 'patch_sha256': sha(diff.encode()), 'local_instructions': instructions,
        'source_config_sha256': config_pin, 'configuration_unchanged': True,
        'phone_queries': False, 'phone_writes': False, 'a51_payload_execution_verified': False,
        'phase_2_device_gate_passed': False}
    (evidence / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print('PREPARED ' + str(evidence / 'result.json'))


if __name__ == '__main__':
    main()
