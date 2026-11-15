#!/usr/bin/env python3
"""Run the authorized Android arena diagnostic, or verify its retained evidence.

Writes only a uniquely named .ko in /data/local/tmp; ordinary insmod/rmmod,
one 64 KiB order-four arena, bounded logs, and cleanup. Never forces loading, changes
SELinux, flashes, reboots, accesses hardware or launches a standalone payload.
"""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import secrets
import shlex
import shutil
import arena_probe as arena

import datetime as dt
import importlib.util
import sys

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('arena_probe_transport', PROJECT / 'scripts/capture-live-loader.py')
transport = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transport)
NAME = 'hakios_arena_probe'
RELEASE = '4.14.357-Everline-KSUN-A51'


def transaction_script(normal, failure, path):
    return f'''cleanup_arena_probe() {{
 if [ -d /sys/module/{NAME} ]; then rmmod {NAME}; fi
 rm -f {path}
}}
trap cleanup_arena_probe EXIT
insmod {path} run_id={normal}
arena_probe_rc=$?
printf 'ARENA_TRANSACTION normal_load=%d\\n' "$arena_probe_rc"
[ "$arena_probe_rc" -eq 0 ] || exit 21
grep '^{NAME} ' /proc/modules || exit 22
sleep 1
grep '^{NAME} ' /proc/modules || exit 26
printf 'ARENA_TRANSACTION hold_checks=2\\n'
rmmod {NAME}
arena_probe_rc=$?
printf 'ARENA_TRANSACTION normal_unload=%d\\n' "$arena_probe_rc"
[ "$arena_probe_rc" -eq 0 ] || exit 23
insmod {path} run_id={failure} fail_after_alloc=1
arena_probe_rc=$?
printf 'ARENA_TRANSACTION failure_load=%d\\n' "$arena_probe_rc"
[ "$arena_probe_rc" -ne 0 ] || exit 24
test ! -d /sys/module/{NAME} || exit 25'''


def command_roles(normal, failure, path):
    transport.require(re.fullmatch('[0-9a-f]{16}', normal) and re.fullmatch('[0-9a-f]{16}', failure)
        and normal != failure, 'invalid run identities')
    transport.require(path == '/data/local/tmp/hakios-arena-probe-' + normal + '.ko', 'wrong temporary path')
    return {'root_before': 'id', 'security_context': 'id -Z', 'selinux': 'getenforce',
        'boot_before': 'cat /proc/sys/kernel/random/boot_id', 'release_before': 'uname -r',
        'config_before': 'cat /proc/config.gz', 'boot_hash_before': 'sha256sum /dev/block/by-name/boot',
        'modules_before': 'cat /proc/modules', 'modules_disabled': 'cat /proc/sys/kernel/modules_disabled',
        'taint_before': 'cat /proc/sys/kernel/tainted',
        'tools': 'command -v insmod && command -v rmmod && command -v sha256sum',
        'meminfo_before': 'cat /proc/meminfo', 'buddyinfo_before': 'cat /proc/buddyinfo',
        'path_absent': 'test ! -e ' + path, 'module_hash': 'sha256sum ' + path,
        'transaction': transaction_script(normal, failure, path),
        'logs_after': "dmesg | grep -E 'HAKIOS_ARENA run=(" + normal + '|' + failure + ") '",
        'modules_after': 'cat /proc/modules', 'boot_after': 'cat /proc/sys/kernel/random/boot_id',
        'release_after': 'uname -r', 'taint_after': 'cat /proc/sys/kernel/tainted',
        'meminfo_after': 'cat /proc/meminfo', 'path_absent_after': 'test ! -e ' + path}


def pin(path):
    return transport.digest_file(path)


def write(path, obj):
    transport.write_json(path, obj)


def config_sha(data):
    with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
        expanded = stream.read(2 * 1024 * 1024 + 1)
    transport.require(len(expanded) <= 2 * 1024 * 1024, 'expanded config exceeds bound')
    return hashlib.sha256(expanded).hexdigest()


def verify(folder):
    folder = Path(folder)
    index = arena.read_json(folder / 'index.json')
    transport.require(len(index['files']) <= 120, 'too many packet files')
    for name, expected in index['files'].items():
        path = transport.inside(folder, name)
        transport.require(type(expected['size']) is int and path.stat().st_size <= 8 * 1024 * 1024
            and pin(path) == expected, 'evidence pin changed: ' + name)
    record = arena.read_json(folder / 'result.json')
    transport.require(record['scope'] == 'android_arena_probe_device_diagnostic' and
        record['status'] in ['captured_pending_verification', 'passed'] and
        type(record['schema_version']) is int and record['schema_version'] == 1 and
        re.fullmatch('[0-9a-f]{32}', record['nonce']), 'wrong scope/status/identity')
    queries = record['queries']
    roles = command_roles(record['normal_run_id'], record['failure_run_id'], record['device_path'])
    expected_ids = ['root_before', 'security_context', 'selinux', 'boot_before', 'release_before',
        'config_before', 'boot_hash_before', 'modules_before', 'modules_disabled', 'taint_before',
        'tools', 'meminfo_before', 'buddyinfo_before', 'path_absent', 'module_hash', 'transaction',
        'logs_after', 'modules_after', 'boot_after', 'release_after', 'taint_after', 'meminfo_after', 'path_absent_after']
    transport.require([q['id'] for q in queries] == expected_ids and record['serial'] == 'A51_SERIAL_HERE', 'query/device roles changed')
    expected_files = {'result.json', 'host-build-result.json', 'hakios_arena_probe.ko',
        'arena-probe-budget.json', 'arena_probe.py', 'test-arena-probe-device.py'} | {
        'queries/' + role + '.' + ext for role in expected_ids for ext in ['stdout', 'response', 'stderr']}
    root_entries = list(folder.iterdir())
    transport.require(len(root_entries) == 8 and all(not p.is_symlink() for p in root_entries)
        and {p.name for p in root_entries} == {name for name in expected_files if '/' not in name}
            | {'queries', 'index.json'}, 'packet root roles changed')
    query_entries = list((folder / 'queries').iterdir())
    transport.require(len(query_entries) == 69 and all(p.is_file() and not p.is_symlink() for p in query_entries)
        and set(index['files']) == expected_files
        and {'queries/' + p.name for p in query_entries} == {name for name in expected_files if '/' in name},
        'packet query file roles changed')
    reconstructed = {}
    for query in queries:
        limit = 2 * 1024 * 1024 if query['id'] == 'config_before' else 65536
        transport.require(query['command'] == roles[query['id']] and
            type(query['limit']) is int and query['limit'] == limit and
            len(query['argv']) == 5 and Path(query['argv'][0].replace('\\', '/')).name.lower() in ['adb', 'adb.exe'] and
            query['argv'][1:4] == ['-s', record['serial'], 'exec-out'] and
            query['argv'][-1] == 'su -c ' + shlex.quote(transport.remote_script(query['command'], record['nonce'])), 'command framing changed')
        transport.require(all(query[ext] == 'queries/' + query['id'] + '.' + ext
            for ext in ['stdout', 'response', 'stderr']), 'query stream role changed')
        transport.require(type(query['exit_code']) is int and type(query['transport_exit_code']) is int,
            'remote exit type changed')
        response = transport.inside(folder, query['response']).read_bytes()
        stdout, remote_exit, status = transport.decode_response(response, record['nonce'],
            query['transport_status'], query['transport_exit_code'], query['limit'])
        transport.require(stdout == transport.inside(folder, query['stdout']).read_bytes() and
            remote_exit == query['exit_code'] == 0 and status == query['status'] == 'ok', 'remote status mismatch')
        reconstructed[query['id']] = (stdout, remote_exit, status)
    normal, failure = record['normal_run_id'], record['failure_run_id']
    logs = reconstructed['logs_after'][0].decode()
    closed = arena.lifetimes(logs, normal, failure)
    transport.require(transport.canonical(record['closed_lifetimes']) == transport.canonical(closed), 'closed lifetime mismatch')
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
    markers = [line for line in transaction.splitlines() if line.startswith('ARENA_TRANSACTION ')]
    transport.require(markers == ['ARENA_TRANSACTION normal_load=0', 'ARENA_TRANSACTION hold_checks=2',
        'ARENA_TRANSACTION normal_unload=0', 'ARENA_TRANSACTION failure_load=1'] and
        re.search(r'^hakios_arena_probe \d+ 0 - Live ', transaction, re.M), 'load/unload status or loaded record missing')
    host = arena.read_json(folder / 'host-build-result.json')
    transport.require(pin(folder / 'host-build-result.json') == record['host_build_result_pin'], 'copied host result differs')
    transport.require(pin(folder / 'hakios_arena_probe.ko') ==
        {'size': host['module']['bytes'], 'sha256': host['module']['sha256']}, 'retained module differs from host build')
    transport.require(host['status'] == 'passed' and host['host_abi_candidate_verified'] is True and
        host['scope'] == 'android_arena_probe_host_build' and
        all(host[k] is False for k in ['phone_queries', 'phone_writes', 'module_load_verified',
            'a51_loader_execution_verified', 'phase_2_device_gate_passed']), 'host candidate not verified')
    transport.require(config_sha(reconstructed['config_before'][0]) ==
        host['installed_association']['config_sha256'], 'current config differs from build')
    transport.require(reconstructed['boot_hash_before'][0].decode().split()[0] ==
        host['installed_association']['boot_sha256'], 'current boot image differs')
    transport.require(reconstructed['module_hash'][0].decode().split()[0] == host['module']['sha256'], 'transferred module differs')
    flags = arena.flags()
    transport.require(transport.canonical(record['flags']) == transport.canonical(flags), 'diagnostic flags do not reconstruct')
    transport.require('ARENA_TRANSACTION hold_checks=2' in transaction and
        len(re.findall(r'^hakios_arena_probe \d+ 0 - Live ', transaction, re.M)) == 2, 'held module records missing')
    transport.require(record['device_path'] == '/data/local/tmp/hakios-arena-probe-' + normal + '.ko', 'wrong temporary path')
    transport.require(record['push']['status'] == 'ok' and type(record['push']['exit_code']) is int
        and record['push']['exit_code'] == 0, 'transfer did not succeed')
    push = record['push']['argv']
    source = push[4].replace('\\', '/') if len(push) == 6 else ''
    relative = record['host_build'] + '/hakios_arena_probe.ko'
    transport.require(len(push) == 6 and push[:4] == [queries[0]['argv'][0], '-s', record['serial'], 'push']
        and source in ['C:/Users/Ankit/Desktop/A51/hakios-a51/' + relative,
            '/mnt/c/Users/Ankit/Desktop/A51/hakios-a51/' + relative]
        and push[5] == record['device_path'], 'transfer role changed')
    ordered = queries[:14] + [record['push']] + queries[14:]
    previous_end = None
    for item in ordered:
        start, end = transport.time_pair(item['started']), transport.time_pair(item['finished'])
        transport.require(start <= end and (previous_end is None or previous_end <= start),
            'command timestamps reversed or overlapping')
        previous_end = end
    transport.require(previous_end <= transport.time_pair(record['finished']), 'record finish precedes commands')
    arena.validate_budget(arena.read_json(folder / 'arena-probe-budget.json'))
    transport.require(arena.pin(folder / 'arena-probe-budget.json') == host['budget'], 'budget binding mismatch')
    return flags


def capture(build_folder, serial):
    build_folder = Path(build_folder)
    build = arena.read_json(build_folder / 'result.json')
    transport.require(build['status'] == 'passed' and build['host_abi_candidate_verified'] is True and
        build['scope'] == 'android_arena_probe_host_build' and
        all(build[k] is False for k in ['phone_queries', 'phone_writes', 'module_load_verified',
            'a51_loader_execution_verified', 'phase_2_device_gate_passed']), 'no passed host build')
    budget = arena.validate_budget(arena.read_json(build_folder / 'arena-probe-budget.json'))
    transport.require(arena.pin(build_folder / 'arena-probe-budget.json') == build['budget'] and
        (build_folder / 'module/arena_budget.h').read_text(encoding='utf-8') == arena.header(budget),
        'compiled budget binding mismatch')
    for name in ['hakios_arena_probe.c', 'arena_budget.h', 'Makefile']:
        transport.require(arena.pin(PROJECT / 'diagnostics/arena-probe' / name) ==
            arena.pin(build_folder / 'module' / name), 'compiled source drift: ' + name)
    module = build_folder / 'hakios_arena_probe.ko'
    transport.require(pin(module)['sha256'] == build['module']['sha256'], 'module pin mismatch')
    adb = shutil.which('adb')
    transport.require(adb and serial == 'A51_SERIAL_HERE', 'explicit authorized A51 serial required')
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder = PROJECT / 'evidence/phase-2/arena-probe-device' / stamp
    folder.mkdir(parents=True)
    (folder / 'queries').mkdir()
    shutil.copy2(build_folder / 'result.json', folder / 'host-build-result.json')
    shutil.copy2(module, folder / 'hakios_arena_probe.ko')
    shutil.copy2(build_folder / 'arena-probe-budget.json', folder / 'arena-probe-budget.json')
    shutil.copy2(PROJECT / 'scripts/arena_probe.py', folder / 'arena_probe.py')
    shutil.copy2(Path(__file__), folder / Path(__file__).name)
    normal, failure = secrets.token_hex(8), secrets.token_hex(8)
    path = '/data/local/tmp/hakios-arena-probe-' + normal + '.ko'
    roles = command_roles(normal, failure, path)
    record = {'schema_version': 1, 'scope': 'android_arena_probe_device_diagnostic', 'status': 'running',
        'serial': serial, 'nonce': secrets.token_hex(16), 'normal_run_id': normal,
        'failure_run_id': failure, 'device_path': path, 'host_build': build_folder.relative_to(PROJECT).as_posix(),
        'host_build_result_pin': pin(build_folder / 'result.json'), 'queries': [], 'flags': {}}
    def query(name, command, limit=65536, timeout=20, required=True):
        if required:
            transport.require(command == roles[name], 'capture command role changed')
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
        transport.require(config_sha(config) == build['installed_association']['config_sha256'], 'current config mismatch')
        transport.require(query('boot_hash_before', 'sha256sum /dev/block/by-name/boot').decode().split()[0] == build['installed_association']['boot_sha256'], 'current boot mismatch')
        modules = query('modules_before', 'cat /proc/modules').decode()
        transport.require(not any(line.startswith(NAME + ' ') for line in modules.splitlines()), 'another probe already loaded')
        transport.require(query('modules_disabled', 'cat /proc/sys/kernel/modules_disabled').strip() == b'0', 'modules disabled')
        query('taint_before', 'cat /proc/sys/kernel/tainted')
        query('tools', 'command -v insmod && command -v rmmod && command -v sha256sum')
        query('meminfo_before', 'cat /proc/meminfo')
        query('buddyinfo_before', 'cat /proc/buddyinfo')
        query('path_absent', 'test ! -e ' + path)
        argv = [adb, '-s', serial, 'push', str(module), path]
        transferred = True  # A failed transport can still leave a partial file.
        meta, out, err = transport.run_bounded(argv, 65536, 30)
        record['push'] = dict(meta, argv=argv, stdout=out.decode(errors='replace'), stderr=err.decode(errors='replace'))
        transport.require(meta['exit_code'] == 0 and meta['status'] == 'ok', 'module transfer failed')
        transport.require(query('module_hash', 'sha256sum ' + path).decode().split()[0] == build['module']['sha256'], 'transferred module hash mismatch')
        transaction = roles['transaction']
        attempted = True
        query('transaction', transaction, timeout=35)
        logs = query('logs_after', "dmesg | grep -E 'HAKIOS_ARENA run=(" + normal + '|' + failure + ") '")
        query('modules_after', 'cat /proc/modules')
        query('boot_after', 'cat /proc/sys/kernel/random/boot_id')
        query('release_after', 'uname -r')
        query('taint_after', 'cat /proc/sys/kernel/tainted')
        query('meminfo_after', 'cat /proc/meminfo')
        query('path_absent_after', 'test ! -e ' + path)
        # Independent reconstruction before declaring success.
        record['flags'] = arena.flags()
        record['closed_lifetimes'] = arena.lifetimes(logs.decode(), normal, failure)
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
        print('ARENA_PROBE_DEVICE ' + str(folder.relative_to(PROJECT)), flush=True)
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
    print('ARENA_PROBE_DEVICE_VERIFIED same_android_boot=true normal_and_failed_init_cleanup=true phase2_gate=false')
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
