"""Read-only Android v2/DT table v0/FDT v17 parsers for the retained A51 inputs.

These inspect file structure and declared addresses. They never select a load
address, apply an overlay, or establish the memory available on a live phone.
"""
from dataclasses import dataclass
import hashlib
import struct


class FormatError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise FormatError(message)


def span(data, offset, size, label):
    require(offset >= 0 and size >= 0 and offset + size <= len(data),
            label + ': outside input bounds')
    return data[offset:offset + size]


def aligned(value, alignment):
    require(alignment > 0 and alignment & (alignment - 1) == 0,
            'alignment must be a power of two')
    return (value + alignment - 1) & -alignment


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def strings(value):
    if not value:
        return []
    require(value.endswith(b'\0'), 'unterminated string property')
    try:
        return [part.decode('utf-8') for part in value[:-1].split(b'\0')]
    except UnicodeDecodeError as exc:
        raise FormatError('invalid UTF-8 string property') from exc


def cells(value):
    require(len(value) % 4 == 0, 'cell property length is not a multiple of four')
    return list(struct.unpack('>' + 'I' * (len(value) // 4), value))


def scalar(value, count=1):
    values = cells(value)
    require(len(values) == count, 'unexpected scalar cell count')
    result = 0
    for item in values:
        result = result << 32 | item
    return result


def address_range(start, size):
    require(0 <= start < 1 << 64 and 0 < size and start + size <= 1 << 64,
            'invalid/overflowing physical address range')
    return {'start': start, 'size': size, 'end_exclusive': start + size,
            'start_hex': hex(start), 'end_hex': hex(start + size)}


def reg_ranges(value, address_cells, size_cells):
    require(address_cells in (1, 2) and size_cells in (1, 2),
            'unsupported address/size cell count')
    values = cells(value)
    width = address_cells + size_cells
    require(values and len(values) % width == 0, 'incomplete reg/alloc-ranges tuple')
    return [address_range(scalar(value[i * 4:(i + address_cells) * 4], address_cells),
                          scalar(value[(i + address_cells) * 4:(i + width) * 4], size_cells))
            for i in range(0, len(values), width)]


def parse_boot(data):
    require(span(data, 0, 8, 'boot magic') == b'ANDROID!', 'unexpected Android boot magic')
    header = span(data, 0, 1660, 'v2 boot header')
    names = ('kernel_size', 'kernel_addr', 'ramdisk_size', 'ramdisk_addr',
             'second_size', 'second_addr', 'tags_addr', 'page_size', 'header_version', 'os_version')
    result = dict(zip(names, struct.unpack_from('<10I', header, 8)))
    require(result['header_version'] == 2, 'only Android boot header v2 is supported')
    page = result['page_size']
    require(2048 <= page <= 65536 and page & (page - 1) == 0, 'invalid boot page size')
    result.update(recovery_dtbo_size=struct.unpack_from('<I', header, 1632)[0],
                  recovery_dtbo_offset=struct.unpack_from('<Q', header, 1636)[0],
                  header_size=struct.unpack_from('<I', header, 1644)[0],
                  dtb_size=struct.unpack_from('<I', header, 1648)[0],
                  dtb_addr=struct.unpack_from('<Q', header, 1652)[0])
    require(result['header_size'] == 1660 and result['header_size'] <= page, 'invalid v2 header size')
    result['name'] = header[48:64].split(b'\0')[0].decode('utf-8', errors='replace')
    result['cmdline'] = ''.join(header[a:b].split(b'\0')[0].decode('utf-8', errors='replace')
                                for a, b in ((64, 576), (608, 1632)))
    require(result['kernel_size'] > 0 and result['dtb_size'] > 0, 'missing kernel or DTB section')
    sections = {}
    offset = page
    for name in ('kernel', 'ramdisk', 'second', 'recovery_dtbo', 'dtb'):
        size = result[name + '_size']
        if name == 'recovery_dtbo':
            declared = result['recovery_dtbo_offset']
            require(declared == offset if size else declared in (0, offset),
                    'recovery DTBO offset disagrees with v2 layout')
        content = span(data, offset, size, name)
        padded_end = offset + aligned(size, page)
        require(padded_end <= len(data), name + ': truncated page padding')
        sections[name] = {'offset': offset, 'size': size, 'padded_end': padded_end,
                          'sha256': sha256(content)}
        offset = padded_end
    result.update(sections=sections, payload_end=offset, trailing_bytes=len(data) - offset)
    return result


def parse_arm64_image(data):
    header = span(data, 0, 64, 'ARM64 Image header')
    require(header[56:60] == b'ARM\x64', 'missing ARM64 Image magic')
    code0, code1, text_offset, image_size, flags, res2, res3, res4, pe_offset = struct.unpack_from(
        '<IIQQQQQQ4xI', header)
    branch = None
    if code0 & 0xfc000000 == 0x14000000:
        immediate = code0 & 0x3ffffff
        branch = (immediate - (1 << 26) if immediate & (1 << 25) else immediate) * 4
    return {'text_offset': text_offset, 'image_size': image_size, 'stored_kernel_bytes': len(data),
            'flags': flags, 'endianness': 'big' if flags & 1 else 'little',
            'page_size': (None, 4096, 16384, 65536)[flags >> 1 & 3],
            'placement_any_2m_aligned_base': bool(flags & 8), 'code0': hex(code0), 'code1': hex(code1),
            'initial_branch_offset': branch, 'reserved_words': [hex(res2), hex(res3), hex(res4)],
            'pe_header_offset': pe_offset,
            'status': 'retained Linux Image header; actual Samsung execution state is unknown'}


@dataclass
class Fdt:
    header: dict
    nodes: dict
    memreserve: list


def parse_fdt(data):
    names = ('magic', 'totalsize', 'off_dt_struct', 'off_dt_strings', 'off_mem_rsvmap',
             'version', 'last_comp_version', 'boot_cpuid_phys', 'size_dt_strings', 'size_dt_struct')
    header = dict(zip(names, struct.unpack('>10I', span(data, 0, 40, 'FDT header'))))
    require(header['magic'] == 0xd00dfeed, 'unexpected FDT magic')
    require(header['version'] == 17 and header['last_comp_version'] <= 17,
            'only compatible FDT v17 is supported')
    total = header['totalsize']
    require(total >= 40, 'invalid FDT total size')
    blob = span(data, 0, total, 'FDT total size')
    ranges = [(0, 40, 'header')]
    for kind in ('struct', 'strings'):
        offset, size = header['off_dt_' + kind], header['size_dt_' + kind]
        require(offset >= 40, 'FDT ' + kind + ' overlaps header')
        span(blob, offset, size, 'FDT ' + kind)
        if kind == 'struct':
            require(offset % 4 == 0 and size % 4 == 0, 'unaligned FDT structure block')
        ranges.append((offset, offset + size, kind))
    reserve_start = header['off_mem_rsvmap']
    require(reserve_start >= 40 and reserve_start % 8 == 0, 'unaligned/header-overlapping FDT reserve map')
    position = reserve_start
    memreserve = []
    while True:
        entry = span(blob, position, 16, 'FDT reserve map terminator')
        require(not any(a < position + 16 and position < b for a, b, _ in ranges),
                'FDT reserve map overlaps another block')
        start, size = struct.unpack('>QQ', entry)
        position += 16
        if start == 0 and size == 0:
            break
        memreserve.append(address_range(start, size))
    ranges.append((reserve_start, position, 'reserve map'))
    ordered = sorted(ranges)
    require(all(a[1] <= b[0] for a, b in zip(ordered, ordered[1:])), 'overlapping FDT blocks')
    strings_block = blob[header['off_dt_strings']:header['off_dt_strings'] + header['size_dt_strings']]
    position = header['off_dt_struct']
    end = position + header['size_dt_struct']
    nodes, stack = {}, []
    root_seen = finished = False
    while position < end:
        token = struct.unpack('>I', span(blob, position, 4, 'FDT token'))[0]
        position += 4
        if token == 1:
            name_end = blob.find(b'\0', position, end)
            require(name_end >= 0, 'unterminated FDT node name')
            try:
                name = blob[position:name_end].decode('utf-8')
            except UnicodeDecodeError as exc:
                raise FormatError('invalid FDT node name') from exc
            require('/' not in name, 'invalid slash in FDT node name')
            if not stack:
                require(not root_seen and name == '', 'invalid/multiple FDT root')
                path, root_seen = '/', True
            else:
                require(name != '', 'empty child node name')
                path = stack[-1].rstrip('/') + '/' + name
            require(path not in nodes, 'duplicate FDT node')
            nodes[path] = {}
            stack.append(path)
            position = aligned(name_end + 1, 4)
        elif token == 2:
            require(stack, 'unbalanced FDT END_NODE')
            stack.pop()
        elif token == 3:
            require(stack, 'FDT property outside a node')
            require(position + 8 <= end, 'truncated FDT property header')
            length, name_offset = struct.unpack_from('>II', blob, position)
            position += 8
            require(position + length <= end, 'FDT property outside structure block')
            require(name_offset < len(strings_block), 'FDT property name outside strings block')
            name_end = strings_block.find(b'\0', name_offset)
            require(name_end >= 0, 'unterminated FDT property name')
            try:
                name = strings_block[name_offset:name_end].decode('utf-8')
            except UnicodeDecodeError as exc:
                raise FormatError('invalid FDT property name') from exc
            require(name and name not in nodes[stack[-1]], 'empty/duplicate FDT property')
            nodes[stack[-1]][name] = blob[position:position + length]
            position = aligned(position + length, 4)
        elif token == 4:
            pass
        elif token == 9:
            require(root_seen and not stack, 'premature FDT END')
            require(not any(blob[position:end]), 'nonzero data after FDT END')
            finished = True
            break
        else:
            raise FormatError('unknown FDT structure token: ' + str(token))
        require(position <= end, 'FDT node/property padding outside structure block')
    require(finished, 'missing FDT END token')
    return Fdt(header, nodes, memreserve)


def parse_dt_table(data):
    names = ('magic', 'total_size', 'header_size', 'entry_size', 'entry_count',
             'entries_offset', 'page_size', 'version')
    header = dict(zip(names, struct.unpack('>8I', span(data, 0, 32, 'DT table header'))))
    require(header['magic'] == 0xd7b7ab1e, 'unexpected Android DT table magic')
    require(header['version'] == 0 and header['header_size'] == 32 and header['entry_size'] == 32,
            'only Android DT table v0 with 32-byte entries is supported')
    total = header['total_size']
    require(total >= 32, 'invalid DT table total size')
    table = span(data, 0, total, 'DT table total size')
    page = header['page_size']
    require(4 <= page <= 65536 and page & (page - 1) == 0, 'invalid DT table page size')
    count, start = header['entry_count'], header['entries_offset']
    require(0 < count <= 4096 and start >= 32 and start % 4 == 0, 'invalid DT entry count/offset')
    span(table, start, count * 32, 'DT entries')
    occupied = [(0, 32), (start, start + count * 32)]
    entries = []
    for index in range(count):
        size, offset, identity, revision, *custom = struct.unpack_from('>8I', table, start + index * 32)
        require(offset % 4 == 0 and size >= 40, 'invalid DT blob offset/size')
        blob = span(table, offset, size, 'DT blob')
        require(not any(a < offset + size and offset < b for a, b in occupied), 'overlapping DT table entries')
        occupied.append((offset, offset + size))
        tree = parse_fdt(blob)
        entries.append({'index': index, 'offset': offset, 'size': size, 'id': identity,
                        'revision': revision, 'custom': custom, 'tree': tree,
                        'blob': blob[:tree.header['totalsize']],
                        'entry_padding_bytes': size - tree.header['totalsize']})
    return header, entries


def merged_ranges(records):
    result = []
    for start, end in sorted((r['start'], r['end_exclusive']) for r in records):
        if result and start <= result[-1][1]:
            result[-1][1] = max(result[-1][1], end)
        else:
            result.append([start, end])
    return result


def static_gaps(memory, reserved):
    result = []
    for start, end in merged_ranges(memory):
        position = start
        for a, b in merged_ranges(reserved):
            if b <= position or a >= end:
                continue
            if a > position:
                result.append(address_range(position, a - position))
            position = max(position, min(b, end))
        if position < end:
            result.append(address_range(position, end - position))
    return result


def summarize_fdt(tree):
    nodes = tree.nodes
    root = nodes['/']

    def text(props, name):
        return strings(props[name]) if name in props else []

    def enabled(path):
        while True:
            status = text(nodes[path], 'status')
            if status and status != ['okay'] and status != ['ok']:
                return False
            if path == '/':
                return True
            path = path.rsplit('/', 1)[0] or '/'

    def widths(parent):
        props = nodes[parent]
        return (scalar(props['#address-cells']) if '#address-cells' in props else 2,
                scalar(props['#size-cells']) if '#size-cells' in props else 1)

    root_address_cells, root_size_cells = widths('/')
    memory, reservations, fragments = [], [], []
    for path, props in nodes.items():
        parent = path.rsplit('/', 1)[0] or '/'
        name = path.rsplit('/', 1)[-1]
        # Linux's early memory scan uses root children. An unapplied overlay or
        # nested bus declaration does not describe the base tree's physical RAM.
        if parent == '/' and (text(props, 'device_type') == ['memory']
                              or name == 'memory' or name.startswith('memory@')):
            require('reg' in props, 'memory node has no reg property')
            for record in reg_ranges(props['reg'], *widths(parent)):
                memory.append(dict(record, node=path, enabled=enabled(path)))
        if path.startswith('/reserved-memory/'):
            record = {'node': path, 'enabled': enabled(path), 'no_map': 'no-map' in props,
                      'reusable': 'reusable' in props, 'compatible': text(props, 'compatible'),
                      'ranges': [], 'dynamic_size': None}
            ac, sc = widths(parent)
            if 'reg' in props:
                record['ranges'] = reg_ranges(props['reg'], ac, sc)
            elif 'size' in props:
                record['dynamic_size'] = scalar(props['size'], sc)
                require(record['dynamic_size'] > 0, 'zero-sized dynamic reservation')
            if 'alignment' in props:
                count = len(cells(props['alignment']))
                require(count in (1, 2), 'unsupported reservation alignment encoding')
                record['alignment'] = scalar(props['alignment'], count)
                record['alignment_cells'] = count
                # The retained drivers/of/of_reserved_mem.c reads alignment
                # with dt_root_addr_cells, while size uses dt_root_size_cells.
                record['alignment_matches_root_address_cells'] = count == root_address_cells
            if 'alloc-ranges' in props:
                record['alloc_ranges'] = reg_ranges(props['alloc-ranges'], ac, sc)
            if record['ranges'] or record['dynamic_size'] is not None:
                reservations.append(record)
        if name == '__overlay__' and parent.count('/') == 1:
            target = nodes[parent]
            fragments.append({'node': path, 'target_path': text(target, 'target-path'),
                              'target_phandle': cells(target['target']) if 'target' in target else [],
                              'model': text(props, 'model'), 'compatible': text(props, 'compatible'),
                              'declares_memory_nodes': any(
                                  p.startswith(path + '/') and any(part == 'memory' or part.startswith('memory@')
                                                                 or part == 'reserved-memory'
                                                                 for part in p[len(path) + 1:].split('/'))
                                  for p in nodes),
                              'memory_effect_verified': False})
    active_memory = [r for r in memory if r['enabled']]
    fixed = tree.memreserve + [r for entry in reservations if entry['enabled'] for r in entry['ranges']]
    ranges_untranslated = [p for p, props in nodes.items() if p.startswith('/reserved-memory')
                           and props.get('ranges')]
    revisions = {name: scalar(root[name]) for name in ('dtb-hw_rev', 'dtb-hw_rev_end',
                 'dtbo-hw_rev', 'dtbo-hw_rev_end') if name in root}
    return {'header': tree.header, 'node_count': len(nodes),
            'root_address_cells': root_address_cells, 'root_size_cells': root_size_cells,
            'model': text(root, 'model'),
            'compatible': text(root, 'compatible'), 'hardware_revision_properties': revisions,
            'declared_memory': memory, 'declared_memory_bytes': sum(b - a for a, b in merged_ranges(active_memory)),
            'memreserve': tree.memreserve, 'reserved_memory': reservations,
            'dynamic_reservations': [r['node'] for r in reservations if r['enabled'] and r['dynamic_size'] is not None],
            'linux_alignment_cell_mismatches': [r['node'] for r in reservations
                                                if r.get('alignment_matches_root_address_cells') is False],
            'untranslated_reserved_ranges': ranges_untranslated,
            'gaps_after_known_static_reservations': [] if ranges_untranslated else static_gaps(active_memory, fixed),
            'overlay_fragments': fragments, 'chosen': {k: text(nodes.get('/chosen', {}), k)
                                                      for k in ('bootargs', 'bootargs_ext', 'stdout-path')},
            'safe_for_loader_placement': False,
            'limits': 'Retained declarations only. Overlays are not applied; bootloader fixups, dynamic/secure '
                      'allocations, live FDT, entry state and a return path remain unverified.'}
