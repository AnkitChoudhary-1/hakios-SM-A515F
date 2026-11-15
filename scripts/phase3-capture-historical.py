#!/usr/bin/env python3
"""Snapshot historical RAM through a bounded, matching-ABI read-only module."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import shlex
import struct
import subprocess

PROJECT = Path(__file__).resolve().parents[1]
SERIAL = 'A51_SERIAL_HERE'
BASELINE = 'eb30609a62999e3282ac81e0a5e56411ef12ec1a39c107171bf3e01209c7cb67'


def pin(path):
    raw = path.read_bytes()
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def main():
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    packet = PROJECT / 'evidence/phase-3/historical-raw-capture' / stamp
    packet.mkdir(parents=True, exist_ok=False)
    build = json.loads((PROJECT / 'manifests/phase3-log-reader.json').read_text())
    ko = PROJECT / build['module_path']
    if pin(ko) != build['module']:
        raise ValueError('module pin mismatch')
    remote = '/data/local/tmp/hakios-p3cap-' + stamp + '.ko'
    remote_snapshot = '/data/local/tmp/hakios-p3cap-' + stamp + '.bin'
    commands = []
    loaded = False
    staged = False

    def run(name, args, allow=(0,), timeout=45):
        argv = ['adb', '-s', SERIAL, *args]
        start = dt.datetime.now(dt.timezone.utc).isoformat()
        res = subprocess.run(argv, capture_output=True, timeout=timeout)
        (packet / (name + '.stdout')).write_bytes(res.stdout)
        (packet / (name + '.stderr')).write_bytes(res.stderr)
        commands.append({'name': name, 'argv': argv, 'started': start,
                         'finished': dt.datetime.now(dt.timezone.utc).isoformat(),
                         'exit_code': res.returncode})
        print(json.dumps({'command': name, 'exit_code': res.returncode}), flush=True)
        if res.returncode not in allow:
            raise RuntimeError(name + ': ' + res.stderr.decode(errors='replace'))
        return res.stdout

    def root(name, cmd, **kwargs):
        return run(name, ['shell', 'su', '-c', shlex.quote(cmd)], **kwargs)

    result = {'schema_version': 1, 'scope': 'historical_ram_snapshot_only',
              'phase_3_device_gate_passed': False, 'module_pin': build['module'],
              'operations': {'device_reads': True, 'temporary_module_load': False,
                             'boot_partition_write': False, 'reboot': False}}
    try:
        if run('state', ['get-state']).strip() != b'device':
            raise ValueError('Android is unavailable')
        if run('model', ['shell', 'getprop', 'ro.product.model']).strip() != b'SM-A515F':
            raise ValueError('wrong model')
        if b'uid=0(root)' not in root('root', 'id'):
            raise ValueError('root unavailable')
        kernel = root('kernel', 'uname -r').decode().strip()
        if not build['vermagic'].startswith(kernel + ' '):
            raise ValueError('kernel ABI mismatch')
        if root('baseline', 'sha256sum /dev/block/by-name/boot').decode().split()[0] != BASELINE:
            raise ValueError('boot is not the pinned baseline')
        before = root('boot-before', 'cat /proc/sys/kernel/random/boot_id').decode().strip()
        root('module-absent', 'test ! -e /sys/module/hakios_p3_capture')
        run('push', ['push', str(ko), remote])
        staged = True
        if root('module-hash', 'sha256sum ' + remote).decode().split()[0] != build['module']['sha256']:
            raise ValueError('staged module pin mismatch')
        root('load', 'insmod ' + remote)
        loaded = True
        result['operations']['temporary_module_load'] = True
        # KernelSU's fd wrapper translates binary shell output. Pull a root-created
        # temporary file through ADB's binary file-transfer protocol instead.
        root('snapshot-file', 'cat /proc/hakios_p3_capture > ' + remote_snapshot)
        run('pull-snapshot', ['pull', remote_snapshot, str(packet / 'snapshot.bin')])
        raw = (packet / 'snapshot.bin').read_bytes()
        if len(raw) != 864 + 65536 or raw[:8] != b'HKCAP001':
            raise ValueError('unexpected snapshot format or size')
        meta = struct.unpack_from('<8Q', raw)
        header = struct.unpack_from('<4Q', raw, 832)
        records = {}
        for name, offset in [('gnss', 64), ('dss40', 320), ('dss100', 576)]:
            bank = raw[offset:offset + 256]
            (packet / (name + '.bin')).write_bytes(bank)
            records[name] = [hex(n) for n in struct.unpack('<32Q', bank)]
        bank = raw[864:]
        (packet / 'gnss-raw-log-bank.bin').write_bytes(bank)
        strings = [m.group().decode('ascii') for m in re.finditer(rb'[\x09\x20-\x7e]{12,}', bank)]
        (packet / 'gnss-printable-strings.txt').write_text('\n'.join(strings) + '\n')
        if meta[4]:
            (packet / 'validated-old-log.txt').write_bytes(bank[:meta[4]])
        root('module-messages', 'dmesg | grep HAKIOS_P3CAP')
        after = root('boot-after', 'cat /proc/sys/kernel/random/boot_id').decode().strip()
        if before != after:
            raise ValueError('boot changed during capture')
        result.update(boot_id=before, same_android_boot=True, records=records,
                      old_header=[hex(n) for n in header],
                      validated_old_log_bytes=meta[4], raw_bank_bytes=len(bank),
                      raw_snapshot_pin=pin(packet / 'snapshot.bin'),
                      historical_log_recovered=bool(meta[4]), checks_passed=True)
    except Exception as exc:
        result.update(checks_passed=False, error=repr(exc))
        raise
    finally:
        if loaded:
            root('unload', 'rmmod hakios_p3_capture')
            root('module-removed', 'test ! -e /sys/module/hakios_p3_capture')
        if staged:
            root('remove-staging', 'rm -f ' + remote + ' ' + remote_snapshot)
            root('staging-removed', 'test ! -e ' + remote + ' && test ! -e ' + remote_snapshot)
        result.update(commands=commands, cleaned_up=True)
        (packet / 'source.py').write_bytes(Path(__file__).read_bytes())
        (packet / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        (packet / 'index.json').write_text(json.dumps([
            {'path': str(p.relative_to(packet)), **pin(p)}
            for p in sorted(packet.iterdir()) if p.is_file()], indent=2) + '\n')
    print(json.dumps({'packet': str(packet.relative_to(PROJECT)),
                      'old_log_bytes': result.get('validated_old_log_bytes'),
                      'same_boot': result.get('same_android_boot')}, indent=2), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
