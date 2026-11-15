#!/usr/bin/env python3
"""Offline Linux observation projection; never certify executable ownership.

normalize() expects the report returned by the trusted capture verifier.
Packet import/replay verifies that complete capture and its original dependencies.
All intervals are half-open; end=2**64 is rejected to match payload-layout v1.
"""
import datetime as dt
import hashlib
import importlib.util
import json
import math
from pathlib import Path, PurePosixPath
import re

PROJECT = Path(__file__).resolve().parents[1]
JSON_LIMIT = 2 * 1024 * 1024
TOTAL_LIMIT = 8 * 1024 * 1024
EXCLUSION_LIMIT = 512
CASE_LIMIT = 256
CONFLICT_LIMIT = 1024
FALSE_FLAGS = ('runtime_memory_ownership_verified', 'safe_for_loader_placement',
               'a51_destination_selected', 'phase_2_device_gate_passed',
               'probe_log_retrieval_verified', 'return_to_android_verified',
               'bootloader_loader_acceptance_verified', 'no_flash_a51_launch_verified')
TOOLS = ('runtime_observations.py', 'import-runtime-map.py', 'test-runtime-map.py',
         'capture-live-loader.py', 'boot_formats.py')
PACKET_FILES = {'result.json', 'map.json', 'diagnostics.json',
                'inputs/live-report.json', 'inputs/live-index.json',
                *('tools/' + name for name in TOOLS)}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def bounded_read(path, limit=JSON_LIMIT):
    require(path.is_file() and not path.is_symlink(), 'missing file or symlink: ' + str(path))
    require(path.stat().st_size <= limit, 'file exceeds pre-read bound: ' + str(path))
    with path.open('rb') as stream:
        value = stream.read(limit + 1)
    require(len(value) <= limit, 'file grew beyond read bound')
    return value


def strict_json(raw):
    text = raw.decode('utf-8')
    depth = 0
    quoted = escaped = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in '[{':
            depth += 1
            require(depth <= 64, 'JSON nesting exceeds 64')
        elif char in ']}':
            depth -= 1
    def pairs(items):
        value = {}
        for key, item in items:
            require(key not in value, 'duplicate JSON key: ' + key)
            value[key] = item
        return value
    def nonfinite(value):
        raise ValueError('nonfinite JSON number: ' + value)
    def finite_float(value):
        number = float(value)
        require(math.isfinite(number), 'nonfinite JSON float: ' + value)
        return number
    return json.loads(text, object_pairs_hook=pairs, parse_constant=nonfinite,
                      parse_float=finite_float)


def read_json(path):
    return strict_json(bounded_read(path))


def encode(value):
    return (json.dumps(value, indent=2, allow_nan=False) + '\n').encode('utf-8')


def bounded_encode(value):
    result = bytearray()
    encoder = json.JSONEncoder(indent=2, allow_nan=False)
    for chunk in encoder.iterencode(value):
        raw = chunk.encode('utf-8')
        require(len(result) + len(raw) + 1 <= JSON_LIMIT, 'encoded JSON exceeds output bound')
        result.extend(raw)
    result.extend(b'\n')
    return bytes(result)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def contained(root, name):
    require(type(name) is str and name and '\\' not in name and ':' not in name
            and not PurePosixPath(name).is_absolute() and '..' not in PurePosixPath(name).parts
            and PurePosixPath(name).as_posix() == name, 'noncanonical relative path')
    path = root / name
    require(path.resolve().is_relative_to(root.resolve()) and path.resolve() != root.resolve(),
            'path escapes its root')
    require(not any(part.is_symlink() for part in (path, *path.parents) if part != root.parent),
            'symlink in path')
    return path


def identity(path):
    raw = bounded_read(path)
    return {'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def uint(value, positive=False):
    require(type(value) is int and (1 if positive else 0) <= value < 2**64,
            'invalid unsigned 64-bit integer')
    return value


def interval(start, size):
    uint(start)
    uint(size, True)
    require(start + size < 2**64, 'interval end overflows supported address space')
    return {'start': start, 'size': size, 'end_exclusive': start + size}


def checked_range(record):
    value = interval(record['start'], record['size'])
    require(type(record['end_exclusive']) is int and record['end_exclusive'] == value['end_exclusive'],
            'inconsistent interval end')
    return value


def union_ranges(records):
    ordered = sorted((checked_range(item) for item in records), key=lambda item: item['start'])
    result = []
    for item in ordered:
        if result and item['start'] <= result[-1]['end_exclusive']:
            end = max(item['end_exclusive'], result[-1]['end_exclusive'])
            result[-1] = interval(result[-1]['start'], end - result[-1]['start'])
        else:
            result.append(dict(item))
    return result


def address_cells(values):
    require(type(values) is list and len(values) in (1, 2), 'initrd address requires one or two cells')
    result = 0
    for value in values:
        require(type(value) is int and 0 <= value < 2**32, 'invalid initrd address cell')
        result = (result << 32) | value
    return result


def normalize(report):
    require(type(report['schema_version']) is int and report['schema_version'] == 2
            and report['scope'] == 'live_android_read_only_observations'
            and report['phone_writes'] is False, 'invalid live observation source')
    summary = report['summary']
    require(all(summary[name] is True for name in ('adb_root_verified',
            'single_boot_observation_verified', 'live_fdt_export_verified', 'capture_complete')),
            'complete stable privileged capture is required')
    require(all(summary[name] is False for name in FALSE_FLAGS), 'source promotes an unproved gate')
    tree = summary['live_fdt']
    require(tree['safe_for_loader_placement'] is False, 'FDT promotes unproved placement')
    require(tree['untranslated_reserved_ranges'] == [], 'untranslated reservations are unsupported')
    require(tree['linux_alignment_cell_mismatches'] == [], 'unresolved reservation cell encoding')
    require(type(tree['declared_memory']) is list and 0 < len(tree['declared_memory']) <= 256,
            'invalid declared memory list')
    banks = []
    exclusions = []
    dynamic = []
    def exclude(value):
        require(len(exclusions) < EXCLUSION_LIMIT, 'too many observed exclusions')
        exclusions.append(value)
    for record in tree['declared_memory']:
        require(type(record['enabled']) is bool, 'invalid memory enabled flag')
        if record['enabled']:
            banks.append(checked_range(record) | {'owner': record['node'], 'basis': 'linux_exported_fdt'})
    require(banks, 'no enabled DRAM declarations')
    merged_banks = union_ranges(banks)
    require(sum(item['size'] for item in banks) == sum(item['size'] for item in merged_banks),
            'overlapping FDT DRAM declarations')
    require(type(tree['declared_memory_bytes']) is int
            and tree['declared_memory_bytes'] == sum(item['size'] for item in banks),
            'declared DRAM total mismatch')
    require(type(tree['memreserve']) is list and len(tree['memreserve']) <= 256,
            'invalid FDT reserve map')
    for number, record in enumerate(tree['memreserve']):
        exclude(checked_range(record) | {'owner': 'fdt-memreserve-' + str(number),
                          'basis': 'linux_exported_fdt', 'kind': 'fdt_memreserve'})
    require(type(tree['reserved_memory']) is list and len(tree['reserved_memory']) <= 256,
            'invalid reserved memory list')
    for record in tree['reserved_memory']:
        require(type(record['enabled']) is bool and type(record['no_map']) is bool
                and type(record['reusable']) is bool, 'invalid reservation flags')
        if not record['enabled']:
            continue
        require(type(record['ranges']) is list and len(record['ranges']) <= 256,
                'invalid reservation ranges')
        for item in record['ranges']:
            exclude(checked_range(item) | {'owner': record['node'],
                'basis': 'linux_exported_fdt', 'kind': 'fixed_reservation',
                'no_map': record['no_map'], 'reusable': record['reusable']})
        if record['dynamic_size'] is not None:
            uint(record['dynamic_size'], True)
            alignment = record.get('alignment')
            require(alignment is None or (type(alignment) is int and alignment > 0
                    and alignment < 2**64 and alignment & (alignment - 1) == 0),
                    'invalid dynamic alignment')
            dynamic.append({'owner': record['node'], 'size': record['dynamic_size'],
                            'alignment': alignment, 'alloc_ranges': [checked_range(item)
                                for item in record.get('alloc_ranges', [])], 'placement': None,
                            'basis': 'linux_exported_fdt', 'ownership_verified': False})
    require(tree['dynamic_reservations'] == [item['owner'] for item in dynamic],
            'dynamic reservation summary mismatch')
    iomem = summary['iomem']
    require(type(iomem) is list and len(iomem) <= 4096, 'invalid iomem list')
    ram = []
    redacted = []
    parents = []
    for number, record in enumerate(iomem):
        require(type(record['indent']) is int and record['indent'] >= 0
                and type(record['zero_address_record']) is bool, 'invalid iomem metadata')
        require(type(record['owner']) is str and record['owner'], 'invalid iomem owner')
        if record['zero_address_record']:
            require(type(record['start']) is int and type(record['end_exclusive']) is int
                    and record['start'] == 0 and record['end_exclusive'] == 1,
                    'invalid redacted iomem extent')
            redacted.append({'record': number, 'owner': record['owner']})
            parents.clear()
            continue
        uint(record['start'])
        uint(record['end_exclusive'], True)
        value = interval(record['start'], record['end_exclusive'] - record['start'])
        while parents and parents[-1]['indent'] >= record['indent']:
            parents.pop()
        if record['indent']:
            require(parents and parents[-1]['start'] <= value['start']
                    and value['end_exclusive'] <= parents[-1]['end_exclusive'],
                    'iomem child has no containing parent')
        parents.append(value | {'indent': record['indent']})
        if record['owner'] == 'System RAM':
            require(record['indent'] == 0, 'nested System RAM record is unsupported')
            ram.append(value)
        else:
            exclude(value | {'owner': record['owner'], 'basis': 'linux_proc_iomem',
                                       'kind': 'iomem_resource'})
    initrd = tree['initrd_cells']
    require(type(initrd) is dict and set(initrd) in (set(), {'linux,initrd-start', 'linux,initrd-end'}),
            'incomplete initrd addresses')
    initrd_range = None
    if initrd:
        start, end = (address_cells(initrd[name]) for name in ('linux,initrd-start', 'linux,initrd-end'))
        initrd_range = interval(start, end - start)
        require(any(item['start'] <= start and end <= item['end_exclusive'] for item in merged_banks),
                'initrd outside observed DRAM')
        exclude(initrd_range | {'owner': 'Linux initrd', 'basis': 'linux_exported_fdt',
                                         'kind': 'initrd_declaration'})
    flags = {name: False for name in FALSE_FLAGS}
    return {'format': 'hakios.a51-runtime-observation-map', 'schema_version': 1,
            'scope': 'historical_linux_observations_only', 'capture_created': report['created'],
            'capture_finished': report['finished'], 'live_fdt_sha256': tree['sha256'],
            'declared_dram': banks, 'declared_dram_union': merged_banks,
            'linux_system_ram': ram, 'linux_system_ram_union': union_ranges(ram),
            'dram_and_iomem_unions_agree': canonical(merged_banks) == canonical(union_ranges(ram)),
            'observed_exclusions': exclusions, 'unplaced_dynamic_reservations': dynamic,
            'redacted_iomem_records': redacted, 'initrd': initrd_range,
            'kernel_configuration': summary['kernel_configuration'],
            'reported_meminfo_kib': summary['meminfo_kib'],
            'query_failures': summary['query_failures'], 'verified_owned_intervals': [],
            'flags': flags, 'phone_queries_this_import': False, 'phone_writes': False,
            'limits': 'Historical Linux declarations/resources do not prove free, secure, DMA or payload ownership. '
                      'MemFree/MemAvailable are counts, not physical extents. Entry and log/return remain unproved.'}


def diagnose_span(observations, start, size):
    candidate = interval(start, size)
    require(len(observations['observed_exclusions']) <= EXCLUSION_LIMIT, 'too many observed exclusions')
    conflicts = [dict(item) for item in observations['observed_exclusions']
                 if start < item['end_exclusive'] and item['start'] < candidate['end_exclusive']]
    coverage = lambda records: any(item['start'] <= start and candidate['end_exclusive'] <= item['end_exclusive']
                                   for item in records)
    return {'candidate': candidate, 'declared_dram_coverage': coverage(observations['declared_dram_union']),
            'linux_system_ram_coverage': coverage(observations['linux_system_ram_union']),
            'conflicts': conflicts, 'unresolved_dynamic_owners':
                [item['owner'] for item in observations['unplaced_dynamic_reservations']],
            'decision': 'rejected_ownership_unproved', 'usable_for_loader': False,
            'runtime_memory_ownership_verified': False, 'phase_2_device_gate_passed': False}


def demonstrations(observations):
    cases = []
    conflict_count = 0
    def add_case(name, start, size):
        nonlocal conflict_count
        require(len(cases) < CASE_LIMIT, 'too many diagnostic cases')
        result = diagnose_span(observations, start, size)
        conflict_count += len(result['conflicts'])
        require(conflict_count <= CONFLICT_LIMIT, 'diagnostic conflict expansion exceeds bound')
        cases.append({'id': name, 'result': result})
    for number, item in enumerate(observations['observed_exclusions']):
        if item['kind'] == 'fixed_reservation' or item['owner'] in ('Kernel code', 'Kernel data', 'Linux initrd'):
            add_case('observed-exclusion-' + str(number), item['start'], 1)
    for name, start in (('qemu-modem-address', 0xF0000000), ('low-bank-without-known-overlap', 0x84000000),
                        ('high-bank-ownership-unknown', 0x880000000), ('outside-declared-dram', 0x40080000)):
        add_case(name, start, 4096)
    return {'format': 'hakios.a51-runtime-map-diagnostics', 'schema_version': 1,
            'diagnostic_only': True, 'cases': cases}


def load_source(report_path):
    report_path = report_path.resolve()
    require(report_path.name == 'report.json'
            and report_path.is_relative_to((PROJECT / 'evidence/phase-2/live-loader').resolve()),
            'source must be a retained live-loader report in this project')
    spec = importlib.util.spec_from_file_location('runtime_map_trusted_live_reader',
                                                PROJECT / 'scripts/capture-live-loader.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    report, count = module.verify(report_path.parent)
    return report, count


def stamp():
    now = dt.datetime.now(dt.timezone.utc)
    return {'utc': now.isoformat(), 'ist': now.astimezone(dt.timezone(dt.timedelta(hours=5, minutes=30))).isoformat()}


def time_pair(value):
    require(type(value) is dict and set(value) == {'utc', 'ist'}, 'invalid timestamp pair')
    utc, ist = (dt.datetime.fromisoformat(value[key]) for key in ('utc', 'ist'))
    require(utc.utcoffset() == dt.timedelta(0) and ist.utcoffset() == dt.timedelta(hours=5, minutes=30)
            and utc == ist, 'UTC/IST timestamp labels disagree')
    return utc


def packet_index(folder):
    files = {}
    total = 0
    for name in sorted(PACKET_FILES):
        path = contained(folder, name)
        files[name] = identity(path)
        total += files[name]['size']
    require(total <= TOTAL_LIMIT, 'packet exceeds aggregate bounds')
    return {'format': 'hakios.runtime-map-index', 'schema_version': 1, 'files': files}


def check_packet_paths(folder):
    def entries(root, files, directories):
        seen = set()
        for path in root.iterdir():
            require(len(seen) < len(files) + len(directories), 'extra packet entry')
            require(not path.is_symlink() and path.name in files | directories,
                    'extra or symlink packet entry')
            require(path.is_file() if path.name in files else path.is_dir(), 'packet entry type mismatch')
            seen.add(path.name)
        require(seen == files | directories, 'missing packet entry')
    entries(folder, {'index.json', 'result.json', 'map.json', 'diagnostics.json'}, {'inputs', 'tools'})
    entries(folder / 'inputs', {'live-report.json', 'live-index.json'}, set())
    entries(folder / 'tools', set(TOOLS), set())


def validate_packet(folder):
    folder = Path(folder).resolve()
    index = read_json(folder / 'index.json')
    require(type(index) is dict and set(index) == {'format', 'schema_version', 'files'}
            and index['format'] == 'hakios.runtime-map-index'
            and type(index['schema_version']) is int and index['schema_version'] == 1
            and type(index['files']) is dict and set(index['files']) == PACKET_FILES,
            'invalid packet index roles')
    check_packet_paths(folder)
    total = 0
    for name, record in index['files'].items():
        require(type(record) is dict and set(record) == {'size', 'sha256'}
                and type(record['size']) is int and 0 <= record['size'] <= JSON_LIMIT
                and type(record['sha256']) is str and re.fullmatch(r'[0-9a-f]{64}', record['sha256']),
                'invalid indexed identity')
        total += record['size']
    require(total <= TOTAL_LIMIT, 'indexed aggregate exceeds bound')
    require(canonical(index) == canonical(packet_index(folder)), 'indexed packet bytes changed')
    result = read_json(folder / 'result.json')
    require(type(result) is dict and set(result) == {'format', 'schema_version', 'created', 'finished',
            'source', 'source_capture_files', 'tools', 'counts', 'flags', 'phone_queries', 'phone_writes'}
            and result['format'] == 'hakios.a51-runtime-map-result'
            and type(result['schema_version']) is int and result['schema_version'] == 1,
            'invalid result schema')
    require(time_pair(result['created']) <= time_pair(result['finished']), 'result timestamps reversed')
    require(result['phone_queries'] is False and result['phone_writes'] is False
            and canonical(result['flags']) == canonical({name: False for name in FALSE_FLAGS}),
            'result promotes device or ownership gates')
    require(type(result['source']) is dict and set(result['source']) == {'report', 'index'}, 'invalid source roles')
    source_bytes = {}
    for key, copy_name in (('report', 'inputs/live-report.json'), ('index', 'inputs/live-index.json')):
        reference = result['source'][key]
        require(type(reference) is dict and set(reference) == {'path', 'size', 'sha256'}, 'invalid source pin')
        path = contained(PROJECT, reference['path'])
        raw = bounded_read(path)
        require(canonical({'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
                == canonical({key: reference[key] for key in ('size', 'sha256')})
                and raw == bounded_read(folder / copy_name), 'source copy/pin mismatch')
        source_bytes[key] = raw
    source_path = contained(PROJECT, result['source']['report']['path'])
    require(result['source']['index']['path'] == (source_path.parent / 'index.json').relative_to(PROJECT).as_posix(),
            'source report/index association mismatch')
    report, count = load_source(source_path)
    require(all(bounded_read(contained(PROJECT, result['source'][key]['path'])) == raw
                for key, raw in source_bytes.items())
            and canonical(report) == canonical(strict_json(source_bytes['report'])),
            'source changed during verification or verified report differs from pinned bytes')
    require(time_pair(report['created']) <= time_pair(report['finished'])
            <= time_pair(result['created']), 'import predates its completed source capture')
    require(type(result['source_capture_files']) is int and result['source_capture_files'] == count,
            'source capture count mismatch')
    require(type(result['tools']) is dict and set(result['tools']) == set(TOOLS), 'tool role mismatch')
    for name in TOOLS:
        require(canonical(result['tools'][name]) == canonical(identity(PROJECT / 'scripts' / name))
                and bounded_read(PROJECT / 'scripts' / name) == bounded_read(folder / 'tools' / name),
                'use the matching trusted importer/tool revision: ' + name)
    observations = normalize(report)
    checks = demonstrations(observations)
    require(canonical(read_json(folder / 'map.json')) == canonical(observations), 'map does not reconstruct')
    require(canonical(read_json(folder / 'diagnostics.json')) == canonical(checks), 'diagnostics do not reconstruct')
    expected_counts = counts_for(observations, checks)
    require(canonical(result['counts']) == canonical(expected_counts), 'result counts mismatch')
    return result


def counts_for(observations, checks):
    return {'declared_banks': len(observations['declared_dram']),
            'declared_dram_bytes': sum(item['size'] for item in observations['declared_dram_union']),
            'fixed_reservation_spans': sum(item['kind'] == 'fixed_reservation' for item in observations['observed_exclusions']),
            'observed_exclusions': len(observations['observed_exclusions']),
            'unplaced_dynamic_reservations': len(observations['unplaced_dynamic_reservations']),
            'verified_owned_intervals': 0, 'diagnostic_rejections': len(checks['cases'])}
