#!/usr/bin/env python3
"""Run only the captured source-built artifacts and verify serial execution."""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path('/opt/a51-hakios/src/hakios-xnu-kernel')
DOCS = Path('/mnt/c/Users/Ankit/Desktop/A51/hakios-a51')


def validate_serial(serial, runner_code):
    """Accept a successful process-1 run before its expected exit panic."""
    first_panic = serial.find('panic(cpu')
    hello_start = serial.find('Hello from user space on Darwin!')
    program_output = serial[hello_start:first_panic] if 0 <= hello_start < first_panic else ''
    markers = {
        'hello': bool(program_output),
        'process_1_root': bool(re.search(r'I am process 1, uid 0, console fd [0-9]+\.', program_output)),
        # The loader prints this too. Require the user program's sysctl result.
        'kernel_version': bool(re.search(r'^kernel\.ver=2\.3\.4-hakios-darwin22\.5-g63fc2b46\r?$', program_output, re.MULTILINE)),
        'normal_init_exit': 'pid 1 exited -- no exit reason available -- (signal 0, exit 0)' in program_output,
        'user_program_before_panic': bool(program_output),
    }
    panics = re.findall(r'^panic\(cpu[^\n]*', serial, re.MULTILINE)
    # Raw hello never performs launchd's spawn handshake. XNU's prefix is
    # misleading even after hello has run and exited successfully.
    expected_panic = bool(panics) and all(
        ('initproc exited' in p or 'initproc failed to start' in p) and
        '(signal 0, exit status 0 )' in p for p in panics)
    return markers, panics, expected_panic, all(markers.values()) and expected_panic and runner_code in (0, 124)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=180)
    args = parser.parse_args()
    if not 10 <= args.seconds <= 1200:
        parser.error('seconds must be between 10 and 1200')
    manifest = json.loads((DOCS/'manifests/build-current.json').read_text())
    if manifest.get('build_exit_code') != 0:
        raise RuntimeError('latest captured build is not a completed successful build')
    artifacts = {a['path']: a for a in manifest['artifacts']}
    for relative in ('hakios-kernel', 'xnuloader/loader.efi', 'userland/hello', 'qemu/payload.bin'):
        path = ROOT/relative
        if not path.is_file() or str(path) not in artifacts:
            raise RuntimeError('missing captured source-built artifact: '+str(path))
        if hashlib.sha256(path.read_bytes()).hexdigest() != artifacts[str(path)]['sha256']:
            raise RuntimeError('artifact changed after build capture: '+str(path))
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder = DOCS/'evidence/qemu'/stamp
    folder.mkdir(parents=True)
    argv = ['bash', str(ROOT/'qemu/run.sh'), str(args.seconds)]
    env = os.environ.copy()
    # Pin this demonstration; keep payload loading via QEMU's RAM loader device.
    env.pop('QEMU_ESP', None)
    env.update(QEMU_MEM='6G', QEMU_SMP='1', QEMU_TB_MB='384',
               QEMU_EFI='/usr/share/AAVMF/AAVMF_CODE.fd',
               QEMU_VARS='/usr/share/AAVMF/AAVMF_VARS.fd')
    print('QEMU serial evidence:', folder, flush=True)
    proc = subprocess.Popen(argv, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    with (folder/'serial.log').open('wb') as log:
        for line in iter(proc.stdout.readline, b''):
            log.write(line)
            log.flush()
            readable = line.decode(errors='replace').replace('\r', '').strip()
            if any(readable.startswith(p) for p in ('UEFI firmware', '== XNULOADER', 'platform ',
                    'Darwin Kernel Version', 'Hello from', 'I am process', 'kernel.ver=', 'pid 1 exited', 'panic(cpu')):
                print(readable, flush=True)
    code = proc.wait()
    serial = (folder/'serial.log').read_text(errors='replace')
    markers, panics, expected_panic, passed = validate_serial(serial, code)
    result = {'schema_version': 1, 'started_utc': stamp, 'command': argv,
              'environment': {k: env[k] for k in ('QEMU_MEM','QEMU_SMP','QEMU_TB_MB','QEMU_EFI','QEMU_VARS')},
              'runner_exit_code': code, 'markers': markers, 'panic_lines': panics,
              'expected_init_exit_panic': expected_panic, 'passed': passed,
              'artifacts': manifest['artifacts'], 'build_snapshot': manifest['snapshot'],
              'serial_log': str(folder/'serial.log'),
              'scope': 'QEMU virt/TCG only; no A51 execution or Darwin interface validation'}
    (folder/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    (DOCS/'manifests/qemu-current.json').write_text(json.dumps(result, indent=2)+'\n')
    print('\nQEMU acceptance:', json.dumps({'passed': passed, 'exit': code, 'markers': markers,
                                           'expected_panic': expected_panic}), flush=True)
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
