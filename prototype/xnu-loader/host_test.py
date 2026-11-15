#!/usr/bin/env python3
"""Host verification test runner for XNU loader, Mach-O parser, Apple Device Tree, and boot trampoline.

Runs unit tests and QEMU ARM64 execution cases in WSL A51-KernelBuilder.
Verifies Mach-O parsing, boot_args serialization, SecureDT compatibility, and real XNU entry to Checkpoints 1 & 2.
"""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
NAMES = [
    'hakios_macho.py',
    'hakios_devicetree.py',
    'test_secure_dt.c',
    'xnu_trampoline.h',
    'xnu_trampoline.S',
    'harness.S',
    'harness.c',
    'harness.ld',
    'host_test.py',
]


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    require(os.name == 'posix', 'run in A51-KernelBuilder WSL')
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    evidence = PROJECT / 'evidence/phase-3/xnu-loader-host' / stamp
    work = Path('/opt/a51-hakios/experimental/xnu-loader-host') / stamp
    evidence.mkdir(parents=True, exist_ok=False)
    work.mkdir(parents=True, exist_ok=False)
    (evidence / 'sources').mkdir()

    sources = {}
    for name in NAMES:
        data = (HERE / name).read_bytes()
        (work / name).write_bytes(data)
        (evidence / 'sources' / name).write_bytes(data)
        sources[name] = {'bytes': len(data), 'sha256': sha(data)}

    result = {
        'schema_version': 1,
        'status': 'running',
        'scope': 'synthetic-qemu-xnu-loader-and-devicetree-only',
        'work': str(work),
        'source_pins': sources,
        'commands': [],
        'cases': [],
        'phone_queries': False,
        'phone_writes': False,
        'macho_parser_verified': False,
        'boot_args_verified': False,
        'devicetree_verified': False,
        'devicetree_bytes': 0,
        'devicetree_sha256': '',
        'xnu_checkpoint_1_verified': False,
        'xnu_checkpoint_2_verified': False,
    }

    def write():
        (evidence / 'result.json').write_text(json.dumps(result, indent=2) + '\n')

    write()

    env = dict(os.environ, PATH='/usr/lib/llvm-18/bin:' + os.environ['PATH'])

    def run(argv, name, timeout=30):
        started = dt.datetime.now(dt.timezone.utc).isoformat()
        try:
            p = subprocess.run(
                [str(x) for x in argv],
                cwd=work,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=timeout,
            )
            output, code = p.stdout, p.returncode
        except subprocess.TimeoutExpired as exc:
            output, code = exc.stdout or b'', 124

        (evidence / (name + '.log')).write_bytes(output)
        result['commands'].append({
            'argv': [str(x) for x in argv],
            'cwd': str(work),
            'started_utc': started,
            'finished_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
            'timeout_seconds': timeout,
            'exit_code': code,
            'output': name + '.log',
            'output_sha256': sha(output),
        })
        write()
        require(code == 0, name + ' failed: see ' + str(evidence / (name + '.log')))
        return output

    try:
        # Check toolchain versions
        for tool in ['clang', 'ld.lld', 'llvm-objcopy', 'llvm-objdump', 'qemu-system-aarch64']:
            output = run([tool, '--version'], 'version-' + tool)
            require(output, 'missing version output for ' + tool)

        # -------------------------------------------------------------
        # Step 1: Unit tests on hakios_macho.py
        # -------------------------------------------------------------
        sys.path.insert(0, str(work))
        from hakios_macho import MachOFile, BootArgs, BOOT_ARGS_SIZE

        kernel_path = Path('/opt/a51-hakios/src/hakios-xnu-kernel/hakios-kernel')
        require(kernel_path.is_file(), 'hakios-kernel binary missing at ' + str(kernel_path))
        kernel_bytes = kernel_path.read_bytes()

        mf = MachOFile(kernel_bytes)
        require(mf.magic == 0xFEEDFACF, 'unexpected magic')
        require(mf.entry_point_va == 0xFFFFFFF00741A4A8, 'unexpected entry VA')
        require(len(mf.segments) >= 10, 'unexpected segment count')
        slot = mf.find_loader_stub_slot()
        require(slot is not None and slot[0] == 0x4177F0, 'loader_stub_slot mismatch')
        result['macho_parser_verified'] = True

        ba = BootArgs(commandLine='-v serial=3 cpus=1 rd=md0 debug=0x144')
        ba_packed = ba.pack()
        require(len(ba_packed) == BOOT_ARGS_SIZE, f'boot_args size {len(ba_packed)} != {BOOT_ARGS_SIZE}')
        ba_unpacked = BootArgs.unpack(ba_packed)
        require(ba_unpacked.virtBase == ba.virtBase, 'virtBase mismatch')
        require(ba_unpacked.commandLine == ba.commandLine, 'cmdline mismatch')
        result['boot_args_verified'] = True
        write()

        # -------------------------------------------------------------
        # Step 2: Apple Device Tree generation & SecureDT C validation
        # -------------------------------------------------------------
        from hakios_devicetree import build_exynos9611_device_tree, DeviceTreeReader

        dt_bytes = build_exynos9611_device_tree()
        require(len(dt_bytes) > 8192, f'Device tree too small: {len(dt_bytes)}')
        (work / 'device_tree.bin').write_bytes(dt_bytes)
        (evidence / 'device_tree.bin').write_bytes(dt_bytes)
        result['devicetree_bytes'] = len(dt_bytes)
        result['devicetree_sha256'] = sha(dt_bytes)

        # Validate with python reader
        dtr = DeviceTreeReader(dt_bytes)
        require(dtr.root is not None and dtr.root['name'] == 'device-tree', 'Root node mismatch')
        require(dtr.find_node('/chosen') is not None, '/chosen missing')
        require(dtr.find_node('/arm-io/gic') is not None, '/arm-io/gic missing')
        require(dtr.find_node('/arm-io/uart0') is not None, '/arm-io/uart0 missing')

        # Compile and run test_secure_dt in C
        run(['clang', '-O2', 'test_secure_dt.c', '-o', 'test_secure_dt'], 'compile-test-secure-dt')
        run(['./test_secure_dt', 'device_tree.bin'], 'run-test-secure-dt')
        result['devicetree_verified'] = True
        write()

        # -------------------------------------------------------------
        # Step 3: Extract real XNU entry slice (28 KB) from hakios-kernel
        # -------------------------------------------------------------
        slice_base_fileoff = 0x417000  # LowExceptionVectorBase
        slice_len = 0x7000             # 28 KB
        slice_data = kernel_bytes[slice_base_fileoff : slice_base_fileoff + slice_len]
        require(slice_data[0x7F0 : 0x7F8] == b'XNULDRST', 'XNULDRST missing in extracted slice')
        (work / 'xnu_slice.bin').write_bytes(slice_data)
        (evidence / 'xnu_slice.bin').write_bytes(slice_data)

        # Create assembly wrappers for incbin
        slice_s = """/* Autogenerated slice wrapper */
.section .data.xnu_slice, "aw", %progbits
.align 12
.global xnu_slice_start
xnu_slice_start:
.incbin "xnu_slice.bin"
"""
        (work / 'xnu_slice.S').write_text(slice_s)

        dt_s = """/* Autogenerated devicetree wrapper */
.section .data.devicetree, "aw", %progbits
.balign 4096
.global dt_blob_start
dt_blob_start:
.incbin "device_tree.bin"
.global dt_blob_end
dt_blob_end:
"""
        (work / 'dt_blob.S').write_text(dt_s)

        # -------------------------------------------------------------
        # Step 4: Build & run QEMU test cases
        # -------------------------------------------------------------
        flags = [
            '--target=aarch64-none-elf',
            '-mcpu=cortex-a53',
            '-ffreestanding',
            '-fno-builtin',
            '-fno-stack-protector',
            '-mgeneral-regs-only',
            '-O2',
            '-Wall',
            '-Wextra',
            '-Werror',
            '-I', str(work),
        ]

        run(['clang', *flags, '-c', 'xnu_trampoline.S', '-o', 'xnu_trampoline.o'], 'assemble-trampoline')
        run(['clang', *flags, '-c', 'xnu_slice.S', '-o', 'xnu_slice.o'], 'assemble-slice')
        run(['clang', *flags, '-c', 'dt_blob.S', '-o', 'dt_blob.o'], 'assemble-dt-blob')

        # Test cases:
        # Case 0: Mock XNU entry (validates register passing, deviceTreeP, & return stub)
        # Case 1: Real XNU start_first_cpu -> LOADER_CHECKPOINT 1 with real Apple Device Tree
        # Case 2: Real XNU start_first_cpu -> LOADER_CHECKPOINT 2 (VBAR + OSLAR) with real Apple Device Tree
        for case in [0, 1, 2]:
            tag = f'case-{case}'
            run(
                ['clang', *flags, f'-DTEST_CASE={case}', '-c', 'harness.S', '-o', f'{tag}-start.o'],
                f'{tag}-assemble-start',
            )
            run(
                ['clang', *flags, f'-DTEST_CASE={case}', '-c', 'harness.c', '-o', f'{tag}-main.o'],
                f'{tag}-compile-main',
            )
            elf = f'{tag}.elf'
            objs = ['xnu_trampoline.o', 'dt_blob.o', f'{tag}-start.o', f'{tag}-main.o']
            if case >= 1:
                objs.append('xnu_slice.o')
            run(
                ['ld.lld', '-T', 'harness.ld', '--build-id=none', *objs, '-o', elf],
                f'{tag}-link',
            )
            run(['llvm-objcopy', '-O', 'binary', elf, f'{tag}.bin'], f'{tag}-binary')

            serial = run(
                [
                    'qemu-system-aarch64',
                    '-machine', 'virt',
                    '-cpu', 'cortex-a53',
                    '-smp', '1',
                    '-m', '256M',
                    '-nographic',
                    '-monitor', 'none',
                    '-nic', 'none',
                    '-no-reboot',
                    '-kernel', f'{tag}.bin',
                ],
                f'{tag}-qemu',
                20,
            ).decode()

            marker = re.findall(
                r'^XNU_TEST case=(\d+) el=(\d+) checks=(\d+) result=(PASS|FAIL)$',
                serial,
                re.M,
            )
            require(
                len(marker) == 1 and marker[0][0] == str(case) and marker[0][3] == 'PASS',
                f'QEMU test failed for {tag}: {serial}',
            )

            record_match = re.findall(r'^RECORD ([0-9a-f]{512})$', serial, re.M)
            require(len(record_match) == 1, f'Record packet missing in {tag}')
            record_bytes = bytes.fromhex(record_match[0])
            require(len(record_bytes) == 256, 'Record size != 256')

            # Unpack record fields
            words = list(struct.unpack('<32Q', record_bytes))
            magic, ver, rec_bytes, status, reason, code = words[:6]
            require(magic == 0x32454C5241494B48, 'Record magic mismatch')
            require(status == 4, f'Status {status} != 4 (CHECKPOINT_HIT)')
            require(reason == 2, f'Reason {reason} != 2 (CHECKPOINT)')
            expected_code = 2 if case == 2 else 1
            require(code == expected_code, f'Code {code} != {expected_code}')

            result['cases'].append({
                'case': case,
                'el': int(marker[0][1]),
                'checks': int(marker[0][2]),
                'result': marker[0][3],
                'status': status,
                'reason': reason,
                'code': code,
                'record_sha256': sha(record_bytes),
            })
            if case == 1:
                result['xnu_checkpoint_1_verified'] = True
            elif case == 2:
                result['xnu_checkpoint_2_verified'] = True
            write()

        result['status'] = 'passed'
        write()
        print('ALL HOST TESTS PASSED (Cases 0, 1, 2 + SecureDT C tests) exit 0')
        return 0

    except Exception as exc:
        result['status'] = 'failed'
        result['error'] = str(exc)
        write()
        print('HOST TEST FAILED: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
