#!/usr/bin/env python3
"""Offline corruption guards with retained fixtures; never contacts the phone.

Each case copies the selected packet into a new HakiOS evidence directory.
Most cases recompute the mutable packet index so they exercise semantic replay
rather than merely its checksum check. The original packet stays unchanged.
"""
import argparse
import datetime as dt
import gzip
import importlib.util
import json
from pathlib import Path
import re
import shlex
import shutil
import arena_probe as arena

PROJECT = arena.PROJECT
spec = importlib.util.spec_from_file_location(
    'ownership_device_guards', PROJECT / 'scripts/test-ownership-probe-device.py')
device = importlib.util.module_from_spec(spec)
spec.loader.exec_module(device)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packet', required=True)
    args = parser.parse_args()
    original = Path(args.packet)
    if not original.is_absolute():
        original = PROJECT / original
    original = original.resolve()
    arena.require(original.is_relative_to(PROJECT.resolve()), 'packet outside HakiOS workspace')
    original_index = arena.pin(original / 'index.json')
    device.verify(original)
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    output = PROJECT / 'evidence/phase-2/ownership-probe-corruption' / stamp
    output.mkdir(parents=True, exist_ok=False)
    checks = []

    def check(name, mutate, repin=True):
        folder = output / name
        shutil.copytree(original, folder)
        record = arena.read_json(folder / 'result.json')
        mutate(folder, record)
        device.write(folder / 'result.json', record)
        if repin:
            device.write(folder / 'index.json', {'files': {
                p.relative_to(folder).as_posix(): device.pin(p)
                for p in sorted(folder.rglob('*')) if p.is_file() and p.name != 'index.json'}})
        try:
            device.verify(folder)
        except (ValueError, KeyError, TypeError) as exc:
            checks.append({'case': name, 'rejected': True, 'reason': str(exc)})
            print('REJECTED ' + name + ': ' + str(exc), flush=True)
        else:
            checks.append({'case': name, 'rejected': False, 'reason': 'corruption accepted'})
            print('ACCEPTED_CORRUPTION ' + name, flush=True)

    def set_flag(key, value):
        def mutate(folder, record):
            record['flags'][key] = value
        return mutate

    def closed(key, value):
        def mutate(folder, record):
            record['closed_lifetimes'][key] = value
        return mutate

    def query(record, role):
        return next(item for item in record['queries'] if item['id'] == role)

    def change_stream(folder, record, role, transform):
        item = query(record, role)
        path = folder / item['stdout']
        old = path.read_bytes()
        new = transform(old)
        assert new != old, 'mutation did not change stream'
        response = folder / item['response']
        data = response.read_bytes()
        assert data.startswith(old), 'unexpected transport prefix'
        path.write_bytes(new)
        response.write_bytes(new + data[len(old):])

    def replace_bytes(old, new, role='logs_after'):
        def mutate(folder, record):
            def transform(data):
                assert old in data, 'missing mutation anchor: ' + repr(old)
                return data.replace(old, new, 1)
            change_stream(folder, record, role, transform)
        return mutate

    def event_mutation(position, transform):
        def mutate(folder, record):
            def mutate_lines(data):
                lines = data.splitlines(keepends=True)
                assert len(lines) == 21, 'unexpected lifecycle length'
                lines[position] = transform(lines[position])
                return b''.join(lines)
            change_stream(folder, record, 'logs_after', mutate_lines)
        return mutate

    def wrong_token(folder, record):
        old = record['closed_lifetimes']['lifetimes'][0]['token'].encode()
        new = record['closed_lifetimes']['lifetimes'][1]['token'].encode()
        event_mutation(6, lambda line: line.replace(old, new, 1))(folder, record)

    def reused_token(folder, record):
        old = record['closed_lifetimes']['lifetimes'][1]['token'].encode()
        new = record['closed_lifetimes']['lifetimes'][0]['token'].encode()
        for role in ['transaction', 'logs_after']:
            change_stream(folder, record, role, lambda data: data.replace(old, new))
        record['closed_lifetimes']['lifetimes'][1]['token'] = new.decode()

    def release_address(folder, record):
        old = record['closed_lifetimes']['lifetimes'][0]['historical_phys'].encode()
        new = ('0x%016x' % (int(old, 16) + 65536)).encode()
        event_mutation(9, lambda line: line.replace(old, new, 1))(folder, record)

    def span_overflow(folder, record):
        event_mutation(0, lambda line: re.sub(rb'phys=0x[0-9a-f]+',
            b'phys=0xffffffffffff0000', line))(folder, record)

    def reorder_logs(folder, record):
        def transform(data):
            lines = data.splitlines(keepends=True)
            assert len(lines) == 21
            lines[9], lines[12] = lines[12], lines[9]
            return b''.join(lines)
        change_stream(folder, record, 'logs_after', transform)

    def duplicate_log(folder, record):
        def transform(data):
            lines = data.splitlines(keepends=True)
            return b''.join(lines[:7] + [lines[6]] + lines[7:])
        change_stream(folder, record, 'logs_after', transform)

    def reverse_log_time(folder, record):
        event_mutation(7, lambda line: re.sub(rb'^\[[^]]+\]', b'[1.000000]', line))(folder, record)

    def status_after_release(folder, record):
        def transform(data):
            lines = data.splitlines(keepends=True)
            positions = [i for i, line in enumerate(lines) if line.startswith(b'OWNER_STATUS released ')]
            assert len(positions) == 1
            i = positions[0]
            lines[i] = lines[i].replace(b'active=0 bound=0', b'active=1 bound=1').replace(b'bytes=0', b'bytes=65536')
            return b''.join(lines)
        change_stream(folder, record, 'transaction', transform)

    def transaction_order(folder, record):
        def transform(data):
            lines = data.splitlines(keepends=True)
            initial = next(i for i, line in enumerate(lines) if line.startswith(b'OWNER_STATUS initial '))
            line = lines.pop(initial)
            # Preserve each individual list's order while moving the initial
            # observation past four rejection markers; only a combined
            # transaction grammar can detect this impossible observation order.
            rejected = next(i for i, candidate in enumerate(lines)
                if candidate.startswith(b'OWNER_STATUS rejected_initial '))
            lines.insert(rejected, line)
            return b''.join(lines)
        change_stream(folder, record, 'transaction', transform)

    def command(folder, record):
        item = record['queries'][0]
        item['command'] = 'id; uname -r'
        item['argv'][-1] = 'su -c ' + shlex.quote(device.transport.remote_script(item['command'], record['nonce']))

    def framing(folder, record):
        record['queries'][0]['argv'][-1] += ' ; id'

    def hold(folder, record):
        item = query(record, 'transaction')
        assert 'sleep 1' in item['command']
        item['command'] = item['command'].replace('sleep 1', ':')
        item['argv'][-1] = 'su -c ' + shlex.quote(device.transport.remote_script(item['command'], record['nonce']))

    def argv_serial(folder, record):
        record['queries'][0]['argv'][2] = 'another-device'

    def record_serial(folder, record):
        record['serial'] = 'another-device'

    def transfer(folder, record):
        record['push']['argv'][5] = '/data/local/tmp/another.ko'

    def status(folder, record):
        record['queries'][0]['exit_code'] = 1

    def bool_exit(folder, record):
        record['queries'][0]['exit_code'] = False

    def stream_role(folder, record):
        record['queries'][0]['stdout'] = record['queries'][1]['stdout']

    def duplicate_query(folder, record):
        record['queries'][1]['id'] = record['queries'][0]['id']

    def file_change(name):
        def mutate(folder, record):
            path = folder / name
            path.write_bytes(path.read_bytes() + b'changed')
        return mutate

    def module_and_host(folder, record):
        file_change('hakios_ownership_probe.ko')(folder, record)
        path = folder / 'host-build-result.json'
        host = arena.read_json(path)
        module_pin = device.pin(folder / 'hakios_ownership_probe.ko')
        host['module'] = {'bytes': module_pin['size'], 'sha256': module_pin['sha256']}
        device.write(path, host)
        record['host_build_result_pin'] = device.pin(path)
        change_stream(folder, record, 'module_hash', lambda data:
            re.sub(rb'^[0-9a-f]{64}', module_pin['sha256'].encode(), data))

    def budget(folder, record):
        path = folder / 'arena-probe-budget.json'
        value = arena.read_json(path)
        value['regions'][1]['bytes'] += 4096
        device.write(path, value)

    def host_gate(folder, record):
        path = folder / 'host-build-result.json'
        value = arena.read_json(path)
        value['phase_2_device_gate_passed'] = True
        device.write(path, value)
        record['host_build_result_pin'] = device.pin(path)

    def config_bomb(folder, record):
        change_stream(folder, record, 'config_before', lambda old:
            gzip.compress(b'x' * (2 * 1024 * 1024 + 1)))

    def reversed_time(folder, record):
        record['queries'][0]['started'] = record['queries'][1]['finished']

    def invalid_timezone(folder, record):
        record['finished']['ist'] = record['finished']['utc']

    cases = [
        ('gate_promotion', set_flag('phase_2_device_gate_passed', True)),
        ('released_to_active', closed('active_owned_interval', True)),
        ('placement_promotion', set_flag('safe_for_loader_placement', True)),
        ('integer_boolean_flag', set_flag('android_module_execution_verified', 1)),
        ('integer_boolean_lifetime', closed('active_owned_interval', 0)),
        ('reframed_command', command), ('argv_suffix', framing), ('hold_removed', hold),
        ('different_argv_serial', argv_serial), ('different_record_serial', record_serial),
        ('different_transfer_destination', transfer), ('false_remote_status', status),
        ('boolean_remote_exit', bool_exit), ('stream_role_alias', stream_role),
        ('duplicate_query_role', duplicate_query),
        ('wrong_binding_token', wrong_token), ('reused_lifetime_token', reused_token),
        ('wrong_binding_plan', event_mutation(6, lambda line: line.replace(
            device.ownership.PLAN.encode(), b'0' * 64, 1))),
        ('wrong_binding_sequence', event_mutation(6, lambda line: line.replace(b'seq=1', b'seq=2', 1))),
        ('wrong_reject_code', event_mutation(10, lambda line: line.replace(b'code=5', b'code=4', 1))),
        ('clear_forgery', replace_bytes(b'cleared=pass', b'cleared=fail')),
        ('integrity_forgery', replace_bytes(b'integrity=pass', b'integrity=fail')),
        ('release_address_forgery', release_address), ('observed_span_overflow', span_overflow),
        ('overlapping_lifetime_order', reorder_logs), ('duplicate_lifecycle_event', duplicate_log),
        ('lifecycle_suffix', event_mutation(6, lambda line: line.rstrip(b'\n') + b' extra=1\n')),
        ('duplicate_lifecycle_field', replace_bytes(b'stage=bind', b'stage=bind stage=bind')),
        ('released_status_active', status_after_release),
        ('transaction_marker_suffix', replace_bytes(b'accept=bind_first', b'accept=bind_first1', 'transaction')),
        ('repinned_module_change', file_change('hakios_ownership_probe.ko')),
        ('budget_change', budget), ('host_gate_promotion', host_gate),
        ('expanded_config_bound', config_bomb), ('reversed_command_time', reversed_time),
        ('invalid_record_timezone', invalid_timezone),
        ('repinned_ownership_helper', file_change('ownership_probe.py')),
        ('repinned_arena_helper', file_change('arena_probe.py')),
        ('repinned_capture_source', file_change('test-ownership-probe-device.py')),
        ('repinned_module_and_host', module_and_host),
        ('reversed_lifecycle_timestamp', reverse_log_time),
        ('interleaved_transaction_order', transaction_order),
        ('noncanonical_status_number', replace_bytes(b'last_seq=1 bytes=65536',
            b'last_seq=01 bytes=65536', 'transaction'))]
    for name, mutate in cases:
        check(name, mutate)
    check('unrepinned_module_change', file_change('hakios_ownership_probe.ko'), repin=False)
    # All evidence verification is read-only against the original packet.
    arena.require(arena.pin(original / 'index.json') == original_index, 'original index changed')
    device.verify(original)
    accepted = [item['case'] for item in checks if not item['rejected']]
    summary = {'passed': not accepted, 'corruption_cases': len(checks),
        'corruption_rejections': len(checks) - len(accepted), 'accepted_corruptions': accepted,
        'checks': checks, 'original_packet': original.relative_to(PROJECT).as_posix(),
        'original_index_pin': original_index, 'original_packet_reverified': True,
        'phone_queries': False, 'phone_writes': False, 'phase_2_device_gate_passed': False}
    device.write(output / 'result.json', summary)
    print('OWNERSHIP_CORRUPTION ' + output.relative_to(PROJECT).as_posix(), flush=True)
    print(json.dumps({key: value for key, value in summary.items() if key != 'checks'}, sort_keys=True))
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
