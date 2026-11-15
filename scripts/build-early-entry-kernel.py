#!/usr/bin/env python3
"""Build the experimental entry hook in an isolated Android clone; host only."""
import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('early_kernel_inputs', PROJECT / 'scripts/build-page-probe.py')
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
from boot_formats import parse_arm64_image

def main():
    base.require(os.name == 'posix', 'run in A51-KernelBuilder')
    original = Path('/opt/a51-everline')
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    build = Path('/opt/a51-hakios/experimental/early-entry') / stamp
    build.mkdir(parents=True, exist_ok=False)
    evidence = PROJECT / 'evidence/phase-2/early-entry-kernel' / stamp
    evidence.mkdir(parents=True, exist_ok=False)
    before = base.inventory(original)
    base.write(evidence / 'original-metadata-before.json', before)
    original_pins = {rel: base.pin(original / 'out' / rel) for rel in base.INPUTS}
    sources = PROJECT / 'prototype/early-entry'
    source_pins = {p.name: base.pin(p) for p in sources.iterdir() if p.is_file()}
    record = {'schema_version': 1, 'status': 'running', 'scope': 'isolated_pre_linux_payload_kernel_host_build',
        'build_directory': str(build), 'started_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'source_lineage': '468ab8343364e4d3a267e670fa6a22fd4197a805; recorded, no verified Git HEAD',
        'prototype_source_pins': source_pins, 'original_input_pins': original_pins,
        'commands': [], 'phone_queries': False, 'phone_writes': False,
        'a51_payload_execution_verified': False, 'phase_2_device_gate_passed': False}
    env = dict(os.environ, PATH='/usr/lib/llvm-18/bin:' + os.environ['PATH'],
        KBUILD_BUILD_USER='a51-builder', KBUILD_BUILD_HOST='local')
    def save():
        base.write(evidence / 'result.json', record)
    def command(argv, label, timeout=1200):
        print('COMMAND ' + label, flush=True)
        started = dt.datetime.now(dt.timezone.utc).isoformat()
        completed = subprocess.run(argv, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
        log = label + '.log'
        (evidence / log).write_bytes(completed.stdout)
        record['commands'].append({'argv': argv, 'started_utc': started,
            'finished_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
            'exit_code': completed.returncode, 'log': log})
        save()
        base.require(completed.returncode == 0, label + ' failed: ' + log)
        return completed.stdout
    save()
    try:
        compiler = command(['clang', '--version'], 'compiler').decode()
        linker = command(['ld.lld', '--version'], 'linker').decode()
        base.require('18.1.3 (1ubuntu1)' in compiler and '18.1.3' in linker, 'toolchain version')
        base.require((original / 'out/.config').read_bytes() ==
            (PROJECT.parent / 'everline-ksu/artifacts/kernel.config').read_bytes(), 'baseline configuration')
        host_test = PROJECT / 'evidence/phase-2/early-entry-host/20261113T004009288671Z/result.json'
        record['qemu_test_result'] = {'path': host_test.relative_to(PROJECT).as_posix(), **base.pin(host_test)}
        command(['cp', '-a', '--reflink=auto', str(original / 'src'), str(build / 'src')], 'copy-source')
        command(['cp', '-a', '--reflink=auto', str(original / 'out'), str(build / 'out')], 'copy-output')
        for path in (build / 'src').rglob('.git'):
            base.require(path.is_file() and not path.is_symlink(), 'unexpected copied Git metadata')
            path.unlink()
        out = build / 'out'
        # Detach ONLY newly copied pointers that refer to the original Android source.
        for name in ['source', 'Makefile']:
            path = out / name
            base.require(path.parent.resolve().is_relative_to(build.resolve()), 'detachment target containment')
            path.unlink()
        for path in build.rglob('*'):
            if path.is_symlink():
                base.require(path.resolve().is_relative_to(build.resolve()), 'isolated symlink escape: ' + str(path))
        preparation = PROJECT / 'evidence/phase-2/early-entry-prepare' / stamp
        command([sys.executable, str(sources / 'prepare.py'), '--source', str(build / 'src'),
            '--evidence', str(preparation)], 'apply-exact-pinned-adaptation')
        record['preparation_result'] = {'path': (preparation / 'result.json').relative_to(PROJECT).as_posix(),
            **base.pin(preparation / 'result.json')}
        record['adaptation_patch'] = {'path': (preparation / 'early-entry.patch').relative_to(PROJECT).as_posix(),
            **base.pin(preparation / 'early-entry.patch')}
        argv = ['make', '-C', str(build / 'src'), 'O=' + str(out), 'ARCH=arm64',
            'LLVM=1', 'LLVM_IAS=1', 'CC=clang', 'LD=ld.lld', 'AR=llvm-ar', 'NM=llvm-nm',
            'OBJCOPY=llvm-objcopy', 'OBJDUMP=llvm-objdump', 'READELF=llvm-readelf',
            'CROSS_COMPILE=aarch64-linux-gnu-', 'CROSS_COMPILE_ARM32=arm-linux-gnueabi-',
            'CLANG_TRIPLE=aarch64-linux-gnu-', '-j4', 'Image']
        command(argv, 'build-experimental-image')
        base.require(base.pin(out / '.config') == original_pins['.config'], 'configuration changed')
        names = {'_text', '_end', '_edata', '__bss_start', 'stext', 'hakios_early_entry',
            'hakios_early_tiny_payload', 'hakios_early_entry_continue', 'hakios_early_record',
            'hakios_early_report', '__mmuoff_data_start', '__mmuoff_data_end'}
        symbols_text = command(['llvm-nm', '--defined-only', str(out / 'vmlinux')], 'symbol-map').decode()
        symbols = {line.split()[-1]: int(line.split()[0], 16) for line in symbols_text.splitlines()
            if line.split() and line.split()[-1] in names}
        base.require(names <= set(symbols), 'required linked symbols absent: ' + repr(names - set(symbols)))
        image = out / 'arch/arm64/boot/Image'
        header = parse_arm64_image(image.read_bytes())
        base.require(header['image_size'] == symbols['_end'] - symbols['_text'], 'effective Image extent')
        base.require(header['initial_branch_offset'] == symbols['stext'] - symbols['_text'], 'native header branch')
        base.require(header['text_offset'] == 0x80000 and header['flags'] == 0xa and
            header['reserved_words'][1] == '0xecefecef' and header['pe_header_offset'] == 0, 'native header convention')
        for name in ['hakios_early_entry', 'hakios_early_tiny_payload', 'hakios_early_entry_continue',
            'hakios_early_report', 'hakios_early_record']:
            base.require(symbols['_text'] <= symbols[name] < symbols['_edata'], 'file-backed prototype placement')
        base.require(symbols['__mmuoff_data_start'] <= symbols['hakios_early_record'] and
            symbols['hakios_early_record'] + 256 <= symbols['__mmuoff_data_end'] <= symbols['_edata'], 'isolated record placement')
        base.require(symbols['hakios_early_record'] % 256 == 0, 'record cache alignment')
        command(['llvm-objdump', '-d', '--disassemble-symbols=stext,hakios_early_entry,hakios_early_tiny_payload,hakios_early_report',
            str(out / 'vmlinux')], 'entry-disassembly')
        base.require(source_pins == {p.name: base.pin(p) for p in sources.iterdir() if p.is_file()},
            'prototype sources changed during build')
        shutil.copy2(image, evidence / 'Image')
        shutil.copy2(out / '.config', evidence / 'kernel.config')
        shutil.copy2(out / 'include/generated/compile.h', evidence / 'compile.h')
        shutil.copytree(sources, evidence / 'prototype', ignore=shutil.ignore_patterns('__pycache__'))
        record.update(status='passed', symbols=symbols, image_header=header,
            image=base.pin(evidence / 'Image'), retained_vmlinux={'path': str(out / 'vmlinux'), **base.pin(out / 'vmlinux')},
            host_build_verified=True, configuration_unchanged=True)
        print('EARLY_ENTRY_IMAGE_LINKED ' + str(header['stored_kernel_bytes']) + ' stored bytes', flush=True)
    except Exception as exc:
        record.update(status='failed', error=str(exc))
        raise
    finally:
        after = base.inventory(original)
        base.write(evidence / 'original-metadata-after.json', after)
        record['original_metadata_unchanged'] = before == after
        record['original_input_bytes_unchanged'] = original_pins == {rel: base.pin(original / 'out' / rel) for rel in base.INPUTS}
        record['finished_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
        save()
        base.write(evidence / 'index.json', {'files': {p.relative_to(evidence).as_posix(): base.pin(p)
            for p in sorted(evidence.rglob('*')) if p.is_file() and p.name != 'index.json'}})
        print('EARLY_ENTRY_KERNEL ' + evidence.relative_to(PROJECT).as_posix(), flush=True)
    base.require(record['original_metadata_unchanged'] and record['original_input_bytes_unchanged'],
        'original Android source/output changed')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
