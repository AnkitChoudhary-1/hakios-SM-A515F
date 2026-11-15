#!/usr/bin/env python3
"""Retain bounded, read-only A51 observations or replay a retained capture.

Run through scripts/run.py. No payload, reboot, mount or device-write command
is available. The observations never establish executable memory ownership.
"""
import argparse
import datetime as dt
import gzip
import hashlib
import io
import json
import math
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import threading
from pathlib import Path, PurePosixPath

from boot_formats import FormatError, cells, parse_fdt, sha256, strings, summarize_fdt

PROJECT = Path(__file__).resolve().parents[1]
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
MIB = 1024 * 1024
JSON_LIMIT = 2 * MIB
FILE_LIMIT = 4 * MIB
STATUS_ALLOWANCE = 128
TOTAL_LIMIT = 32 * MIB
SYMBOLS = ('CONFIG_KEXEC', 'CONFIG_KEXEC_FILE', 'CONFIG_KEXEC_CORE',
           'CONFIG_DEBUG_FS', 'CONFIG_IKCONFIG', 'CONFIG_IKCONFIG_PROC',
           'CONFIG_OF', 'CONFIG_OF_FLATTREE', 'CONFIG_SYSFS',
           'CONFIG_RANDOMIZE_BASE', 'CONFIG_RELOCATABLE', 'CONFIG_ARCH_KEEP_MEMBLOCK',
           'CONFIG_ARM_PSCI_FW', 'CONFIG_PSTORE', 'CONFIG_PSTORE_RAM',
           'CONFIG_SEC_LOG', 'CONFIG_SEC_DEBUG', 'CONFIG_SEC_DEBUG_LAST_KMSG',
           'CONFIG_EXYNOS_WATCHDOG', 'CONFIG_KSU', 'CONFIG_KSU_MANUAL_HOOK')
PROPERTIES = ('ro.product.model', 'ro.product.device', 'ro.hardware',
              'ro.bootloader', 'ro.build.display.id', 'ro.build.version.release',
              'ro.boot.slot_suffix', 'ro.boot.revision', 'ro.boot.hardware.revision',
              'ro.boot.flash.locked', 'ro.boot.verifiedbootstate', 'ro.boot.vbmeta.device_state')
QUERIES = [
    ('root_begin', 'id', 4096),
    ('boot_id_begin', 'cat /proc/sys/kernel/random/boot_id', 4096),
] + [('property_' + key, 'getprop ' + key, 4096) for key in PROPERTIES] + [
    ('uname', 'uname -a', 16384),
    ('fdt_begin', 'cat /sys/firmware/fdt', 2 * MIB),
    ('meminfo', 'cat /proc/meminfo', 65536),
    ('iomem', 'cat /proc/iomem', 2 * MIB),
    ('cpuinfo', 'cat /proc/cpuinfo', 65536),
    ('cpu_online', 'cat /sys/devices/system/cpu/online', 4096),
    ('config_gz', 'cat /proc/config.gz', 2 * MIB),
    ('dt_model', 'cat /sys/firmware/devicetree/base/model', 4096),
    ('dt_compatible', 'cat /sys/firmware/devicetree/base/compatible', 4096),
    ('dt_initrd_start', 'cat /sys/firmware/devicetree/base/chosen/linux,initrd-start', 4096),
    ('dt_initrd_end', 'cat /sys/firmware/devicetree/base/chosen/linux,initrd-end', 4096),
    ('dt_video_reg', 'cat /sys/firmware/devicetree/base/reserved-memory/ion_video_stream/reg', 4096),
    ('dt_crypto_reg', 'cat /sys/firmware/devicetree/base/reserved-memory/ion_crypto/reg', 4096),
    ('dt_wlbt_reg', 'cat /sys/firmware/devicetree/base/reserved-memory/wifibt_if/reg', 4096),
    ('dt_reserved_listing', 'ls -l /sys/firmware/devicetree/base/reserved-memory', 65536),
    ('dt_chosen_listing', 'ls -l /sys/firmware/devicetree/base/chosen', 65536),
    ('mounts', 'cat /proc/mounts', 256 * 1024),
    ('pstore_listing', 'ls -la /sys/fs/pstore', 65536),
    ('pstore_console', 'cat /sys/fs/pstore/console-ramoops-0', 2 * MIB),
    ('last_kmsg_listing', 'ls -l /proc/last_kmsg', 16384),
    ('last_kmsg_platform_log', "cat /proc/last_kmsg | grep -Ei 'Booting Linux|Linux version|Kernel command line|Machine model|OF:|reserved.memory|Reserved memory|cma:|Memory:|memblock|psci|watchdog|sec_log|sec_getlog|debug.snapshot|pstore|ramoops|initrd|fdt|devicetree|Kernel Offset|smp:'", 2 * MIB),
    ('reset_reason', 'cat /proc/reset_reason', 16384),
    ('debugfs_listing', 'ls -ld /sys/kernel/debug', 16384),
    ('kexec_loaded', 'cat /sys/kernel/kexec_loaded', 4096),
    ('kernel_platform_log', "dmesg | grep -Ei 'Booting Linux|Linux version|Kernel command line|Machine model|OF:|reserved.memory|Reserved memory|cma:|Memory:|memblock|psci|watchdog|sec_log|sec_getlog|debug.snapshot|pstore|ramoops|initrd|fdt|devicetree|Kernel Offset|smp:'", 4 * MIB),
    ('boot_links', 'ls -l /dev/block/by-name/boot /dev/block/by-name/dtbo /dev/block/by-name/recovery', 16384),
] + [(name + '_size', 'blockdev --getsize64 /dev/block/by-name/' + name, 4096)
     for name in ('boot', 'dtbo', 'recovery')] + [
    (name + '_sha256', 'sha256sum /dev/block/by-name/' + name, 4096)
    for name in ('boot', 'dtbo', 'recovery')
] + [
    ('fdt_end', 'cat /sys/firmware/fdt', 2 * MIB),
    ('boot_id_end', 'cat /proc/sys/kernel/random/boot_id', 4096),
    ('root_end', 'id', 4096),
]
LOCAL_INPUTS = {
    'installed_boot': 'everline-ksu/artifacts/A51-PixelOS-Everline-KernelSU-Next-boot.img',
    'original_boot': 'everline-ksu/backups/a51-pixelos-original-boot.img',
    'original_dtbo': 'everline-ksu/backups/a51-pixelos-original-dtbo.img',
    'original_recovery': 'everline-ksu/backups/a51-twrp-original-recovery.img',
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def stamp():
    now = dt.datetime.now(dt.timezone.utc)
    return {'utc': now.isoformat(), 'ist': now.astimezone(IST).isoformat()}


def bounded_read(path, limit=FILE_LIMIT):
    with Path(path).open('rb') as stream:
        value = stream.read(limit + 1)
    require(len(value) <= limit, 'file exceeds bound: ' + str(path))
    return value


def json_read(path):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate JSON key')
            result[key] = value
        return result

    def constant(value):
        raise ValueError('nonfinite JSON number: ' + value)

    def floating(value):
        result = float(value)
        require(math.isfinite(result), 'overflowing JSON float')
        return result

    return json.loads(bounded_read(path, JSON_LIMIT), object_pairs_hook=pairs,
                      parse_constant=constant, parse_float=floating)


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=True, allow_nan=False) + '\n', encoding='utf-8')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest_file(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(MIB), b''):
            result.update(block)
    return {'size': Path(path).stat().st_size, 'sha256': result.hexdigest()}


def inside(folder, name):
    folder = Path(folder)
    require(isinstance(name, str) and 0 < len(name) <= 1024 and '\\' not in name and '\0' not in name, 'invalid retained path')
    relative = PurePosixPath(name)
    require(relative.as_posix() == name and not relative.is_absolute() and relative.parts and
            all(part not in ('..', '.') and ':' not in part for part in relative.parts), 'unsafe retained path')
    result = folder.joinpath(*relative.parts)
    require(result.resolve().is_relative_to(folder.resolve()) and not result.is_symlink(), 'retained path escapes capture')
    return result


def run_bounded(argv, limit, timeout=20):
    """Drain both pipes with caps before retaining bytes, on Windows and Linux."""
    started = stamp()
    values = {'stdout': bytearray(), 'stderr': bytearray()}
    overflow = threading.Event()
    try:
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False)
    except OSError as exc:
        return {'started': started, 'finished': stamp(), 'exit_code': None,
                'status': 'launch_error'}, b'', str(exc).encode('utf-8')[:65536]

    def reader(pipe, name, cap):
        while True:
            block = pipe.read(65536)
            if not block:
                break
            available = cap - len(values[name])
            values[name].extend(block[:available])
            if len(block) > available:
                overflow.set()
                try:
                    proc.kill()
                except OSError:
                    pass
                break
        pipe.close()

    threads = [threading.Thread(target=reader, args=(proc.stdout, 'stdout', limit), daemon=True),
               threading.Thread(target=reader, args=(proc.stderr, 'stderr', 65536), daemon=True)]
    for thread in threads:
        thread.start()
    status = 'ok'
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        status = 'timeout'
        proc.kill()
        proc.wait()
    for thread in threads:
        thread.join(timeout=5)
    require(not any(thread.is_alive() for thread in threads), 'pipe did not close after command termination')
    if overflow.is_set():
        status = 'output_limit'
    elif status == 'ok' and proc.returncode != 0:
        status = 'command_failed'
    return {'started': started, 'finished': stamp(), 'exit_code': proc.returncode,
            'status': status}, bytes(values['stdout']), bytes(values['stderr'])


def remote_script(command, nonce):
    require(isinstance(nonce, str) and re.fullmatch(r'[0-9a-f]{32}', nonce), 'invalid remote status nonce')
    # Android's shell supports pipefail. If it does not, no query is executed.
    return "set -o pipefail && { " + command + "; }; hakios_read_status=$?; printf '\\nHAKIOS_A51_STATUS_" + nonce + "=%d\\n' \"$hakios_read_status\""


def unwrap_status(response, nonce):
    remote_script('id', nonce)
    marker = b'\nHAKIOS_A51_STATUS_' + nonce.encode('ascii') + b'='
    position = response.rfind(marker)
    require(position >= 0, 'remote exit status is missing')
    tail = response[position + len(marker):]
    require(re.fullmatch(rb'[0-9]{1,3}\n', tail) is not None, 'invalid remote exit status footer')
    code = int(tail)
    require(0 <= code <= 255 and tail == str(code).encode('ascii') + b'\n', 'remote exit status outside shell bounds or noncanonical')
    return response[:position], code


def decode_response(response, nonce, transport_status, transport_exit_code, limit):
    """Reconstruct payload and remote status from the retained transport bytes."""
    require(transport_status in ('ok', 'command_failed', 'launch_error', 'timeout', 'output_limit'), 'invalid transport status')
    require(type(transport_exit_code) is int or transport_exit_code is None, 'invalid transport exit type')
    if transport_status == 'launch_error':
        require(transport_exit_code is None and not response, 'invalid launch failure')
    else:
        require(type(transport_exit_code) is int, 'missing transport exit code')
    if transport_status == 'ok':
        require(transport_exit_code == 0, 'successful transport has nonzero exit status')
    if transport_status == 'command_failed':
        require(transport_exit_code != 0, 'failed transport has zero exit status')
    status, code, stdout = transport_status, None, response
    try:
        stdout, code = unwrap_status(response, nonce)
        if status == 'ok' and code != 0:
            status = 'command_failed'
    except ValueError:
        if status == 'ok':
            status = 'missing_remote_status'
    if len(stdout) > limit:
        status = 'output_limit'
        stdout = stdout[:limit]
    return stdout, code, status


def time_pair(value):
    require(isinstance(value, dict) and set(value) == {'utc', 'ist'}, 'invalid timestamp pair')
    utc = dt.datetime.fromisoformat(value['utc'])
    ist = dt.datetime.fromisoformat(value['ist'])
    require(utc.utcoffset() == dt.timedelta(0) and ist.utcoffset() == dt.timedelta(hours=5, minutes=30)
            and utc == ist, 'UTC/IST timestamps disagree')
    return utc


def parse_iomem(data):
    records = []
    for line in data.decode('utf-8', errors='strict').splitlines():
        match = re.fullmatch(r'(\s*)([0-9a-fA-F]+)-([0-9a-fA-F]+) : (.+)', line)
        require(match is not None, 'malformed /proc/iomem line')
        indent, start, end, owner = match.groups()
        start, end = int(start, 16), int(end, 16)
        require(0 <= start <= end < 2 ** 64, 'invalid inclusive iomem extent')
        records.append({'indent': len(indent), 'start': start, 'end_exclusive': end + 1,
                        'owner': owner, 'zero_address_record': start == end == 0})
    return records


def config_symbols(data):
    with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
        text = stream.read(2 * MIB + 1)
    require(len(text) <= 2 * MIB, 'decompressed configuration exceeds bound')
    definitions = {}
    for line in text.decode('utf-8', errors='strict').splitlines():
        match = re.fullmatch(r'(CONFIG_[A-Z0-9_]+)=(.*)|# (CONFIG_[A-Z0-9_]+) is not set', line)
        if match:
            key = match[1] or match[3]
            require(key not in definitions, 'duplicate configuration definition')
            definitions[key] = match[2] if match[1] else 'n'
    return {key: definitions.get(key, 'absent_or_unknown') for key in SYMBOLS}


def tree_diff(before, after):
    old, new = set(before.nodes), set(after.nodes)
    changed, added, removed = [], [], []
    for node in sorted(old & new):
        a, b = before.nodes[node], after.nodes[node]
        added.extend(node.rstrip('/') + '/' + key for key in sorted(b.keys() - a.keys()))
        removed.extend(node.rstrip('/') + '/' + key for key in sorted(a.keys() - b.keys()))
        changed.extend(node.rstrip('/') + '/' + key for key in sorted(a.keys() & b.keys()) if a[key] != b[key])
    return {'nodes_added': sorted(new - old), 'nodes_removed': sorted(old - new),
            'properties_added': added, 'properties_removed': removed, 'properties_changed': changed,
            'memreserve_changed': canonical(before.memreserve) != canonical(after.memreserve)}


def summarize(folder, report):
    require(type(report.get('schema_version')) is int and report['schema_version'] == 2, 'unsupported capture schema')
    require(report.get('phone_writes') is False, 'capture cannot claim device writes')
    require(report.get('scope') == 'live_android_read_only_observations', 'unsupported observation scope')
    require(report.get('remote_stdout_may_include_stderr') is True, 'missing exec-out transport semantics')
    nonce = report['remote_status_nonce']
    remote_script('id', nonce)
    require(isinstance(report.get('serial'), str) and re.fullmatch(r'[A-Za-z0-9._:-]+', report['serial']), 'invalid serial')
    require(isinstance(report.get('adb_path'), str) and report['adb_path'], 'invalid adb path')
    created, finished = time_pair(report['created']), time_pair(report['finished'])
    require(created <= finished, 'capture timestamps are reversed')
    transport = report['transport_check']
    require(transport['argv'] == [report['adb_path'], '-s', report['serial'], 'get-state']
            and transport['status'] == 'ok' and type(transport['exit_code']) is int and transport['exit_code'] == 0
            and transport['stdout'].strip() == 'device', 'selected transport was not verified')
    require(time_pair(transport['started']) <= time_pair(transport['finished']) <= created,
            'transport timestamps are reversed or after capture creation')
    executable = report['adb_executable']
    require(type(executable['size']) is int and executable['size'] > 0 and
            isinstance(executable['sha256'], str) and re.fullmatch(r'[0-9a-f]{64}', executable['sha256']), 'invalid adb executable identity')
    queries = report['queries']
    require(isinstance(queries, list) and len(queries) <= len(QUERIES), 'invalid query count')
    successful, failures = {}, []
    previous = created
    for number, (record, (name, command, limit)) in enumerate(zip(queries, QUERIES)):
        expected_argv = [report['adb_path'], '-s', report['serial'], 'exec-out', 'su -c ' + shlex.quote(remote_script(command, nonce))]
        require(record['id'] == name and record['command'] == command and record['argv'] == expected_argv,
                'query differs from fixed read-only command list')
        require(type(record['exit_code']) is int or record['exit_code'] is None, 'invalid command exit type')
        require(record['exit_code'] is None or 0 <= record['exit_code'] <= 255, 'invalid command exit value')
        begin, end = time_pair(record['started']), time_pair(record['finished'])
        require(previous <= begin <= end <= finished, 'query timestamps are reversed or outside capture')
        previous = end
        require(all(type(record[key + '_size']) is int for key in ('stdout', 'stderr', 'response')), 'invalid output size type')
        require(record['status'] in ('ok', 'command_failed', 'launch_error', 'timeout', 'output_limit', 'missing_remote_status'), 'invalid command status')
        prefix = 'queries/' + str(number).zfill(2) + '-' + name
        require(all(record[key] == prefix + '.' + key for key in ('stdout', 'stderr', 'response')), 'unexpected query file path')
        stdout = bounded_read(inside(folder, record['stdout']), limit)
        stderr = bounded_read(inside(folder, record['stderr']), 65536)
        response = bounded_read(inside(folder, record['response']), limit + STATUS_ALLOWANCE)
        require(record['stdout_size'] == len(stdout) and record['stdout_sha256'] == sha256(stdout), 'stdout identity mismatch')
        require(record['stderr_size'] == len(stderr) and record['stderr_sha256'] == sha256(stderr), 'stderr identity mismatch')
        require(record['response_size'] == len(response) and record['response_sha256'] == sha256(response), 'transport response identity mismatch')
        decoded, exit_code, status = decode_response(response, nonce, record['transport_status'], record['transport_exit_code'], limit)
        require(stdout == decoded and record['exit_code'] == exit_code and record['status'] == status,
                'remote response/status does not reconstruct')
        if record['status'] == 'ok':
            require(record['exit_code'] == 0 and record['transport_exit_code'] == 0, 'successful query has nonzero exit status')
            successful[name] = stdout
        else:
            failures.append({'query': name, 'status': record['status'], 'exit_code': record['exit_code']})
    text = lambda name: successful.get(name, b'').decode('utf-8', errors='replace').strip()
    root = all(re.search(r'\buid=0\(root\)', text(name)) for name in ('root_begin', 'root_end'))
    boot_id = text('boot_id_begin')
    same_boot = bool(re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', boot_id)
                     and boot_id == text('boot_id_end'))
    fdt = successful.get('fdt_begin')
    stable_fdt = fdt is not None and fdt == successful.get('fdt_end')
    result = {'adb_root_verified': bool(root), 'single_boot_observation_verified': same_boot,
              'live_fdt_export_verified': False, 'capture_complete': len(queries) == len(QUERIES),
              'successful_queries': len(successful), 'query_failures': failures,
              'android_properties': {key: text('property_' + key) for key in PROPERTIES},
              'uname': text('uname'), 'cpu_online': text('cpu_online'),
              'kernel_configuration': config_symbols(successful['config_gz']) if 'config_gz' in successful else None,
              'iomem': parse_iomem(successful['iomem']) if 'iomem' in successful else None,
              'meminfo_kib': {key: int(value) for key, value in re.findall(r'^([A-Za-z_()]+):\s+(\d+) kB$', text('meminfo'), re.M)},
              'logging_interface_observations': {key: {'query_succeeded': key in successful, 'text': text(key)}
                                                 for key in ('pstore_listing', 'last_kmsg_listing', 'reset_reason', 'debugfs_listing')},
              'existing_android_log_retrieval': {key: {'query_succeeded': key in successful,
                  'nonempty': bool(successful.get(key)), 'size': len(successful.get(key, b''))}
                  for key in ('pstore_console', 'last_kmsg_platform_log')},
              'mounts_for_logs': [line for line in text('mounts').splitlines() if 'pstore' in line or 'debugfs' in line],
              'live_fdt': None, 'base_comparisons': [], 'partitions': {},
              'runtime_memory_ownership_verified': False, 'safe_for_loader_placement': False,
              'a51_destination_selected': False, 'phase_2_device_gate_passed': False,
              'probe_log_retrieval_verified': False, 'return_to_android_verified': False,
              'bootloader_loader_acceptance_verified': False, 'no_flash_a51_launch_verified': False}
    if fdt is not None:
        tree = parse_fdt(fdt)
        require(tree.header['totalsize'] == len(fdt), 'exported FDT has trailing/unaccounted bytes')
        summary = summarize_fdt(tree)
        summary.pop('gaps_after_known_static_reservations')
        summary.pop('chosen')
        summary['limits'] = 'Observed Linux-exported tree; pre-Linux fixups, dynamic/secure ownership and executable destinations remain unverified.'
        chosen = tree.nodes.get('/chosen', {})
        summary['chosen_property_names'] = sorted(chosen)
        summary['stdout_path'] = strings(chosen.get('stdout-path', b''))
        summary['initrd_cells'] = {key: cells(chosen[key]) for key in ('linux,initrd-start', 'linux,initrd-end') if key in chosen}
        summary['seed_properties_present'] = [key for key in chosen if 'seed' in key.lower()]
        summary['sha256'] = sha256(fdt)
        summary['unchanged_at_capture_end'] = stable_fdt
        summary['sysfs_model_matches'] = successful.get('dt_model') == tree.nodes['/'].get('model')
        summary['sysfs_compatible_matches'] = successful.get('dt_compatible') == tree.nodes['/'].get('compatible')
        result['live_fdt'] = summary
        result['live_fdt_export_verified'] = bool(root and same_boot and stable_fdt and
            summary['sysfs_model_matches'] and summary['sysfs_compatible_matches'])
        for item in report['base_fdts']:
            base = bounded_read(inside(folder, item['copy']), 2 * MIB)
            require(item['size'] == len(base) and item['sha256'] == sha256(base), 'retained base identity mismatch')
            result['base_comparisons'].append({'image': item['image'], 'sha256': sha256(base),
                                              'diff': tree_diff(parse_fdt(base), tree)})
    for name, expected in (('boot', 'installed_boot'), ('dtbo', 'original_dtbo'), ('recovery', 'original_recovery')):
        digest = text(name + '_sha256').split()
        size = text(name + '_size')
        require(not digest or re.fullmatch(r'[0-9a-f]{64}', digest[0]), 'invalid partition digest')
        require(not size or re.fullmatch(r'[0-9]+', size), 'invalid partition size')
        local = report['local_inputs'][expected]
        require(type(local['exists']) is bool, 'invalid local input existence type')
        if local['exists']:
            require(type(local['size']) is int and local['size'] >= 0 and
                    re.fullmatch(r'[0-9a-f]{64}', local['sha256']), 'invalid local input identity')
        result['partitions'][name] = {'size': int(size) if size else None,
            'sha256': digest[0] if digest else None, 'comparison_input': expected,
            'matches_retained_size_and_sha256': bool(digest and size and local.get('exists') and
                int(size) == local['size'] and digest[0] == local['sha256'])}
    return result


def make_index(folder):
    files = {}
    total = 0
    for path in sorted(folder.rglob('*')):
        require(not path.is_symlink(), 'symlink in capture')
        if path.is_file() and path != folder / 'index.json':
            name = path.relative_to(folder).as_posix()
            inside(folder, name)
            size = path.stat().st_size
            require(size <= FILE_LIMIT + (STATUS_ALLOWANCE if name.endswith('.response') else 0), 'indexed file exceeds bound')
            total += size
            require(len(files) < 256 and total <= TOTAL_LIMIT, 'capture index exceeds bound')
            files[name] = digest_file(path)
    return {'schema_version': 1, 'files': files}


def verify_inputs(folder, report):
    reference = report['source_trace']
    require(isinstance(reference, dict) and set(reference) == {'report', 'sha256'}, 'invalid source-trace reference')
    trace_path = inside(PROJECT, reference['report'])
    require(sha256(bounded_read(trace_path, JSON_LIMIT)) == reference['sha256'], 'source-trace report changed')
    trace = json_read(trace_path)
    require(isinstance(report['base_fdts'], list) and len(report['base_fdts']) == len(trace['base_fdts']) == 3, 'invalid base FDT count')
    for item, source in zip(report['base_fdts'], trace['base_fdts']):
        expected = dict(source['input'], image=source['image'], source_copy=source['input']['copy'],
                        copy='inputs/' + source['image'] + '.dtb')
        require(canonical(item) == canonical(expected), 'base FDT provenance differs from pinned trace')
        value = bounded_read(inside(folder, item['copy']), 2 * MIB)
        original = bounded_read(inside(trace_path.parent, item['source_copy']), 2 * MIB)
        require(value == original and len(value) == item['size'] and sha256(value) == item['sha256'], 'base FDT bytes changed')
    require(isinstance(report['local_inputs'], dict) and set(report['local_inputs']) == set(LOCAL_INPUTS), 'invalid local input set')
    for key, relative in LOCAL_INPUTS.items():
        item = report['local_inputs'][key]
        require(item['path'] == relative and type(item['exists']) is bool, 'invalid local input path or existence type')
        path = PROJECT.parent / relative
        require(path.is_file() == item['exists'], 'local input availability changed: ' + key)
        if item['exists']:
            require(type(item['size']) is int and item['size'] >= 0, 'invalid local input size')
            require(digest_file(path) == {'size': item['size'], 'sha256': item['sha256']}, 'local input bytes changed: ' + key)


def verify(folder):
    folder = Path(folder).resolve()
    index = json_read(folder / 'index.json')
    require(type(index.get('schema_version')) is int and index['schema_version'] == 1, 'invalid index schema')
    files = index['files']
    require(isinstance(files, dict) and len(files) <= 256, 'invalid index count')
    total = 0
    for name, identity in files.items():
        require(isinstance(identity, dict) and set(identity) == {'size', 'sha256'}, 'invalid indexed identity')
        cap = FILE_LIMIT + (STATUS_ALLOWANCE if name.endswith('.response') else 0)
        require(type(identity['size']) is int and 0 <= identity['size'] <= cap, 'invalid indexed size')
        require(isinstance(identity['sha256'], str) and re.fullmatch(r'[0-9a-f]{64}', identity['sha256']), 'invalid indexed digest')
        total += identity['size']
        require(total <= TOTAL_LIMIT, 'indexed bytes exceed bound')
    for name, identity in files.items():
        value = bounded_read(inside(folder, name), identity['size'])
        require(len(value) == identity['size'] and sha256(value) == identity['sha256'], 'indexed file changed: ' + name)
    require(canonical(index) == canonical(make_index(folder)), 'missing, extra or altered indexed files')
    report = json_read(folder / 'report.json')
    expected_files = {'report.json', 'tools/capture-live-loader.py', 'tools/boot_formats.py'}
    for item in report['base_fdts']:
        expected_files.add(item['copy'])
    for item in report['queries']:
        expected_files.update(item[key] for key in ('stdout', 'stderr', 'response'))
    require(set(files) == expected_files, 'unexpected retained file set')
    for script in ('capture-live-loader.py', 'boot_formats.py'):
        require(bounded_read(folder / 'tools' / script) == bounded_read(PROJECT / 'scripts' / script), 'use the matching retained script revision: ' + script)
    verify_inputs(folder, report)
    expected = summarize(folder, report)
    require(canonical(report['summary']) == canonical(expected), 'stored observations do not reconstruct from retained bytes')
    return report, len(files)


def capture(serial):
    require(re.fullmatch(r'[A-Za-z0-9._:-]+', serial), 'invalid ADB serial')
    adb = shutil.which('adb')
    require(adb, 'adb is unavailable')
    # Check the explicitly selected transport; never select a different phone.
    state, out, err = run_bounded([adb, '-s', serial, 'get-state'], 4096)
    require(state['status'] == 'ok' and out.strip() == b'device', 'selected phone is not authorized/connected')
    folder = PROJECT / 'evidence' / 'phase-2' / 'live-loader' / dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder.mkdir(parents=True, exist_ok=False)
    (folder / 'queries').mkdir()
    (folder / 'tools').mkdir()
    (folder / 'inputs').mkdir()
    nonce = secrets.token_hex(16)
    report = {'schema_version': 2, 'scope': 'live_android_read_only_observations', 'created': stamp(),
              'serial': serial, 'adb_path': adb, 'adb_executable': digest_file(adb),
              'remote_status_nonce': nonce, 'remote_stdout_may_include_stderr': True,
              'transport_check': dict(state, argv=[adb, '-s', serial, 'get-state'], stdout=out.decode(), stderr=err.decode(errors='replace')),
              'phone_writes': False, 'queries': [], 'base_fdts': [], 'local_inputs': {}}
    for script in ('capture-live-loader.py', 'boot_formats.py'):
        shutil.copyfile(PROJECT / 'scripts' / script, folder / 'tools' / script)
    pointer = json_read(PROJECT / 'manifests' / 'loader-source-trace-current.json')
    trace_path = inside(PROJECT, pointer['report'])
    trace_bytes = bounded_read(trace_path, JSON_LIMIT)
    require(sha256(trace_bytes) == pointer['sha256'], 'source-trace pointer identity mismatch')
    trace = json_read(trace_path)
    report['source_trace'] = {'report': pointer['report'], 'sha256': pointer['sha256']}
    for item in trace['base_fdts']:
        value = bounded_read(inside(trace_path.parent, item['input']['copy']), 2 * MIB)
        require(len(value) == item['input']['size'] and sha256(value) == item['input']['sha256'], 'source-trace base hash mismatch')
        name = 'inputs/' + item['image'] + '.dtb'
        inside(folder, name).write_bytes(value)
        report['base_fdts'].append(dict(item['input'], image=item['image'], source_copy=item['input']['copy'], copy=name))
    for key, relative in LOCAL_INPUTS.items():
        path = PROJECT.parent / relative
        record = {'path': relative, 'exists': path.is_file()}
        if path.is_file():
            record.update(digest_file(path))
        report['local_inputs'][key] = record
    print('CAPTURE ' + str(folder), flush=True)
    for number, (name, command, limit) in enumerate(QUERIES):
        argv = [adb, '-s', serial, 'exec-out', 'su -c ' + shlex.quote(remote_script(command, nonce))]
        metadata, response, stderr = run_bounded(argv, limit + STATUS_ALLOWANCE)
        metadata['transport_status'] = metadata['status']
        metadata['transport_exit_code'] = metadata['exit_code']
        stdout, metadata['exit_code'], metadata['status'] = decode_response(
            response, nonce, metadata['transport_status'], metadata['transport_exit_code'], limit)
        out_name = 'queries/' + str(number).zfill(2) + '-' + name + '.stdout'
        err_name = 'queries/' + str(number).zfill(2) + '-' + name + '.stderr'
        response_name = 'queries/' + str(number).zfill(2) + '-' + name + '.response'
        inside(folder, out_name).write_bytes(stdout)
        inside(folder, err_name).write_bytes(stderr)
        inside(folder, response_name).write_bytes(response)
        report['queries'].append(dict(metadata, id=name, command=command, argv=argv,
            stdout=out_name, stderr=err_name, stdout_size=len(stdout), stdout_sha256=sha256(stdout),
            stderr_size=len(stderr), stderr_sha256=sha256(stderr), response=response_name,
            response_size=len(response), response_sha256=sha256(response)))
        print(str(number + 1) + '/' + str(len(QUERIES)) + ' ' + name + ': ' + metadata['status'] + ' (' + str(len(stdout)) + ' bytes)', flush=True)
        if name == 'root_begin' and (metadata['status'] != 'ok' or not re.search(rb'\buid=0\(root\)', stdout)):
            break
        if name == 'boot_id_begin' and metadata['status'] != 'ok':
            break
    report['finished'] = stamp()
    report['summary'] = summarize(folder, report)
    write_json(folder / 'report.json', report)
    write_json(folder / 'index.json', make_index(folder))
    verified, count = verify(folder)
    complete = verified['summary']['capture_complete'] and verified['summary']['live_fdt_export_verified']
    if complete:
        write_json(PROJECT / 'manifests' / 'live-loader-current.json', {
            'schema_version': 2, 'report': (folder / 'report.json').relative_to(PROJECT).as_posix(),
            'sha256': digest_file(folder / 'report.json')['sha256'], 'indexed_files': count,
            'scope': report['scope'], 'phone_writes': False, 'phase_2_device_gate_passed': False})
    print('Retained/indexed files: ' + str(count), flush=True)
    print('ADB root verified: ' + str(report['summary']['adb_root_verified']), flush=True)
    print('Live exported FDT verified: ' + str(report['summary']['live_fdt_export_verified']), flush=True)
    print('Query failures retained: ' + str(len(report['summary']['query_failures'])), flush=True)
    print('Executable ownership / Phase 2 device gate: false', flush=True)
    return 0 if complete else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--serial')
    action.add_argument('--verify', type=Path)
    args = parser.parse_args()
    try:
        if args.verify:
            report, count = verify(args.verify)
            print('Verified ' + str(count) + ' retained files and reconstructed read-only observations; device gate remains false.')
            return 0
        return capture(args.serial)
    except (ValueError, FormatError, OSError, KeyError, TypeError, EOFError) as exc:
        print(type(exc).__name__ + ': ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
