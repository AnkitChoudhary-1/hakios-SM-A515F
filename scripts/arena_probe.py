"""Fixed diagnostic budget and closed allocation lifetimes; never launch code."""
import hashlib
import json
from pathlib import Path
import re
import struct

PROJECT = Path(__file__).resolve().parents[1]
REGIONS = [('input', 0, 4096, 17), ('image', 4096, 16384, 34),
           ('bss', 20480, 8192, 51), ('stack', 28672, 16384, 68),
           ('logs', 45056, 4096, 85), ('spare', 49152, 16384, 102)]
REFERENCE = 'evidence/phase-2/loader-probe/20261111T105317947466Z'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def read_json(path):
    path = Path(path)
    require(path.stat().st_size <= 2 * 1024 * 1024, 'JSON exceeds bound')
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate key')
            result[key] = value
        return result
    def number(value):
        raise ValueError('noninteger JSON number')
    source = path.read_text(encoding='utf-8')
    depth, quoted, escaped = 0, False, False
    for char in source:
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
            require(depth <= 64, 'JSON nesting exceeds bound')
        elif char in ']}':
            depth -= 1
            require(depth >= 0, 'JSON delimiter mismatch')
    require(depth == 0 and not quoted, 'JSON delimiter mismatch')
    return json.loads(source, object_pairs_hook=pairs,
                      parse_float=number, parse_constant=number)


def pin(path):
    data = Path(path).read_bytes()
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def reference():
    """Measure the retained QEMU ELF as sizing context, without executing it."""
    folder = PROJECT / REFERENCE
    result = pin(folder / 'result.json')
    require(result['sha256'] == 'd34df32b8ec8f95d62453dec4021a6f59577e72ddefb7fc2bdac4b8bb16b8351', 'reference result drift')
    binary = pin(folder / 'probe.bin')
    require(binary == {'bytes': 7248, 'sha256': 'bdb3754a8856c412661a31dae53d46bce59cc0d12407f7a807c1bb346cc1958e'}, 'reference binary drift')
    elf = (folder / 'probe.elf').read_bytes()
    require(hashlib.sha256(elf).hexdigest() == 'dedf47cfa9dd5438dd53c46b8a7915677239df310f55c7d68471895c4886a187', 'reference ELF drift')
    require(elf[:6] == b'\x7fELF\x02\x01', 'reference ELF identity')
    offset = struct.unpack_from('<Q', elf, 40)[0]
    stride, count, names = struct.unpack_from('<HHH', elf, 58)
    require(stride == 64 and 0 < names < count and offset + stride * count <= len(elf), 'reference ELF section bounds')
    sections = [struct.unpack_from('<IIQQQQIIQQ', elf, offset + n * stride) for n in range(count)]
    sh = sections[names]
    strings = elf[sh[4]:sh[4] + sh[5]]
    bss = [h for h in sections if strings[h[0]:].split(b'\0', 1)[0] == b'.bss']
    require(len(bss) == 1 and bss[0][1] == 8, 'reference BSS missing')
    linker = (folder / 'source/qemu/virt.ld').read_text(encoding='utf-8')
    require('. += 16384;' in linker, 'reference stack extent changed')
    require(bss[0][5] <= 8192, 'reference BSS exceeds allowance')
    return {'result': REFERENCE + '/result.json', 'result_sha256': result['sha256'],
            'binary': binary, 'elf_sha256': hashlib.sha256(elf).hexdigest(),
            'bss_bytes': bss[0][5], 'actual_stack_bytes': 16384,
            'modeled_arena_bytes': 4096, 'frame_bytes': 256, 'frame_count': 7,
            'linker_sha256': pin(folder / 'source/qemu/virt.ld')['sha256'],
            'a51_executable': False}


def budget():
    return {'schema_version': 1, 'scope': 'android_arena_diagnostic_budget',
        'arena_bytes': 65536, 'page_bytes': 4096, 'order': 4,
        'regions': [{'role': role, 'offset': start, 'bytes': size, 'pattern': pattern}
                    for role, start, size, pattern in REGIONS],
        'allocator_flags': ['GFP_NOWAIT', '__GFP_ZERO', '__GFP_NOWARN', '__GFP_NOMEMALLOC'],
        'reference': reference(), 'payload_budget_final': False,
        'a51_destination_selected': False, 'phase_2_device_gate_passed': False}


def validate_budget(value):
    # Exact schema and exact types: True cannot stand in for version/order/size.
    require(json.dumps(value, sort_keys=True) == json.dumps(budget(), sort_keys=True), 'budget schema/value drift')
    return value


def header(value):
    validate_budget(value)
    lines = ['/* Generated from manifests/arena-probe-budget.json. */',
             '#define AR_ORDER 4U', '#define AR_BYTES 65536UL', '#define AR_LAYOUT \\']
    for i, (_, start, size, pattern) in enumerate(REGIONS):
        suffix = ', \\' if i < len(REGIONS) - 1 else ''
        lines.append('    {' + str(start) + 'UL, ' + str(size) + 'UL, ' + hex(pattern) + '}' + suffix)
    return '\n'.join(lines) + '\n'


def flags():
    return {'module_load_verified': True, 'normal_unload_verified': True,
        'contiguous_64k_diagnostic_lifetime_verified': True, 'held_pattern_integrity_verified': True,
        'failed_init_cleanup_verified': True, 'same_android_boot_verified': True,
        'diagnostic_log_retrieval_verified': True, 'device_temporary_file_cleaned': True,
        'phone_writes': True, 'a51_loader_execution_verified': False,
        'owned_payload_destination_verified': False, 'physical_handoff_verified': False,
        'fault_logging_verified': False, 'return_after_standalone_payload_verified': False,
        'no_flash_a51_launch_verified': False, 'phase_2_device_gate_passed': False}


def lifetimes(logs, normal, failure):
    require(re.fullmatch('[0-9a-f]{16}', normal) and re.fullmatch('[0-9a-f]{16}', failure)
            and normal != failure, 'invalid run identities')
    require(type(logs) is str and len(logs) <= 65536, 'lifecycle logs exceed bound')
    entries = []
    identities = []
    for line in logs.splitlines():
        match = re.fullmatch(r'(?:\[\s*\d+\.\d+\]\s+)?HAKIOS_ARENA (run=([0-9a-f]{16}) stage=(\w+).*)', line)
        require(match is not None, 'invalid lifecycle line grammar')
        entries.append(match[1])
        identities.append((match[2], match[3]))
    require(identities == [(normal, 'acquire'), (normal, 'selfcheck'), (normal, 'loaded'),
        (normal, 'release'), (failure, 'acquire'), (failure, 'selfcheck'), (failure, 'release')],
        'global lifecycle order mismatch')
    result = []
    for run, stages, reason in [(normal, ['acquire', 'selfcheck', 'loaded', 'release'], 'unload'),
                               (failure, ['acquire', 'selfcheck', 'release'], 'requested_init_failure')]:
        run_entries = [line for line in entries if line.startswith('run=' + run + ' ')]
        acquire = re.fullmatch(r'run=' + run + r' stage=acquire phys=(0x[0-9a-fA-F]{1,16}) bytes=(\d+) order=(\d+)', run_entries[0])
        release = re.fullmatch(r'run=' + run + r' stage=release phys=(0x[0-9a-fA-F]{1,16}) bytes=(\d+) order=(\d+) reason='
            + reason + r' integrity=pass cleared=pass', run_entries[-1])
        matches = [acquire, release]
        require(all(matches) and acquire.groups() == release.groups(), 'acquire/release grammar or identity mismatch')
        phys, size, order = int(matches[0][1], 16), int(matches[0][2]), int(matches[0][3])
        require(0 < phys <= (1 << 64) - 1 - 65536 and phys % 65536 == 0
                and size == 65536 and order == 4, 'allocation bounds mismatch')
        require(run_entries[1] == 'run=' + run + ' stage=selfcheck regions=6 zero=pass pattern=pass', 'region selfcheck missing')
        if reason == 'unload':
            require(run_entries[2] == 'run=' + run + ' stage=loaded', 'loaded event grammar mismatch')
        result.append({'run_id': run, 'start': phys, 'end_exclusive': phys + size, 'bytes': size,
                       'order': order, 'release_reason': reason, 'state': 'released',
                       'active_owned_interval': False, 'safe_for_loader_placement': False})
    return result
