#!/usr/bin/env python3
"""Run the authorized Android page diagnostic, or verify its retained evidence.

Writes only a uniquely named .ko in /data/local/tmp; ordinary insmod/rmmod,
one order-zero page, bounded logs, and cleanup. Never forces loading, changes
SELinux, flashes, reboots, accesses hardware or launches a standalone payload.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import secrets
import shlex
import shutil

import datetime as dt
import importlib.util
import sys

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('page_probe_transport', PROJECT / 'scripts/capture-live-loader.py')
transport = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transport)
NAME = 'hakios_page_probe'
RELEASE = '4.14.357-Everline-KSUN-A51'


def pin(path):
    return transport.digest_file(path)


def write(path, obj):
    transport.write_json(path, obj)


def verify(folder):
    folder = Path(folder)
    index = json.loads((folder / 'index.json').read_text())
    for name, expected in index['files'].items():
        path = transport.inside(folder, name)
        transport.require(pin(path) == expected, 'evidence pin changed: ' + name)
    record = json.loads((folder / 'result.json').read_text())
    transport.require(record['scope'] == 'android_page_probe_device_diagnostic', 'wrong scope')
    queries = record['queries']
    reconstructed = {}
    for query in queries:
        response = (folder / query['response']).read_bytes()
        stdout, remote_exit, status = transport.decode_response(response, record['nonce'],
            query['transport_status'], query['transport_exit_code'], query['limit'])
        transport.require(stdout == (folder / query['stdout']).read_bytes() and
            remote_exit == query['exit_code'] and status == query['status'], 'remote status mismatch')
        reconstructed[query['id']] = (stdout, remote_exit, status)
    normal, failure = record['normal_run_id'], record['failure_run_id']
    logs = reconstructed['logs_after'][0].decode()
    def lifecycle(run, stages, reason):
        entries = [line.split('HAKIOS_PAGE ', 1)[1] for line in logs.splitlines()
                   if 'HAKIOS_PAGE run=' + run + ' ' in line]
        actual = [re.search(r' stage=(\w+)', line)[1] for line in entries]
        transport.require(actual == stages, 'lifecycle mismatch for ' + run)
        allocations = [re.search(r' phys=(0x[0-9a-fA-F]+) bytes=(\d+)', line) for line in entries
                       if 'stage=acquire ' in line or 'stage=release ' in line]
        transport.require(len(allocations) == 2 and all(allocations) and
            allocations[0].groups() == allocations[1].groups() and
            int(allocations[0][1], 16) % 4096 == 0 and allocations[0][2] == '4096', 'page ownership/lifetime mismatch')
        transport.require(any('stage=selfcheck zero=pass pattern=pass' in x for x in entries), 'selfcheck missing')
        transport.require('reason=' + reason in entries[-1], 'release reason mismatch')
    lifecycle(normal, ['acquire', 'selfcheck', 'loaded', 'release'], 'unload')
    lifecycle(failure, ['acquire', 'selfcheck', 'release'], 'requested_init_failure')
    for key in ['root_before', 'boot_before', 'config_before', 'release_before', 'boot_hash_before',
                'modules_before', 'modules_disabled', 'path_absent', 'module_hash', 'transaction',
                'logs_after', 'modules_after', 'boot_after', 'release_after', 'path_absent_after']:
        transport.require(reconstructed[key][1:] == (0, 'ok'), 'required command failed: ' + key)
    transport.require(reconstructed['boot_before'][0] == reconstructed['boot_after'][0], 'Android boot changed')
    transport.require(reconstructed['release_before'][0].decode().strip() == RELEASE and
        reconstructed['release_after'][0] == reconstructed['release_before'][0], 'kernel release changed')
    transport.require('uid=0' in reconstructed['root_before'][0].decode(), 'root missing')
    transport.require(reconstructed['modules_disabled'][0].strip() == b'0', 'module loading disabled')
    for key in ['modules_before', 'modules_after']:
        transport.require(not any(line.startswith(NAME + ' ') for line in reconstructed[key][0].decode().splitlines()), 'module remains loaded')
    transaction = reconstructed['transaction'][0].decode()
    transport.require('PAGE_TRANSACTION normal_load=0' in transaction and
        'PAGE_TRANSACTION normal_unload=0' in transaction and
        'PAGE_TRANSACTION failure_load=1' in transaction and
        re.search(r'^hakios_page_probe \d+ 0 - Live ', transaction, re.M), 'load/unload status or loaded record missing')
    host = json.loads((folder / 'host-build-result.json').read_text())
    transport.require(pin(folder / 'host-build-result.json') == record['host_build_result_pin'], 'copied host result differs')
    transport.require(pin(folder / 'hakios_page_probe.ko') ==
        {'size': host['module']['bytes'], 'sha256': host['module']['sha256']}, 'retained module differs from host build')
    transport.require(host['status'] == 'passed' and host['host_abi_candidate_verified'] is True, 'host candidate not verified')
    transport.require(hashlib.sha256(gzip.decompress(reconstructed['config_before'][0])).hexdigest() ==
        host['installed_association']['config_sha256'], 'current config differs from build')
    transport.require(reconstructed['boot_hash_before'][0].decode().split()[0] ==
        host['installed_association']['boot_sha256'], 'current boot image differs')
    transport.require(reconstructed['module_hash'][0].decode().split()[0] == host['module']['sha256'], 'transferred module differs')
    flags = {'module_load_verified': True, 'normal_unload_verified': True,
        'one_page_allocation_selfcheck_release_verified': True, 'failed_init_cleanup_verified': True,
        'same_android_boot_verified': True, 'diagnostic_log_retrieval_verified': True,
        'device_temporary_file_cleaned': True, 'phone_writes': True,
        'a51_loader_execution_verified': False, 'owned_payload_destination_verified': False,
        'physical_handoff_verified': False, 'fault_logging_verified': False,
        'return_after_standalone_payload_verified': False, 'no_flash_a51_launch_verified': False,
        'phase_2_device_gate_passed': False}
    transport.require(record['flags'] == flags, 'diagnostic flags do not reconstruct')
    return flags


def capture(build_folder, serial):
    build_folder = Path(build_folder)
    build = json.loads((build_folder / 'result.json').read_text())
    transport.require(build['status'] == 'passed' and build['host_abi_candidate_verified'], 'no passed host build')
    module = build_folder / 'hakios_page_probe.ko'
    transport.require(pin(module)['sha256'] == build['module']['sha256'], 'module pin mismatch')
    adb = shutil.which('adb')
    transport.require(adb and serial == 'A51_SERIAL_HERE', 'explicit authorized A51 serial required')
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder = PROJECT / 'evidence/phase-2/page-probe-device' / stamp
    folder.mkdir(parents=True)
    (folder / 'queries').mkdir()
    shutil.copy2(build_folder / 'result.json', folder / 'host-build-result.json')
    shutil.copy2(module, folder / 'hakios_page_probe.ko')
    shutil.copy2(Path(__file__), folder / Path(__file__).name)
    normal, failure = secrets.token_hex(8), secrets.token_hex(8)
    path = '/data/local/tmp/hakios-page-probe-' + normal + '.ko'
    record = {'schema_version': 1, 'scope': 'android_page_probe_device_diagnostic', 'status': 'running',
        'serial': serial, 'nonce': secrets.token_hex(16), 'normal_run_id': normal,
        'failure_run_id': failure, 'device_path': path, 'host_build': build_folder.relative_to(PROJECT).as_posix(),
        'host_build_result_pin': pin(build_folder / 'result.json'), 'queries': [], 'flags': {}}
    def query(name, command, limit=65536, timeout=20, required=True):
        argv = [adb, '-s', serial, 'exec-out', 'su -c ' + shlex.quote(transport.remote_script(command, record['nonce']))]
        meta, response, stderr = transport.run_bounded(argv, limit + 128, timeout)
        stdout, exit_code, status = transport.decode_response(response, record['nonce'], meta['status'], meta['exit_code'], limit)
        base = 'queries/' + name
        for ext, data in [('stdout', stdout), ('response', response), ('stderr', stderr)]:
            (folder / (base + '.' + ext)).write_bytes(data)
        item = dict(meta, id=name, argv=argv, command=command, limit=limit,
                    transport_status=meta['status'], transport_exit_code=meta['exit_code'],
                    exit_code=exit_code, status=status, stdout=base + '.stdout',
                    response=base + '.response', stderr=base + '.stderr')
        record['queries'].append(item)
        write(folder / 'result.json', record)
        print(name + ': remote=' + str(exit_code) + ' status=' + status, flush=True)
        if required:
            transport.require(exit_code == 0 and status == 'ok', 'device command failed: ' + name)
        return stdout
    attempted = False
    transferred = False
    try:
        transport.require(b'uid=0' in query('root_before', 'id'), 'root unavailable')
        query('security_context', 'id -Z')
        query('selinux', 'getenforce')
        query('boot_before', 'cat /proc/sys/kernel/random/boot_id')
        transport.require(query('release_before', 'uname -r').decode().strip() == RELEASE, 'current release mismatch')
        config = query('config_before', 'cat /proc/config.gz', 2 * 1024 * 1024)
        transport.require(hashlib.sha256(gzip.decompress(config)).hexdigest() == build['installed_association']['config_sha256'], 'current config mismatch')
        transport.require(query('boot_hash_before', 'sha256sum /dev/block/by-name/boot').decode().split()[0] == build['installed_association']['boot_sha256'], 'current boot mismatch')
        modules = query('modules_before', 'cat /proc/modules').decode()
        transport.require(not any(line.startswith(NAME + ' ') for line in modules.splitlines()), 'another probe already loaded')
        transport.require(query('modules_disabled', 'cat /proc/sys/kernel/modules_disabled').strip() == b'0', 'modules disabled')
        query('taint_before', 'cat /proc/sys/kernel/tainted')
        query('tools', 'command -v insmod && command -v rmmod && command -v sha256sum')
        query('path_absent', 'test ! -e ' + path)
        argv = [adb, '-s', serial, 'push', str(module), path]
        transferred = True  # A failed transport can still leave a partial file.
        meta, out, err = transport.run_bounded(argv, 65536, 30)
        record['push'] = dict(meta, argv=argv, stdout=out.decode(errors='replace'), stderr=err.decode(errors='replace'))
        transport.require(meta['exit_code'] == 0 and meta['status'] == 'ok', 'module transfer failed')
        transport.require(query('module_hash', 'sha256sum ' + path).decode().split()[0] == build['module']['sha256'], 'transferred module hash mismatch')
        transaction = f'''cleanup_page_probe() {{
 if [ -d /sys/module/{NAME} ]; then rmmod {NAME}; fi
 rm -f {path}
}}
trap cleanup_page_probe EXIT
insmod {path} run_id={normal}
page_probe_rc=$?
printf 'PAGE_TRANSACTION normal_load=%d\\n' "$page_probe_rc"
[ "$page_probe_rc" -eq 0 ] || exit 21
grep '^{NAME} ' /proc/modules || exit 22
rmmod {NAME}
page_probe_rc=$?
printf 'PAGE_TRANSACTION normal_unload=%d\\n' "$page_probe_rc"
[ "$page_probe_rc" -eq 0 ] || exit 23
insmod {path} run_id={failure} fail_after_alloc=1
page_probe_rc=$?
printf 'PAGE_TRANSACTION failure_load=%d\\n' "$page_probe_rc"
[ "$page_probe_rc" -ne 0 ] || exit 24
test ! -d /sys/module/{NAME} || exit 25'''
        attempted = True
        query('transaction', transaction, timeout=35)
        query('logs_after', "dmesg | grep -E 'HAKIOS_PAGE run=(" + normal + '|' + failure + ") '")
        query('modules_after', 'cat /proc/modules')
        query('boot_after', 'cat /proc/sys/kernel/random/boot_id')
        query('release_after', 'uname -r')
        query('taint_after', 'cat /proc/sys/kernel/tainted')
        query('path_absent_after', 'test ! -e ' + path)
        # Independent reconstruction before declaring success.
        record['flags'] = {'module_load_verified': True, 'normal_unload_verified': True,
            'one_page_allocation_selfcheck_release_verified': True, 'failed_init_cleanup_verified': True,
            'same_android_boot_verified': True, 'diagnostic_log_retrieval_verified': True,
            'device_temporary_file_cleaned': True, 'phone_writes': True,
            'a51_loader_execution_verified': False, 'owned_payload_destination_verified': False,
            'physical_handoff_verified': False, 'fault_logging_verified': False,
            'return_after_standalone_payload_verified': False, 'no_flash_a51_launch_verified': False,
            'phase_2_device_gate_passed': False}
        record['status'] = 'captured_pending_verification'
    except Exception as exc:
        record.update(status='failed', error=str(exc))
        if attempted:
            query('fallback_cleanup', 'if [ -d /sys/module/' + NAME + ' ]; then rmmod ' + NAME + ' || exit 31; fi; rm -f ' + path +
                  ' && test ! -d /sys/module/' + NAME + ' && test ! -e ' + path, required=False)
        elif transferred:
            query('fallback_file_cleanup', 'rm -f ' + path + ' && test ! -e ' + path, required=False)
        raise
    finally:
        record['finished'] = transport.stamp()
        write(folder / 'result.json', record)
        write(folder / 'index.json', {'files': {p.relative_to(folder).as_posix(): pin(p)
            for p in sorted(folder.rglob('*')) if p.is_file() and p.name != 'index.json'}})
        print('PAGE_PROBE_DEVICE ' + str(folder.relative_to(PROJECT)), flush=True)
    try:
        verify(folder)
        record['status'] = 'passed'
    except Exception as exc:
        record.update(status='failed', error=str(exc), flags={})
        raise
    finally:
        write(folder / 'result.json', record)
        write(folder / 'index.json', {'files': {p.relative_to(folder).as_posix(): pin(p)
            for p in sorted(folder.rglob('*')) if p.is_file() and p.name != 'index.json'}})
    print('PAGE_PROBE_DEVICE_VERIFIED same_android_boot=true normal_and_failed_init_cleanup=true phase2_gate=false')
    return 0


def main():
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build')
    parser.add_argument('--serial')
    parser.add_argument('--verify')
    args = parser.parse_args()
    if args.verify:
        print(json.dumps(verify(args.verify), sort_keys=True))
        return 0
    transport.require(args.build and args.serial, '--build and --serial required')
    return capture(PROJECT / args.build, args.serial)


if __name__ == '__main__':
    raise SystemExit(main())
