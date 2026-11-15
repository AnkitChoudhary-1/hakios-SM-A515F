#!/usr/bin/env python3
"""Build a bounded read-only Android log reader in a separate HakiOS tree."""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess

PROJECT = Path(__file__).resolve().parents[1]
BASE = Path('/opt/a51-hakios/diagnostics/page-probe/20261111T124258280383Z')
ORIGINAL = Path('/opt/a51-everline')


def main() -> int:
    spec = importlib.util.spec_from_file_location('page_build', PROJECT / 'scripts/build-page-probe.py')
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    packet = PROJECT / 'evidence/phase-3/log-reader-build' / stamp
    build = Path('/opt/a51-hakios/diagnostics/phase3-log-reader') / stamp
    packet.mkdir(parents=True, exist_ok=False)
    build.mkdir(parents=True, exist_ok=False)
    before = helper.inventory(ORIGINAL)
    original_pins = {rel: helper.pin(ORIGINAL / 'out' / rel) for rel in helper.INPUTS}
    commands = []
    env = dict(os.environ, PATH='/usr/lib/llvm-18/bin:' + os.environ['PATH'])

    def run(name, argv, timeout=240):
        print('COMMAND ' + name, flush=True)
        start = dt.datetime.now(dt.timezone.utc).isoformat()
        proc = subprocess.run(argv, capture_output=True, env=env, timeout=timeout)
        (packet / (name + '.stdout')).write_bytes(proc.stdout)
        (packet / (name + '.stderr')).write_bytes(proc.stderr)
        commands.append({'name': name, 'argv': argv, 'exit_code': proc.returncode,
                         'started_utc': start, 'finished_utc': dt.datetime.now(dt.timezone.utc).isoformat()})
        if proc.returncode:
            raise RuntimeError(name + ': ' + proc.stderr.decode(errors='replace'))
        return proc.stdout

    run('compiler', ['clang', '--version'])
    run('copy-isolated-source', ['cp', '-a', '--reflink=auto', str(BASE / 'src'), str(build / 'src')])
    out = build / 'out'
    out.mkdir()
    for rel in ['include', 'scripts', 'arch/arm64/include/generated']:
        target = out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        run('copy-' + rel.replace('/', '-'), ['cp', '-a', '--reflink=auto', str(BASE / 'out' / rel), str(target)])
    for rel in ['.config', 'Module.symvers']:
        shutil.copy2(BASE / 'out' / rel, out / rel)
        if helper.pin(out / rel) != original_pins[rel]:
            raise ValueError('copied ABI input mismatch: ' + rel)
    module = build / 'module'
    shutil.copytree(PROJECT / 'diagnostics/phase3-log-reader', module)
    run('build', ['make', '-C', str(build / 'src'), 'O=' + str(out), 'M=' + str(module),
        'ARCH=arm64', 'LLVM=1', 'LLVM_IAS=1', 'CC=clang', 'LD=ld.lld',
        'AR=llvm-ar', 'NM=llvm-nm', 'OBJCOPY=llvm-objcopy', 'OBJDUMP=llvm-objdump',
        'READELF=llvm-readelf', 'CROSS_COMPILE=aarch64-linux-gnu-',
        'CROSS_COMPILE_ARM32=arm-linux-gnueabi-', 'CLANG_TRIPLE=aarch64-linux-gnu-',
        'V=1', '-j2', 'modules'])
    ko = module / 'hakios_p3_capture.ko'
    sections = helper.elf_sections(ko.read_bytes())
    modinfo = sections['.modinfo'][1].decode().split('\0')
    vermagic = next(s[9:] for s in modinfo if s.startswith('vermagic='))
    if vermagic != '4.14.357-Everline-KSUN-A51 SMP preempt mod_unload modversions aarch64':
        raise ValueError('module vermagic mismatch')
    symvers = {line.split()[1]: int(line.split()[0], 16)
               for line in (out / 'Module.symvers').read_text().splitlines()}
    versions = sections['__versions'][1]
    if not versions or len(versions) % 64:
        raise ValueError('invalid symbol versions')
    imports = {}
    for offset in range(0, len(versions), 64):
        crc = struct.unpack_from('<Q', versions, offset)[0]
        name = versions[offset + 8:offset + 64].split(b'\0')[0].decode()
        if name in imports or symvers.get(name) != crc:
            raise ValueError('import CRC mismatch: ' + name)
        imports[name] = hex(crc)
    undefined = {line.split()[-1] for line in run('undefined-symbols', ['llvm-nm', '--undefined-only', str(ko)]).decode().splitlines() if line.strip()}
    if not undefined <= set(imports) or 'module_layout' not in imports:
        raise ValueError('unversioned module import')
    if before != helper.inventory(ORIGINAL) or original_pins != {rel: helper.pin(ORIGINAL / 'out' / rel) for rel in helper.INPUTS}:
        raise ValueError('original Android tree changed')
    shutil.copy2(ko, packet / ko.name)
    shutil.copytree(module, packet / 'module', ignore=shutil.ignore_patterns('.tmp_versions'))
    (packet / 'source.py').write_bytes(Path(__file__).read_bytes())
    result = {'schema_version': 1, 'scope': 'bounded_read_only_historical_record_reader_host_build',
        'packet': str(packet.relative_to(PROJECT)), 'build': str(build), 'commands': commands,
        'original_input_pins': original_pins, 'original_unchanged': True,
        'vermagic': vermagic, 'imports': imports, 'module': helper.pin(packet / ko.name),
        'module_path': str((packet / ko.name).relative_to(PROJECT)), 'device_operations': False}
    (packet / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    (packet / 'index.json').write_text(json.dumps([
        {'path': str(p.relative_to(packet)), **helper.pin(p)} for p in sorted(packet.rglob('*')) if p.is_file()
    ], indent=2) + '\n')
    (PROJECT / 'manifests/phase3-log-reader.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'packet': result['packet'], 'module': result['module_path'],
                      'verified_imports': len(imports), 'device_operations': False}), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
