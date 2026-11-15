#!/usr/bin/env python3
"""Capture per-CPU EL1 state through the authorized temporary Android module.

No standalone branch, architectural-register write, MMIO, reboot or flash.
Replay validates exact commands, raw nonce footers, module bytes and logs.
"""
import argparse
import datetime as dt
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import secrets
import shlex
import shutil
import sys
import zlib

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('cpu_capture_transport', PROJECT / 'scripts/capture-live-loader.py')
transport = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transport)
NAME = 'hakios_cpu_state'
RELEASE = '4.14.357-Everline-KSUN-A51'
SCOPE = 'android_capture_only_per_cpu_architectural_state'
require = transport.require

def pin(path):
    return transport.digest_file(path)

def read(path, limit=16 * 1024 * 1024):
    require(path.is_file() and not path.is_symlink(), 'expected regular evidence file')
    with path.open('rb') as stream:
        value = stream.read(limit + 1)
    require(len(value) <= limit, 'evidence read bound')
    return value

def obj(path):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate JSON key')
            result[key] = value
        return result
    return json.loads(read(path), object_pairs_hook=pairs)

def same(first, second):
    return json.dumps(first, sort_keys=True, allow_nan=False) == json.dumps(second, sort_keys=True, allow_nan=False)

def config_data(data):
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    output = decoder.decompress(data, 2 * 1024 * 1024 + 1)
    require(len(output) <= 2 * 1024 * 1024 and decoder.eof and not decoder.unused_data,
            'bounded single gzip configuration')
    return output

def flags():
    return {'phone_queries': True, 'phone_temporary_write': True,
        'module_load_unload_verified': True, 'per_cpu_capture_verified': True,
        'same_android_boot_verified': True, 'temporary_file_absent': True,
        'architectural_register_writes': False, 'standalone_payload_execution': False,
        'physical_handoff_verified': False, 'fault_return_verified': False,
        'phase_2_device_gate_passed': False}

def commands(run, path):
    transaction = f'''cleanup_cpu_state() {{
 if [ -d /sys/module/{NAME} ]; then rmmod {NAME} || return 31; fi
 rm -f {path}
}}
trap cleanup_cpu_state EXIT
insmod {path} run_id={run}
cpu_state_rc=$?
printf 'CPU_STATE_TRANSACTION load=%d\\n' "$cpu_state_rc"
[ "$cpu_state_rc" -eq 0 ] || exit 21
grep '^{NAME} ' /proc/modules || exit 22
rmmod {NAME}
cpu_state_rc=$?
printf 'CPU_STATE_TRANSACTION unload=%d\\n' "$cpu_state_rc"
[ "$cpu_state_rc" -eq 0 ] || exit 23
rm -f {path} || exit 24
test ! -d /sys/module/{NAME} && test ! -e {path} || exit 25
trap - EXIT'''
    return {
        'root_before': 'id', 'context_before': 'id -Z', 'selinux_before': 'getenforce',
        'boot_before': 'cat /proc/sys/kernel/random/boot_id', 'release_before': 'uname -r',
        'config_before': 'cat /proc/config.gz', 'boot_hash_before': 'sha256sum /dev/block/by-name/boot',
        'online_before': 'cat /sys/devices/system/cpu/online',
        'modules_before': 'cat /proc/modules', 'disabled_before': 'cat /proc/sys/kernel/modules_disabled',
        'taint_before': 'cat /proc/sys/kernel/tainted', 'path_absent': 'test ! -e ' + path,
        'module_hash': 'sha256sum ' + path, 'transaction': transaction,
        'logs_after': "dmesg | grep 'HAKIOS_CPU run=" + run + " '",
        'modules_after': 'cat /proc/modules', 'boot_after': 'cat /proc/sys/kernel/random/boot_id',
        'online_after': 'cat /sys/devices/system/cpu/online', 'release_after': 'uname -r',
        'context_after': 'id -Z', 'selinux_after': 'getenforce',
        'taint_after': 'cat /proc/sys/kernel/tainted',
        'path_absent_after': 'test ! -e ' + path}

def cpu_list(data):
    text = data.decode().strip()
    require(re.fullmatch(r'\d+(?:-\d+)?(?:,\d+(?:-\d+)?)*', text) is not None, 'online syntax')
    result = []
    for item in text.split(','):
        ends = [int(n) for n in item.split('-')]
        low, high = ends[0], ends[-1]
        require(0 <= low <= high < 32, 'online bound')
        result.extend(range(low, high + 1))
    require(result == sorted(set(result)) and result, 'online uniqueness/order')
    return result

def cpu_records(logs, run, online):
    lines = logs.decode('utf-8').splitlines()
    entries = []
    for line in lines:
        require(line.count('HAKIOS_CPU ') == 1, 'CPU log marker')
        payload = line.split('HAKIOS_CPU ', 1)[1]
        require(payload.startswith('run=' + run + ' '), 'CPU run association')
        tokens = payload.split()
        fields = dict(token.split('=', 1) for token in tokens)
        require(len(fields) == len(tokens), 'CPU duplicate field')
        entries.append(fields)
    require(len(entries) == len(online) * 3 + 2, 'CPU log count')
    shapes = [
        ('identity', ['el', 'midr', 'mpidr', 'mmfr0', 'mmfr1']),
        ('translation', ['sctlr', 'tcr', 'ttbr0', 'ttbr1', 'mair', 'vbar']),
        ('execution', ['pc', 'sp', 'daif', 'cntfrq', 'cntvct', 'seen'])]
    records = []
    for index, cpu in enumerate(online):
        record = {'cpu': cpu}
        for n, (stage, keys) in enumerate(shapes):
            entry = entries[index * 3 + n]
            require(set(entry) == {'run', 'stage', 'cpu', *keys}, 'CPU field shape')
            require(entry['stage'] == stage and entry['cpu'] == str(cpu), 'CPU stage/order')
            for key in keys:
                require(re.fullmatch(r'[0-9a-f]{1,16}', entry[key]) is not None, 'CPU register syntax')
                record[key] = int(entry[key], 16)
        require(record['el'] == 4 and record['seen'] == 1, 'expected single EL1 sample')
        require(record['sctlr'] & 1 and record['sctlr'] & 4 and record['sctlr'] & 4096,
                'expected active MMU/data/instruction cache')
        require(record['pc'] >> 63 and record['sp'] >> 63 and record['sp'] % 16 == 0,
                'expected aligned kernel virtual execution')
        require(record['vbar'] % 2048 == 0 and record['cntfrq'] > 0, 'vectors/timer evidence')
        records.append(record)
    require(entries[-2] == {'run': run, 'stage': 'loaded', 'cpus': str(len(online)),
        'architectural_writes': '0'}, 'loaded receipt')
    require(entries[-1] == {'run': run, 'stage': 'unloaded', 'capture_cleared': '1'}, 'unloaded receipt')
    return records

def verify(folder):
    folder = Path(folder).resolve()
    index = obj(folder / 'index.json')
    names = {p.relative_to(folder).as_posix() for p in folder.rglob('*') if p.is_file() and p.name != 'index.json'}
    require(names == set(index['files']), 'exact packet enumeration')
    require(len(names) < 100, 'packet file count bound')
    for name, expected in index['files'].items():
        path = transport.inside(folder, name)
        require(pin(path) == expected, 'evidence pin changed: ' + name)
    record = obj(folder / 'result.json')
    require(record['scope'] == SCOPE and record['serial'] == 'A51_SERIAL_HERE', 'capture identity')
    require(re.fullmatch('[0-9a-f]{16}', record['run_id']) is not None, 'run token')
    require(re.fullmatch('[0-9a-f]{32}', record['nonce']) is not None, 'nonce')
    path = '/data/local/tmp/hakios-cpu-state-' + record['run_id'] + '.ko'
    require(record['device_path'] == path, 'temporary path')
    expected = commands(record['run_id'], path)
    require([q['id'] for q in record['queries']] == list(expected), 'fixed command sequence')
    outputs = {}
    for q in record['queries']:
        name = q['id']
        require(q['command'] == expected[name], 'command changed')
        require(q['limit'] == (2 * 1024 * 1024 if name == 'config_before' else 65536), 'query bound')
        argv_tail = ['-s', record['serial'], 'exec-out',
            'su -c ' + shlex.quote(transport.remote_script(q['command'], record['nonce']))]
        require(q['argv'][1:] == argv_tail, 'command argv binding')
        response = read(transport.inside(folder, q['response']), q['limit'] + 128)
        stdout, code, status = transport.decode_response(response, record['nonce'],
            q['transport_status'], q['transport_exit_code'], q['limit'])
        require(stdout == read(transport.inside(folder, q['stdout']), q['limit']), 'decoded stdout changed')
        require(type(q['exit_code']) is int and type(q['transport_exit_code']) is int and
            code == q['exit_code'] == 0 and status == q['status'] == 'ok', 'required remote success')
        outputs[name] = stdout
    host = obj(folder / 'host-build-result.json')
    require(pin(folder / 'host-build-result.json') == record['host_build_result_pin'], 'host result binding')
    require(host['status'] == 'passed' and host['host_abi_candidate_verified'] is True,
            'host build acceptance')
    require(host['scope'] == 'android_cpu_state_capture_host_build', 'host capture scope')
    require(pin(folder / (NAME + '.ko')) == {'size': host['module']['bytes'],
        'sha256': host['module']['sha256']}, 'host module binding')
    require(outputs['module_hash'].decode().split()[0] == host['module']['sha256'], 'phone module binding')
    require(record['push']['exit_code'] == 0 and record['push']['status'] == 'ok', 'transfer success')
    require(record['push']['argv'][1:3] == ['-s', record['serial']] and
        record['push']['argv'][3] == 'push' and record['push']['argv'][-1] == path, 'transfer destination')
    expanded = config_data(outputs['config_before'])
    require(len(expanded) < 2 * 1024 * 1024 and hashlib.sha256(expanded).hexdigest() ==
        host['installed_association']['config_sha256'], 'installed configuration binding')
    require(outputs['boot_hash_before'].decode().split()[0] == host['installed_association']['boot_sha256'],
            'installed boot binding')
    require(b'uid=0' in outputs['root_before'], 'root before capture')
    require(outputs['boot_before'] == outputs['boot_after'] and
        re.fullmatch(rb'[0-9a-f-]{36}\n', outputs['boot_before']) is not None, 'same Android boot')
    require(outputs['release_before'].decode().strip() == RELEASE and
        outputs['release_before'] == outputs['release_after'], 'same kernel')
    for key in ['context', 'selinux', 'taint', 'online']:
        require(outputs[key + '_before'] == outputs[key + '_after'], 'unchanged ' + key)
    require(outputs['disabled_before'].strip() == b'0', 'module loading available')
    for key in ['modules_before', 'modules_after']:
        require(not any(line.startswith(NAME + ' ') for line in outputs[key].decode().splitlines()), 'module absent')
    receipt = outputs['transaction'].decode()
    require('CPU_STATE_TRANSACTION load=0\n' in receipt and 'CPU_STATE_TRANSACTION unload=0\n' in receipt and
        re.search(r'^hakios_cpu_state \d+ 0 - Live ', receipt, re.M), 'load/live/unload receipt')
    records = cpu_records(outputs['logs_after'], record['run_id'], cpu_list(outputs['online_before']))
    require(same(record['cpu_records'], records) and same(record['flags'], flags()), 'reconstructed CPU records/flags')
    return {'flags': flags(), 'cpu_records': records, 'log_lines': len(records) * 3 + 2}

def capture(build_folder, serial):
    require(serial == 'A51_SERIAL_HERE', 'explicit authorized A51 serial')
    build_folder = Path(build_folder).resolve()
    require(build_folder.is_relative_to(PROJECT), 'project build evidence')
    build = obj(build_folder / 'result.json')
    require(build['status'] == 'passed' and build['host_abi_candidate_verified'] is True, 'passed build required')
    require(build['scope'] == 'android_cpu_state_capture_host_build', 'capture-only host build')
    for name, expected in obj(build_folder / 'index.json')['files'].items():
        actual = pin(transport.inside(build_folder, name))
        require(actual == {'size': expected['bytes'], 'sha256': expected['sha256']}, 'host packet changed')
    source = build_folder / 'module/hakios_cpu_state.c'
    require(pin(source) == pin(PROJECT / 'diagnostics/cpu-state/hakios_cpu_state.c'), 'trusted capture source binding')
    module = build_folder / (NAME + '.ko')
    require(pin(module)['sha256'] == build['module']['sha256'], 'built module binding')
    adb = shutil.which('adb')
    require(adb, 'ADB available')
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder = PROJECT / 'evidence/phase-2/cpu-state-device' / stamp
    folder.mkdir(parents=True, exist_ok=False)
    (folder / 'queries').mkdir()
    for original, target in [(build_folder / 'result.json', 'host-build-result.json'),
        (module, NAME + '.ko'), (Path(__file__), Path(__file__).name),
        (PROJECT / 'scripts/capture-live-loader.py', 'capture-live-loader.py'),
        (source, 'hakios_cpu_state.c')]:
        shutil.copy2(original, folder / target)
    run = secrets.token_hex(8)
    path = '/data/local/tmp/hakios-cpu-state-' + run + '.ko'
    record = {'schema_version': 1, 'scope': SCOPE, 'status': 'running', 'serial': serial,
        'nonce': secrets.token_hex(16), 'run_id': run, 'device_path': path,
        'host_build': build_folder.relative_to(PROJECT).as_posix(),
        'host_build_result_pin': pin(build_folder / 'result.json'),
        'started': transport.stamp(), 'queries': [], 'flags': {}, 'cpu_records': []}
    def query(name, command, required=True):
        limit = 2 * 1024 * 1024 if name == 'config_before' else 65536
        argv = [adb, '-s', serial, 'exec-out',
            'su -c ' + shlex.quote(transport.remote_script(command, record['nonce']))]
        meta, response, stderr = transport.run_bounded(argv, limit + 128, 35 if name == 'transaction' else 20)
        stdout, code, status = transport.decode_response(response, record['nonce'], meta['status'], meta['exit_code'], limit)
        base = 'queries/' + name
        for ext, data in [('stdout', stdout), ('response', response), ('stderr', stderr)]:
            (folder / (base + '.' + ext)).write_bytes(data)
        record['queries'].append(dict(meta, id=name, argv=argv, command=command, limit=limit,
            transport_status=meta['status'], transport_exit_code=meta['exit_code'],
            exit_code=code, status=status, stdout=base + '.stdout', response=base + '.response', stderr=base + '.stderr'))
        transport.write_json(folder / 'result.json', record)
        print(name + ': remote=' + str(code) + ' status=' + status, flush=True)
        if required:
            require(code == 0 and status == 'ok', 'device command failed: ' + name)
        return stdout
    transferred = False
    attempted = False
    def save():
        transport.write_json(folder / 'result.json', record)
        transport.write_json(folder / 'index.json', {'files': {p.relative_to(folder).as_posix(): pin(p)
            for p in sorted(folder.rglob('*')) if p.is_file() and p.name != 'index.json'}})
    try:
        recipe = commands(run, path)
        results = {}
        for name, command in recipe.items():
            if name == 'module_hash':
                transferred = True
                argv = [adb, '-s', serial, 'push', str(module), path]
                meta, out, err = transport.run_bounded(argv, 65536, 30)
                record['push'] = dict(meta, argv=argv, stdout=out.decode(errors='replace'), stderr=err.decode(errors='replace'))
                require(meta['exit_code'] == 0 and meta['status'] == 'ok', 'module transfer')
            if name == 'transaction':
                require(results['module_hash'].decode().split()[0] == build['module']['sha256'], 'phone module pin')
                attempted = True
            results[name] = query(name, command)
            if name == 'root_before':
                require(b'uid=0' in results[name], 'root available')
            if name == 'release_before':
                require(results[name].decode().strip() == RELEASE, 'installed release')
            if name == 'config_before':
                require(hashlib.sha256(config_data(results[name])).hexdigest() ==
                    build['installed_association']['config_sha256'], 'installed configuration')
            if name == 'boot_hash_before':
                require(results[name].decode().split()[0] == build['installed_association']['boot_sha256'], 'installed boot')
            if name == 'modules_before':
                require(not any(line.startswith(NAME + ' ') for line in results[name].decode().splitlines()), 'no existing module')
            if name == 'disabled_before':
                require(results[name].strip() == b'0', 'module loading enabled')
        record.update(status='captured_pending_verification', flags=flags(),
            cpu_records=cpu_records(results['logs_after'], run, cpu_list(results['online_before'])),
            finished=transport.stamp())
        save()
        verify(folder)
        record['status'] = 'passed'
        save()
    except Exception as exc:
        record.update(status='failed', error=str(exc), flags={})
        if transferred:
            cleanup = ('if [ -d /sys/module/' + NAME + ' ]; then rmmod ' + NAME + ' || exit 31; fi; ' if attempted else '')
            query('fallback_cleanup', cleanup + 'rm -f ' + path + ' && test ! -e ' + path, required=False)
        record['finished'] = transport.stamp()
        save()
        raise
    finally:
        print('CPU_STATE_DEVICE ' + folder.relative_to(PROJECT).as_posix(), flush=True)
    print('CPU_STATE_VERIFIED cpus=' + str(len(record['cpu_records'])) + ' standalone=false phase2_gate=false')
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
    require(args.build and args.serial, '--build and --serial required')
    return capture(PROJECT / args.build, args.serial)

if __name__ == '__main__':
    raise SystemExit(main())
