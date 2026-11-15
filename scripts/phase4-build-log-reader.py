#!/usr/bin/env python3
"""Build/test the nonce-bound Android reader against the exact installed ABI."""
from __future__ import annotations
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
from phase4_support import PROJECT, new_packet, pin, require, command, write_json, documents, index_packet

BASE = Path('/opt/a51-hakios/diagnostics/page-probe/20261111T124258280383Z')
ORIGINAL = Path('/opt/a51-everline')


def main():
    if os.name == 'nt':
        script = '/mnt/c' + str(Path(__file__).resolve()).replace('\\', '/')[2:]
        return subprocess.call(['wsl', '-d', 'A51-KernelBuilder', '--exec', 'python3', '-B', script])
    packet = new_packet('log-reader-build', __file__)
    build = Path('/opt/a51-hakios/diagnostics/phase4-log-reader') / packet.name
    build.mkdir(parents=True, exist_ok=False)
    records, result = [], {'built': False, 'device_operations': False, 'phase_4_gate_passed': False,
                          'packet': packet.relative_to(PROJECT).as_posix(), 'work': str(build)}
    spec = importlib.util.spec_from_file_location('page_build', PROJECT / 'scripts/build-page-probe.py')
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    before = helper.inventory(ORIGINAL)
    original_pins = {rel: helper.pin(ORIGINAL / 'out' / rel) for rel in helper.INPUTS}
    try:
        env = dict(os.environ, PATH='/usr/lib/llvm-18/bin:' + os.environ['PATH'])
        source = PROJECT / 'diagnostics/phase4-log-reader'
        shutil.copytree(source, build / 'module')
        shutil.copytree(source, packet / 'sources')
        shutil.copy2(PROJECT / 'scripts/phase4_capture.py', packet / 'phase4_capture.py')
        command(packet, records, 'compiler', ['clang', '--version'], env=env)
        command(packet, records, 'compile-contract-test', ['clang', '-std=c11', '-Wall', '-Wextra', '-Werror',
            '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-g', str(source / 'test_contract.c'),
            '-o', str(build / 'test-contract')], env=env)
        command(packet, records, 'run-contract-test', [str(build / 'test-contract')], env=env)
        command(packet, records, 'copy-isolated-source', ['cp', '-a', '--reflink=auto', str(BASE / 'src'), str(build / 'src')], timeout=240)
        out = build / 'out'
        out.mkdir()
        for rel in ['include', 'scripts', 'arch/arm64/include/generated']:
            target = out / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            command(packet, records, 'copy-' + rel.replace('/', '-'), ['cp', '-a', '--reflink=auto', str(BASE / 'out' / rel), str(target)], timeout=240)
        for rel in ['.config', 'Module.symvers']:
            shutil.copy2(BASE / 'out' / rel, out / rel)
            require(pin(out / rel) == original_pins[rel], 'Copied ABI input differs: ' + rel)
        module = build / 'module'
        command(packet, records, 'build-module', ['make', '-C', str(build / 'src'), 'O=' + str(out), 'M=' + str(module),
            'ARCH=arm64', 'LLVM=1', 'LLVM_IAS=1', 'CC=clang', 'LD=ld.lld', 'AR=llvm-ar', 'NM=llvm-nm',
            'OBJCOPY=llvm-objcopy', 'OBJDUMP=llvm-objdump', 'READELF=llvm-readelf',
            'CROSS_COMPILE=aarch64-linux-gnu-', 'CROSS_COMPILE_ARM32=arm-linux-gnueabi-',
            'CLANG_TRIPLE=aarch64-linux-gnu-', 'V=1', '-j2', 'modules'], timeout=240, env=env)
        ko = module / 'hakios_p4_capture.ko'
        sections = helper.elf_sections(ko.read_bytes())
        vermagic = next(s[9:] for s in sections['.modinfo'][1].decode().split('\0') if s.startswith('vermagic='))
        require(vermagic == '4.14.357-Everline-KSUN-A51 SMP preempt mod_unload modversions aarch64', 'Wrong module ABI')
        symvers = {line.split()[1]: int(line.split()[0], 16) for line in (out / 'Module.symvers').read_text().splitlines()}
        versions, imports = sections['__versions'][1], {}
        require(versions and len(versions) % 64 == 0, 'Invalid symbol versions')
        for at in range(0, len(versions), 64):
            crc = struct.unpack_from('<Q', versions, at)[0]
            name = versions[at + 8:at + 64].split(b'\0')[0].decode()
            require(name not in imports and symvers.get(name) == crc, 'Import CRC mismatch: ' + name)
            imports[name] = hex(crc)
        undefined = {line.split()[-1] for line in command(packet, records, 'undefined-symbols',
            ['llvm-nm', '--undefined-only', str(ko)], env=env).stdout.decode().splitlines() if line.strip()}
        require(undefined <= set(imports) and 'module_layout' in imports, 'Unversioned module import')
        require(before == helper.inventory(ORIGINAL) and original_pins ==
            {rel: helper.pin(ORIGINAL / 'out' / rel) for rel in helper.INPUTS}, 'Original Android tree changed')
        shutil.copy2(ko, packet / ko.name)
        result.update(built=True, original_unchanged=True, original_input_pins=original_pins, vermagic=vermagic,
            imports=imports, module={**pin(packet / ko.name), 'path': (packet / ko.name).relative_to(PROJECT).as_posix()},
            sources={p.name: pin(p) for p in source.iterdir() if p.is_file()})
    except Exception as exc:
        result['error'] = str(exc)
    finally:
        write_json(packet / 'result.json', result)
        if result['built']:
            write_json(PROJECT / 'manifests/phase4-log-reader.json', result)
        state = json.loads((PROJECT / 'state.json').read_text(encoding='utf-8'))
        state['phase_4_log_reader'] = {'result': result['packet'] + '/result.json', 'built': result['built'], 'error': result.get('error')}
        note = f"\n\n## P4-014 — Build nonce-bound binary log reader ({packet.name})\n\nPurpose/files: diagnostics/phase4-log-reader/*, scripts/phase4_capture.py, scripts/phase4-build-log-reader.py, isolated outputs, manifests/state and this log. Three fixed physical banks include the previously missed 8F copy. Records require the expected nonce before logs are copied; committed headers, full source metadata and fixed 64 KiB/400-byte capacities are checked. Saved pointers never select mappings. A second metadata read rejects unstable snapshots. Uncopied bytes are zeroed.\n\nVerification: built={result['built']}, error={result.get('error')}. Native ASan/UBSan contract checks, exact module ABI/import CRCs, Android input preservation and command/output/status/times are retained in `{result['packet']}`. Actual module execution, capture survival through reboot and peripheral validation remain pending. No phone operations.\n\nRollback/rebuild: ignore the separate module/build and restore before documents; unload hakios_p4_capture and remove its unique staging file after any device test. Original Android and Phase 3 trees remain preserved. Phase 4 is incomplete.\n"
        documents(packet, {'state.json': json.dumps(state, indent=2) + '\n',
            'docs/IMPLEMENTATION-LOG.md': (PROJECT / 'docs/IMPLEMENTATION-LOG.md').read_text(encoding='utf-8') + note})
        index_packet(packet)
    print(json.dumps({k: result.get(k) for k in ('packet', 'built', 'error', 'module')}), flush=True)
    return 0 if result['built'] else 1

if __name__ == '__main__':
    raise SystemExit(main())
