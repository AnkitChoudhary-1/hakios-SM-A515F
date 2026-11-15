#!/usr/bin/env python3
"""Offline replay and retained corruption fixtures; never contacts the phone."""
import argparse
import datetime as dt
import gzip
import importlib.util
import json
from pathlib import Path
import shlex
import shutil
import arena_probe as arena

PROJECT = arena.PROJECT
spec = importlib.util.spec_from_file_location('arena_device_guards', PROJECT / 'scripts/test-arena-probe-device.py')
device = importlib.util.module_from_spec(spec)
spec.loader.exec_module(device)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packet', required=True)
    args = parser.parse_args()
    original = Path(args.packet)
    if not original.is_absolute():
        original = PROJECT / original
    device.verify(original)
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    output = PROJECT / 'evidence/phase-2/arena-probe-corruption' / stamp
    output.mkdir(parents=True, exist_ok=False)
    checks = []

    def check(name, mutate, repin=True):
        folder = output / name
        shutil.copytree(original, folder)
        record = arena.read_json(folder / 'result.json')
        mutate(folder, record)
        device.write(folder / 'result.json', record)
        if repin:
            device.write(folder / 'index.json', {'files': {p.relative_to(folder).as_posix(): device.pin(p)
                for p in sorted(folder.rglob('*')) if p.is_file() and p.name != 'index.json'}})
        try:
            device.verify(folder)
        except (ValueError, KeyError, TypeError) as exc:
            checks.append({'case': name, 'rejected': True, 'reason': str(exc)})
            print('REJECTED ' + name + ': ' + str(exc), flush=True)
        else:
            raise AssertionError('corruption accepted: ' + name)

    def flag(folder, r):
        r['flags']['phase_2_device_gate_passed'] = True

    def active(folder, r):
        r['closed_lifetimes'][0]['active_owned_interval'] = True

    def command(folder, r):
        q = r['queries'][0]
        q['command'] = 'id; uname -r'
        q['argv'][-1] = 'su -c ' + shlex.quote(device.transport.remote_script(q['command'], r['nonce']))

    def hold(folder, r):
        q = next(q for q in r['queries'] if q['id'] == 'transaction')
        q['command'] = q['command'].replace('sleep 1', ':')
        q['argv'][-1] = 'su -c ' + shlex.quote(device.transport.remote_script(q['command'], r['nonce']))

    def argv(folder, r):
        r['queries'][0]['argv'][2] = 'another-device'

    def transfer(folder, r):
        r['push']['argv'][5] = '/data/local/tmp/another.ko'

    def status(folder, r):
        r['queries'][0]['exit_code'] = 1

    def stream(folder, r):
        r['queries'][0]['stdout'] = r['queries'][1]['stdout']

    def log_change(old, new):
        def mutate(folder, r):
            q = next(q for q in r['queries'] if q['id'] == 'logs_after')
            for key in ['stdout', 'response']:
                path = folder / q[key]
                data = path.read_bytes()
                assert old in data
                path.write_bytes(data.replace(old, new, 1))
        return mutate

    def module(folder, r):
        path = folder / 'hakios_arena_probe.ko'
        path.write_bytes(path.read_bytes() + b'changed')

    def budget(folder, r):
        path = folder / 'arena-probe-budget.json'
        value = arena.read_json(path)
        value['regions'][1]['bytes'] += 4096
        device.write(path, value)

    def host_gate(folder, r):
        path = folder / 'host-build-result.json'
        value = arena.read_json(path)
        value['phase_2_device_gate_passed'] = True
        device.write(path, value)
        r['host_build_result_pin'] = device.pin(path)

    def config_bomb(folder, r):
        q = next(q for q in r['queries'] if q['id'] == 'config_before')
        path = folder / q['stdout']
        old = path.read_bytes()
        new = gzip.compress(b'x' * (2 * 1024 * 1024 + 1))
        response = folder / q['response']
        data = response.read_bytes()
        assert data.startswith(old)
        response.write_bytes(new + data[len(old):])
        path.write_bytes(new)

    def bool_flag(folder, r):
        r['flags']['module_load_verified'] = 1

    def bool_lifetime(folder, r):
        r['closed_lifetimes'][0]['active_owned_interval'] = 0

    def bool_exit(folder, r):
        r['queries'][0]['exit_code'] = False

    def reversed_time(folder, r):
        r['queries'][0]['started'] = r['queries'][1]['finished']

    def invalid_timezone(folder, r):
        r['finished']['ist'] = r['finished']['utc']

    def reorder_logs(folder, r):
        q = next(q for q in r['queries'] if q['id'] == 'logs_after')
        old = (folder / q['stdout']).read_bytes()
        lines = old.splitlines(keepends=True)
        assert len(lines) == 7
        new = b''.join(lines[:3] + lines[4:6] + lines[3:4] + lines[6:])
        (folder / q['stdout']).write_bytes(new)
        response = folder / q['response']
        data = response.read_bytes()
        assert data.startswith(old)
        response.write_bytes(new + data[len(old):])

    def marker_suffix(folder, r):
        q = next(q for q in r['queries'] if q['id'] == 'transaction')
        for key in ['stdout', 'response']:
            path = folder / q[key]
            path.write_bytes(path.read_bytes().replace(b'normal_load=0', b'normal_load=01'))

    def duplicate_field(folder, r):
        q = next(q for q in r['queries'] if q['id'] == 'logs_after')
        for key in ['stdout', 'response']:
            path = folder / q[key]
            path.write_bytes(path.read_bytes().replace(b'stage=loaded', b'stage=loaded stage=loaded'))

    for name, mutate in [('gate_promotion', flag), ('released_to_active', active),
        ('reframed_command', command), ('hold_removed', hold), ('different_serial', argv),
        ('different_transfer_destination', transfer), ('false_remote_status', status),
        ('stream_role_alias', stream), ('clear_forgery', log_change(b'cleared=pass', b'cleared=fail')),
        ('integrity_forgery', log_change(b'integrity=pass', b'integrity=fail')),
        ('release_address_forgery', log_change(b'stage=release phys=0x0000000081980000',
                                            b'stage=release phys=0x0000000081990000')),
        ('repinned_module_change', module), ('budget_change', budget), ('host_gate_promotion', host_gate),
        ('expanded_config_bound', config_bomb), ('integer_boolean_flag', bool_flag),
        ('integer_boolean_lifetime', bool_lifetime), ('boolean_remote_exit', bool_exit),
        ('reversed_command_time', reversed_time), ('invalid_record_timezone', invalid_timezone),
        ('overlapping_allocation_log_order', reorder_logs), ('transaction_marker_suffix', marker_suffix),
        ('duplicate_lifecycle_field', duplicate_field)]:
        check(name, mutate)
    check('unrepinned_module_change', module, repin=False)
    summary = {'passed': True, 'corruption_rejections': len(checks), 'checks': checks,
               'original_packet': original.relative_to(PROJECT).as_posix(),
               'phone_queries': False, 'phone_writes': False, 'phase_2_device_gate_passed': False}
    device.write(output / 'result.json', summary)
    print(json.dumps({k: v for k, v in summary.items() if k != 'checks'}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
