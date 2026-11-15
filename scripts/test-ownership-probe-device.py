#!/usr/bin/env python3
"""Run the authorized Android ownership diagnostic, or verify retained evidence.

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
import ownership_probe as ownership

import datetime as dt
import importlib.util
import sys

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ownership_probe_transport', PROJECT / 'scripts/capture-live-loader.py')
transport = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transport)
NAME = 'hakios_ownership_probe'
RELEASE = '4.14.357-Everline-KSUN-A51'


transaction_script = ownership.transaction_script


def command_roles(normal, second, failure, path):
    transport.require(re.fullmatch('[0-9a-f]{16}', normal) and re.fullmatch('[0-9a-f]{16}', failure)
        and normal != failure, 'invalid run identities')
    transport.require(path == '/data/local/tmp/hakios-ownership-probe-' + normal + '.ko', 'wrong temporary path')
    return {'root_before': 'id', 'security_context': 'id -Z', 'selinux': 'getenforce',
        'boot_before': 'cat /proc/sys/kernel/random/boot_id', 'release_before': 'uname -r',
        'config_before': 'cat /proc/config.gz', 'boot_hash_before': 'sha256sum /dev/block/by-name/boot',
        'modules_before': 'cat /proc/modules', 'modules_disabled': 'cat /proc/sys/kernel/modules_disabled',
        'taint_before': 'cat /proc/sys/kernel/tainted',
        'tools': 'command -v insmod && command -v rmmod && command -v sha256sum',
        'meminfo_before': 'cat /proc/meminfo', 'buddyinfo_before': 'cat /proc/buddyinfo',
        'path_absent': 'test ! -e ' + path, 'module_hash': 'sha256sum ' + path,
        'transaction': transaction_script(normal, second, failure, path),
        'logs_after': "dmesg | grep -E 'HAKIOS_OWNER run=(" + normal + '|' + second + '|' + failure + ") '",
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


def binding_values(record, folder):
    return {'scope': 'historical_ownership_capture_source_binding',
        'nonce': record['nonce'], 'serial': record['serial'],
        'normal_run_id': record['normal_run_id'], 'second_run_id': record['second_run_id'],
        'failure_run_id': record['failure_run_id'], 'host_build': record['host_build'],
        'host_build_result_pin': pin(folder / 'host-build-result.json'),
        'module': pin(folder / 'hakios_ownership_probe.ko'),
        'sources': {name: pin(folder / name) for name in
            ['arena_probe.py', 'ownership_probe.py', 'test-ownership-probe-device.py']}}


def binding_path(record):
    transport.require(re.fullmatch('[0-9a-f]{32}', record['nonce']), 'invalid binding identity')
    return PROJECT / 'evidence/phase-2/ownership-probe-bindings' / (record['nonce'] + '.json')


def register_capture_binding(folder):
    """Pin capture to its recorder snapshots outside the mutable replay packet."""
    folder = Path(folder)
    record = arena.read_json(folder / 'result.json')
    destination = binding_path(record)
    transport.require(not destination.exists(), 'capture binding already registered')
    expected_command = ['python', 'scripts/test-ownership-probe-device.py', '--build',
        record['host_build'], '--serial', record['serial']]
    first = transport.time_pair(record['queries'][0]['started'])
    last = transport.time_pair(record['queries'][-1]['finished'])
    candidates = []
    for path in (PROJECT / 'runs').glob('*/metadata.json'):
        run = arena.read_json(path)
        if run['command'] != expected_command or run['status'] not in ['passed', 'running']:
            continue
        if transport.time_pair(run['started']) <= first and (
                run['status'] == 'running' or last <= transport.time_pair(run['finished'])):
            candidates.append(path)
    transport.require(len(candidates) == 1, 'no unique capture recorder association')
    run_path = candidates[0]
    values = binding_values(record, folder)
    for name, expected in values['sources'].items():
        transport.require(pin(run_path.parent / 'project-scripts' / name) == expected,
            'capture source differs from recorder: ' + name)
    values['capture_run'] = run_path.relative_to(PROJECT).as_posix()
    destination.parent.mkdir(parents=True, exist_ok=True)
    write(destination, values)
    return destination


def verify(folder):
    folder = Path(folder)
    index = arena.read_json(folder / 'index.json')
    transport.require(len(index['files']) <= 120, 'too many packet files')
    for name, expected in index['files'].items():
        path = transport.inside(folder, name)
        transport.require(type(expected['size']) is int and path.stat().st_size <= 8 * 1024 * 1024
            and pin(path) == expected, 'evidence pin changed: ' + name)
    record = arena.read_json(folder / 'result.json')
    transport.require(record['scope'] == 'android_ownership_probe_device_diagnostic' and
        record['status'] in ['captured_pending_verification', 'passed'] and
        type(record['schema_version']) is int and record['schema_version'] == 1 and
        re.fullmatch('[0-9a-f]{32}', record['nonce']), 'wrong scope/status/identity')
    binding = arena.read_json(binding_path(record))
    expected_binding = binding_values(record, folder)
    transport.require(transport.canonical({k: v for k, v in binding.items() if k != 'capture_run'}) ==
        transport.canonical(expected_binding), 'external capture/source binding differs')
    run_path = transport.inside(PROJECT, binding['capture_run'])
    run = arena.read_json(run_path)
    transport.require(run['status'] in ['passed', 'running'] and run['command'] ==
        ['python', 'scripts/test-ownership-probe-device.py', '--build', record['host_build'], '--serial', record['serial']],
        'capture recorder role changed')
    for name, expected in binding['sources'].items():
        transport.require(pin(run_path.parent / 'project-scripts' / name) == expected, 'recorder source changed')
    transport.require(re.fullmatch(r'evidence/phase-2/ownership-probe-build/\d{8}T\d{12}Z', record['host_build']),
        'invalid original host packet path')
    original_host = transport.inside(PROJECT, record['host_build'])
    transport.require(pin(original_host / 'result.json') == binding['host_build_result_pin'] and
        pin(original_host / 'hakios_ownership_probe.ko') == binding['module'], 'original host association changed')
    queries = record['queries']
    roles = command_roles(record['normal_run_id'], record['second_run_id'], record['failure_run_id'], record['device_path'])
    expected_ids = ['root_before', 'security_context', 'selinux', 'boot_before', 'release_before',
        'config_before', 'boot_hash_before', 'modules_before', 'modules_disabled', 'taint_before',
        'tools', 'meminfo_before', 'buddyinfo_before', 'path_absent', 'module_hash', 'transaction',
        'logs_after', 'modules_after', 'boot_after', 'release_after', 'taint_after', 'meminfo_after', 'path_absent_after']
    transport.require([q['id'] for q in queries] == expected_ids and record['serial'] == 'A51_SERIAL_HERE', 'query/device roles changed')
    expected_files = {'result.json', 'host-build-result.json', 'hakios_ownership_probe.ko',
        'arena-probe-budget.json', 'arena_probe.py', 'ownership_probe.py', 'test-ownership-probe-device.py'} | {
        'queries/' + role + '.' + ext for role in expected_ids for ext in ['stdout', 'response', 'stderr']}
    root_entries = list(folder.iterdir())
    transport.require(len(root_entries) == 9 and all(not p.is_symlink() for p in root_entries)
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
    normal, second, failure = record['normal_run_id'], record['second_run_id'], record['failure_run_id']
    logs = reconstructed['logs_after'][0].decode()
    closed = ownership.reconstruct(reconstructed['transaction'][0].decode(), logs, normal, second, failure)
    transport.require(transport.canonical(record['closed_lifetimes']) == transport.canonical(closed), 'closed lifetime mismatch')
    for key in ['root_before', 'boot_before', 'config_before', 'release_before', 'boot_hash_before',
                'modules_before', 'modules_disabled', 'path_absent', 'module_hash', 'transaction',
                'logs_after', 'modules_after', 'boot_after', 'release_after', 'path_absent_after']:
        transport.require(reconstructed[key][1:] == (0, 'ok'), 'required command failed: ' + key)
    transport.require(reconstructed['boot_before'][0] == reconstructed['boot_after'][0], 'Android boot changed')
    transport.require(re.fullmatch(rb'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\n',
        reconstructed['boot_before'][0]), 'invalid Android boot identity')
    transport.require(reconstructed['release_before'][0].decode().strip() == RELEASE and
        reconstructed['release_after'][0] == reconstructed['release_before'][0], 'kernel release changed')
    transport.require(re.match(rb'^uid=0(?:\([^\n )]+\))? ', reconstructed['root_before'][0]), 'root missing')
    transport.require(reconstructed['modules_disabled'][0].strip() == b'0', 'module loading disabled')
    for key in ['modules_before', 'modules_after']:
        transport.require(not any(line.startswith(NAME + ' ') for line in reconstructed[key][0].decode().splitlines()), 'module remains loaded')
    transaction = reconstructed['transaction'][0].decode()
    host = arena.read_json(folder / 'host-build-result.json')
    transport.require(pin(folder / 'host-build-result.json') == record['host_build_result_pin'], 'copied host result differs')
    transport.require(pin(folder / 'hakios_ownership_probe.ko') ==
        {'size': host['module']['bytes'], 'sha256': host['module']['sha256']}, 'retained module differs from host build')
    transport.require(host['status'] == 'passed' and host['host_abi_candidate_verified'] is True and
        host['scope'] == 'android_ownership_probe_host_build' and
        all(host[k] is False for k in ['phone_queries', 'phone_writes', 'module_load_verified',
            'a51_loader_execution_verified', 'phase_2_device_gate_passed']), 'host candidate not verified')
    transport.require(config_sha(reconstructed['config_before'][0]) ==
        host['installed_association']['config_sha256'], 'current config differs from build')
    transport.require(reconstructed['boot_hash_before'][0].decode().split()[0] ==
        host['installed_association']['boot_sha256'], 'current boot image differs')
    transport.require(reconstructed['module_hash'][0].decode().split()[0] == host['module']['sha256'], 'transferred module differs')
    flags = ownership.flags()
    transport.require(transport.canonical(record['flags']) == transport.canonical(flags), 'diagnostic flags do not reconstruct')
    transport.require(record['device_path'] == '/data/local/tmp/hakios-ownership-probe-' + normal + '.ko', 'wrong temporary path')
    transport.require(record['push']['status'] == 'ok' and type(record['push']['exit_code']) is int
        and record['push']['exit_code'] == 0, 'transfer did not succeed')
    push = record['push']['argv']
    source = push[4].replace('\\', '/') if len(push) == 6 else ''
    relative = record['host_build'] + '/hakios_ownership_probe.ko'
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
    transport.require(host['budget']['sha256'] == ownership.PLAN, 'compiled plan digest differs')
    return flags


def capture(build_folder, serial):
    build_folder = Path(build_folder)
    build = arena.read_json(build_folder / 'result.json')
    transport.require(build['status'] == 'passed' and build['host_abi_candidate_verified'] is True and
        build['scope'] == 'android_ownership_probe_host_build' and
        all(build[k] is False for k in ['phone_queries', 'phone_writes', 'module_load_verified',
            'a51_loader_execution_verified', 'phase_2_device_gate_passed']), 'no passed host build')
    budget = arena.validate_budget(arena.read_json(build_folder / 'arena-probe-budget.json'))
    transport.require(arena.pin(build_folder / 'arena-probe-budget.json') == build['budget'] and
        (build_folder / 'module/arena_budget.h').read_text(encoding='utf-8') == arena.header(budget) + '#define OP_PLAN_SHA \"' + ownership.PLAN + '\"\n',
        'compiled budget binding mismatch')
    for name in ['hakios_ownership_probe.c', 'arena_budget.h', 'ownership_core.h', 'test_ownership.c', 'Makefile']:
        transport.require(arena.pin(PROJECT / 'diagnostics/ownership-probe' / name) ==
            arena.pin(build_folder / 'module' / name), 'compiled source drift: ' + name)
    module = build_folder / 'hakios_ownership_probe.ko'
    transport.require(pin(module)['sha256'] == build['module']['sha256'], 'module pin mismatch')
    adb = shutil.which('adb')
    transport.require(adb and serial == 'A51_SERIAL_HERE', 'explicit authorized A51 serial required')
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder = PROJECT / 'evidence/phase-2/ownership-probe-device' / stamp
    folder.mkdir(parents=True)
    (folder / 'queries').mkdir()
    shutil.copy2(build_folder / 'result.json', folder / 'host-build-result.json')
    shutil.copy2(module, folder / 'hakios_ownership_probe.ko')
    shutil.copy2(build_folder / 'arena-probe-budget.json', folder / 'arena-probe-budget.json')
    shutil.copy2(PROJECT / 'scripts/ownership_probe.py', folder / 'ownership_probe.py')
    shutil.copy2(PROJECT / 'scripts/arena_probe.py', folder / 'arena_probe.py')
    shutil.copy2(Path(__file__), folder / Path(__file__).name)
    normal, second, failure = secrets.token_hex(8), secrets.token_hex(8), secrets.token_hex(8)
    path = '/data/local/tmp/hakios-ownership-probe-' + normal + '.ko'
    roles = command_roles(normal, second, failure, path)
    record = {'schema_version': 1, 'scope': 'android_ownership_probe_device_diagnostic', 'status': 'running',
        'serial': serial, 'nonce': secrets.token_hex(16), 'normal_run_id': normal,
        'second_run_id': second, 'failure_run_id': failure, 'device_path': path, 'host_build': build_folder.relative_to(PROJECT).as_posix(),
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
        transaction_output = query('transaction', transaction, timeout=35)
        logs = query('logs_after', "dmesg | grep -E 'HAKIOS_OWNER run=(" + normal + '|' + second + '|' + failure + ") '")
        query('modules_after', 'cat /proc/modules')
        query('boot_after', 'cat /proc/sys/kernel/random/boot_id')
        query('release_after', 'uname -r')
        query('taint_after', 'cat /proc/sys/kernel/tainted')
        query('meminfo_after', 'cat /proc/meminfo')
        query('path_absent_after', 'test ! -e ' + path)
        # Independent reconstruction before declaring success.
        record['flags'] = ownership.flags()
        record['closed_lifetimes'] = ownership.reconstruct(transaction_output.decode(), logs.decode(), normal, second, failure)
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
        print('OWNERSHIP_PROBE_DEVICE ' + str(folder.relative_to(PROJECT)), flush=True)
    try:
        register_capture_binding(folder)
        verify(folder)
        record['status'] = 'passed'
    except Exception as exc:
        record.update(status='failed', error=str(exc), flags={})
        raise
    finally:
        write(folder / 'result.json', record)
        write(folder / 'index.json', {'files': {p.relative_to(folder).as_posix(): pin(p)
            for p in sorted(folder.rglob('*')) if p.is_file() and p.name != 'index.json'}})
    print('OWNERSHIP_PROBE_DEVICE_VERIFIED same_android_boot=true three_lifetimes_closed=true binding_verified=true phase2_gate=false')
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
