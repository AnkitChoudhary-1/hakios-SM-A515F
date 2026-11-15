#!/usr/bin/env python3
"""Build exact early payload in a synthetic QEMU harness; retain every command.

Run via scripts/run.py in WSL. No phone interfaces, original source writes,
or A51 address are used. QEMU results cannot pass Phase 2's device gate.
"""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
NAMES = ['hakios_early_entry.S', 'hakios_early_entry.h', 'harness.S', 'harness.c', 'harness.ld', 'host_test.py']
EXPECTED = [0x1010, 0x2020, 0x3030, 0x4040, 0x1818, 0x1919, 0x2020, 0x2121,
            0x2222, 0x2323, 0x2424, 0x2525, 0x2626, 0x2727, 0x2828, 0x2929, 0x3030, 0, 0xa0000000]


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    require(os.name == 'posix', 'run in A51-KernelBuilder WSL')
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    evidence = PROJECT / 'evidence/phase-2/early-entry-host' / stamp
    work = Path('/opt/a51-hakios/experimental/early-entry-host') / stamp
    evidence.mkdir(parents=True, exist_ok=False)
    work.mkdir(parents=True, exist_ok=False)
    (evidence / 'sources').mkdir()
    sources = {}
    for name in NAMES:
        data = (HERE / name).read_bytes()
        (work / name).write_bytes(data)
        (evidence / 'sources' / name).write_bytes(data)
        sources[name] = {'bytes': len(data), 'sha256': sha(data)}
    result = {'schema_version': 1, 'status': 'running', 'scope': 'synthetic-qemu-early-entry-only',
        'work': str(work), 'source_pins': sources, 'commands': [], 'cases': [],
        'phone_queries': False, 'phone_writes': False, 'a51_payload_execution_verified': False,
        'a51_return_verified': False, 'phase_2_device_gate_passed': False}
    def write():
        (evidence / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    write()
    env = dict(os.environ, PATH='/usr/lib/llvm-18/bin:' + os.environ['PATH'])
    def run(argv, name, timeout=30):
        started = dt.datetime.now(dt.timezone.utc).isoformat()
        try:
            p = subprocess.run([str(x) for x in argv], cwd=work, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
            output, code = p.stdout, p.returncode
        except subprocess.TimeoutExpired as exc:
            output, code = exc.stdout or b'', 124
        (evidence / (name + '.log')).write_bytes(output)
        result['commands'].append({'argv': [str(x) for x in argv], 'cwd': str(work),
            'started_utc': started, 'finished_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
            'timeout_seconds': timeout, 'exit_code': code, 'output': name + '.log',
            'output_sha256': sha(output)})
        write()
        require(code == 0, name + ' failed: see ' + str(evidence / (name + '.log')))
        return output
    try:
        for tool in ['clang', 'ld.lld', 'llvm-objcopy', 'llvm-nm', 'llvm-objdump', 'llvm-readelf', 'qemu-system-aarch64']:
            output = run([tool, '--version'], 'version-' + tool)
            require(output, 'missing version output')
        flags = ['--target=aarch64-none-elf', '-mcpu=cortex-a53', '-ffreestanding',
                 '-fno-builtin', '-fno-stack-protector', '-mgeneral-regs-only', '-O2',
                 '-Wall', '-Wextra', '-Werror', '-I', str(work)]
        run(['clang', *flags, '-c', 'hakios_early_entry.S', '-o', 'payload.o'], 'assemble-payload')
        run(['llvm-objdump', '-d', 'payload.o'], 'payload-disassembly')
        run(['llvm-readelf', '-SW', 'payload.o'], 'payload-sections')
        for case, expected_el in [(0, 1), (0, 2), (1, 1), (2, 1), (3, 1)]:
            tag = 'case-' + str(case) + '-el-' + str(expected_el)
            run(['clang', *flags, '-DHKE_CASE=' + str(case), '-c', 'harness.S', '-o', tag + '-start.o'], tag + '-assemble')
            run(['clang', *flags, '-DHKE_CASE=' + str(case), '-c', 'harness.c', '-o', tag + '-main.o'], tag + '-compile')
            elf = tag + '.elf'
            run(['ld.lld', '-T', 'harness.ld', '--build-id=none', 'payload.o', tag + '-start.o', tag + '-main.o', '-o', elf], tag + '-link')
            symbols = run(['llvm-nm', '--defined-only', elf], tag + '-symbols').decode()
            sym = {m[2]: int(m[0], 16) for m in re.findall(r'^([0-9a-f]+)\s+(\w)\s+(\S+)$', symbols, re.M)}
            run(['llvm-objcopy', '-O', 'binary', elf, tag + '.bin'], tag + '-binary')
            machine = 'virt,virtualization=on' if expected_el == 2 else 'virt'
            serial = run(['qemu-system-aarch64', '-machine', machine, '-cpu', 'cortex-a53',
                '-smp', '1', '-m', '64M', '-nographic', '-monitor', 'none', '-nic', 'none',
                '-no-reboot', '-kernel', tag + '.bin'], tag + '-qemu', 20).decode()
            marker = re.findall(r'^HKE_TEST_V1 case=(\d+) el=(\d+) checks=(\d+) result=(PASS|FAIL)$', serial, re.M)
            require(len(marker) == 1 and marker[0][0] == str(case) and marker[0][1] == str(expected_el)
                    and marker[0][3] == 'PASS', 'QEMU harness failed or unexpected EL: ' + tag)
            records = re.findall(r'^RECORD ([0-9a-f]{512})$', serial, re.M)
            regs = re.findall(r'^REGISTERS ([0-9a-f]{304})$', serial, re.M)
            require(len(records) == len(regs) == 1, 'serial packet bounds: ' + tag)
            words = list(struct.unpack('<32Q', bytes.fromhex(records[0])))
            require(list(struct.unpack('<19Q', bytes.fromhex(regs[0]))) == EXPECTED,
                    'independent register preservation failed: ' + tag)
            require(words[:3] == [0x31454c5241494b48, 1, 256], 'initialized header mismatch')
            if case in [2, 3]:
                require(words[3:] == [0] * 29, 'unsafe-entry path wrote record')
            else:
                require(words[5:9] == EXPECTED[:4] and words[9] == expected_el * 4, 'entry register capture')
                require(words[10:13] == [sym['stext'], sym['hakios_early_tiny_payload'], sym['hakios_early_entry_continue']], 'physical PC capture')
                require(words[13] == 0 and words[22:24] == [0x3030, 0xa0000000], 'entry SP/LR/NZCV capture')
                require(words[17] & 5 == 0 and words[19] == 4 << ((words[18] >> 16) & 15), 'cache contract')
                require(words[24:] == [0] * 8, 'reserved bytes changed')
                if case == 1:
                    require(words[3:5] == [2, 1] and words[14] & 0x3c0 == 0x340 and words[20:22] == [0, 0], 'invalid DAIF path')
                else:
                    value = EXPECTED[0] ^ EXPECTED[1] ^ EXPECTED[2] ^ EXPECTED[3] ^ words[15] ^ words[16]
                    value = ((value >> 7) | (value << 57)) & ((1 << 64) - 1)
                    require(words[3:5] == [1, 0] and words[14] & 0x3c0 == 0x3c0
                            and words[20:22] == [value, 0x3143455845494b48], 'trusted arithmetic payload result')
            result['cases'].append({'case': case, 'expected_el': expected_el, 'verified': True,
                'harness_checks': int(marker[0][2]), 'record_hex': records[0], 'registers_hex': regs[0],
                'elf_sha256': sha((work / elf).read_bytes()), 'binary_sha256': sha((work / (tag + '.bin')).read_bytes())})
            shutil.copy2(work / elf, evidence / elf)
            write()
            print('PASS ' + tag + ' checks=' + marker[0][2], flush=True)
        result['status'] = 'passed'
    except Exception as exc:
        result['status'] = 'failed'
        result['error'] = str(exc)
        raise
    finally:
        result['finished_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
        write()
        print('RESULT ' + str(evidence / 'result.json'), flush=True)


if __name__ == '__main__':
    main()
