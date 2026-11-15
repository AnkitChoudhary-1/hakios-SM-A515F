#!/usr/bin/env python3
"""Guard binary input bounds and the limits of retained-tree memory analysis."""
import struct
import unittest

import boot_formats as formats


def cell(*values):
    return struct.pack('>' + 'I' * len(values), *values)


def padded(value, alignment=4):
    return value + b'\0' * (-len(value) % alignment)


def fdt(properties=None, reservations=()):
    names = bytearray()
    offsets = {}

    def node(name, properties):
        result = cell(1) + padded(name.encode() + b'\0')
        for key, value in properties.items():
            if isinstance(value, dict):
                continue
            if key not in offsets:
                offsets[key] = len(names)
                names.extend(key.encode() + b'\0')
            result += cell(3, len(value), offsets[key]) + padded(value)
        for key, value in properties.items():
            if isinstance(value, dict):
                result += node(key, value)
        return result + cell(2)

    structure = node('', properties or {}) + cell(9)
    reserve = b''.join(struct.pack('>QQ', a, b) for a, b in reservations) + b'\0' * 16
    structure_offset = 40 + len(reserve)
    names_offset = structure_offset + len(structure)
    header = cell(0xd00dfeed, names_offset + len(names), structure_offset, names_offset,
                  40, 17, 16, 0, len(names), len(structure))
    return header + reserve + structure + names


def table(*blobs):
    offset = 32 + 32 * len(blobs)
    entries, payload = b'', b''
    for blob in blobs:
        entries += cell(len(blob), offset, 0, 0, 0, 0, 0, 0)
        payload += padded(blob)
        offset += len(padded(blob))
    return cell(0xd7b7ab1e, offset, 32, 32, len(blobs), 32, 2048, 0) + entries + payload


def boot(dt=None, recovery_dtbo=b''):
    kernel = struct.pack('<IIQQQQQQ4sI', 0x14000010, 0, 0x80000, 4096, 10, 0, 0xecefecef,
                         0, b'ARM\x64', 0)
    dt = table(fdt()) if dt is None else dt
    header = bytearray(2048)
    header[:8] = b'ANDROID!'
    struct.pack_into('<10I', header, 8, len(kernel), 0x10008000, 3, 0x11000000,
                     0, 0, 0x10000100, 2048, 2, 0)
    struct.pack_into('<IQIIQ', header, 1632, len(recovery_dtbo), 6144 if recovery_dtbo else 0,
                     1660, len(dt), 0x10000000)
    return bytes(header) + padded(kernel, 2048) + padded(b'ram', 2048) + padded(recovery_dtbo, 2048) + padded(dt, 2048)


def changed(data, offset, value, endian='>I'):
    result = bytearray(data)
    struct.pack_into(endian, result, offset, value)
    return bytes(result)


class BootBounds(unittest.TestCase):
    def test_realistic_v2_offsets_and_image_header(self):
        data = boot(recovery_dtbo=table(fdt()))
        header = formats.parse_boot(data)
        self.assertEqual(header['sections']['recovery_dtbo']['offset'], 6144)
        self.assertEqual(header['sections']['dtb']['offset'], 8192)
        image = formats.parse_arm64_image(data[2048:2112])
        self.assertEqual((image['text_offset'], image['image_size'], image['page_size']), (0x80000, 4096, 4096))
        self.assertEqual(image['initial_branch_offset'], 64)

    def test_extended_cmdline_is_preserved(self):
        data = bytearray(boot())
        data[64:70] = b'first\0'
        data[608:615] = b' extra\0'
        self.assertEqual(formats.parse_boot(data)['cmdline'], 'first extra')

    def test_truncated_header(self):
        with self.assertRaisesRegex(formats.FormatError, 'bounds'):
            formats.parse_boot(boot()[:1659])

    def test_unsupported_version(self):
        with self.assertRaisesRegex(formats.FormatError, 'v2'):
            formats.parse_boot(changed(boot(), 40, 3, '<I'))

    def test_bad_page_size(self):
        for value in (0, 512, 3000, 131072):
            with self.subTest(value=value), self.assertRaisesRegex(formats.FormatError, 'page'):
                formats.parse_boot(changed(boot(), 36, value, '<I'))

    def test_incorrect_header_size(self):
        with self.assertRaisesRegex(formats.FormatError, 'header size'):
            formats.parse_boot(changed(boot(), 1644, 1648, '<I'))

    def test_kernel_extent_outside_input(self):
        with self.assertRaisesRegex(formats.FormatError, 'bounds'):
            formats.parse_boot(changed(boot(), 8, 0xffffffff, '<I'))

    def test_recovery_dtbo_cannot_overlap_ramdisk(self):
        with self.assertRaisesRegex(formats.FormatError, 'offset'):
            formats.parse_boot(changed(boot(recovery_dtbo=table(fdt())), 1636, 2048, '<Q'))

    def test_truncated_padding_rejected(self):
        with self.assertRaisesRegex(formats.FormatError, 'padding'):
            formats.parse_boot(boot()[:-1])

    def test_wrong_arm64_magic(self):
        with self.assertRaisesRegex(formats.FormatError, 'Image magic'):
            formats.parse_arm64_image(b'\0' * 64)


class DtTableBounds(unittest.TestCase):
    def test_multiple_blobs_and_big_endian_fields(self):
        header, entries = formats.parse_dt_table(table(fdt(), fdt({'model': b'other\0'})))
        self.assertEqual(header['entry_count'], 2)
        self.assertEqual(entries[1]['tree'].nodes['/']['model'], b'other\0')

    def test_oversized_entry_count(self):
        with self.assertRaisesRegex(formats.FormatError, 'count|bounds'):
            formats.parse_dt_table(changed(table(fdt()), 16, 4096))

    def test_total_size_exceeds_input(self):
        with self.assertRaisesRegex(formats.FormatError, 'bounds'):
            formats.parse_dt_table(changed(table(fdt()), 4, 0xffffffff))

    def test_blob_cannot_overlap_header_or_entries(self):
        for value in (0, 32):
            with self.subTest(value=value), self.assertRaisesRegex(formats.FormatError, 'overlap'):
                formats.parse_dt_table(changed(table(fdt()), 36, value))

    def test_blobs_cannot_overlap_each_other(self):
        data = table(fdt(), fdt())
        first_offset = struct.unpack_from('>I', data, 36)[0]
        with self.assertRaisesRegex(formats.FormatError, 'overlap'):
            formats.parse_dt_table(changed(data, 68, first_offset))

    def test_blob_outside_table(self):
        with self.assertRaisesRegex(formats.FormatError, 'bounds'):
            formats.parse_dt_table(changed(table(fdt()), 32, 0xffffffff))

    def test_unsupported_compressed_v1(self):
        with self.assertRaisesRegex(formats.FormatError, 'v0'):
            formats.parse_dt_table(changed(table(fdt()), 28, 1))


class FdtBounds(unittest.TestCase):
    def test_valid_empty_root(self):
        self.assertEqual(formats.parse_fdt(fdt()).nodes, {'/': {}})

    def test_total_size_exceeds_input(self):
        with self.assertRaisesRegex(formats.FormatError, 'bounds'):
            formats.parse_fdt(changed(fdt(), 4, 0xffffffff))

    def test_overlapping_blocks(self):
        data = fdt({'model': b'test\0'})
        offset = struct.unpack_from('>I', data, 8)[0]
        with self.assertRaisesRegex(formats.FormatError, 'overlap'):
            formats.parse_fdt(changed(data, 12, offset))

    def test_unterminated_reserve_map(self):
        data = changed(fdt(), 40, 1, '>Q')
        data = changed(data, 48, 1, '>Q')
        with self.assertRaisesRegex(formats.FormatError, 'overlap|terminator'):
            formats.parse_fdt(data)

    def test_property_length_exceeds_structure_block(self):
        data = fdt({'model': b'test\0'})
        offset = struct.unpack_from('>I', data, 8)[0] + 12
        with self.assertRaisesRegex(formats.FormatError, 'property outside'):
            formats.parse_fdt(changed(data, offset, 0xffffffff))

    def test_property_name_offset_exceeds_strings(self):
        data = fdt({'model': b'test\0'})
        offset = struct.unpack_from('>I', data, 8)[0] + 16
        with self.assertRaisesRegex(formats.FormatError, 'name outside'):
            formats.parse_fdt(changed(data, offset, 0xffffffff))

    def test_unterminated_node_name(self):
        data = bytearray(fdt())
        start = struct.unpack_from('>I', data, 8)[0] + 4
        end = struct.unpack_from('>I', data, 12)[0]
        data[start:end] = b'x' * (end - start)
        with self.assertRaisesRegex(formats.FormatError, 'unterminated'):
            formats.parse_fdt(bytes(data))

    def test_premature_end_cannot_hide_nodes(self):
        data = fdt()
        offset = struct.unpack_from('>I', data, 8)[0] + 8
        with self.assertRaisesRegex(formats.FormatError, 'premature'):
            formats.parse_fdt(changed(data, offset, 9))

    def test_unsupported_fdt_version(self):
        with self.assertRaisesRegex(formats.FormatError, 'v17'):
            formats.parse_fdt(changed(fdt(), 20, 16))


class MemoryMeaning(unittest.TestCase):
    def test_64_bit_memory_static_overlap_and_dynamic_unknown(self):
        data = fdt({'#address-cells': cell(2), '#size-cells': cell(2),
                    'memory@100000000': {'device_type': b'memory\0', 'reg': cell(1, 0, 0, 0x10000)},
                    'reserved-memory': {'#address-cells': cell(2), '#size-cells': cell(2), 'ranges': b'',
                        'fixed': {'reg': cell(1, 0x1000, 0, 0x2000), 'no-map': b''},
                        'dynamic': {'size': cell(0, 0x4000)},
                        'disabled': {'size': cell(0, 0x8000), 'status': b'disabled\0'}}},
                   reservations=[(0x100002000, 0x2000)])
        summary = formats.summarize_fdt(formats.parse_fdt(data))
        self.assertEqual(summary['declared_memory_bytes'], 0x10000)
        self.assertEqual(summary['dynamic_reservations'], ['/reserved-memory/dynamic'])
        self.assertEqual([(r['start'], r['size']) for r in summary['gaps_after_known_static_reservations']],
                         [(0x100000000, 0x1000), (0x100004000, 0xc000)])
        self.assertFalse(summary['safe_for_loader_placement'])

    def test_partial_reg_tuple_is_rejected(self):
        data = fdt({'memory@0': {'reg': cell(0, 0)}})
        with self.assertRaisesRegex(formats.FormatError, 'incomplete'):
            formats.summarize_fdt(formats.parse_fdt(data))

    def test_physical_range_cannot_overflow_64_bits(self):
        with self.assertRaisesRegex(formats.FormatError, 'overflow'):
            formats.address_range((1 << 64) - 8, 16)

    def test_nested_reservations_and_ancestor_status(self):
        data = fdt({'reserved-memory': {'debug': {'#address-cells': cell(1), '#size-cells': cell(1),
                              'reg-child': {'reg': cell(0x8000, 0x100)}},
                                       'disabled-group': {'status': b'disabled\0',
                              'child': {'reg': cell(0, 0x9000, 0x100)}}}})
        summary = formats.summarize_fdt(formats.parse_fdt(data))
        self.assertEqual(len(summary['reserved_memory']), 2)
        self.assertTrue(summary['reserved_memory'][0]['enabled'])
        self.assertFalse(summary['reserved_memory'][1]['enabled'])

    def test_nonempty_reserved_bus_ranges_suppress_gap_output(self):
        data = fdt({'memory@0': {'reg': cell(0, 0, 0x10000)},
                    'reserved-memory': {'ranges': cell(0, 0, 0), 'fixed': {'reg': cell(0, 0x1000, 0x1000)}}})
        summary = formats.summarize_fdt(formats.parse_fdt(data))
        self.assertEqual(summary['untranslated_reserved_ranges'], ['/reserved-memory'])
        self.assertEqual(summary['gaps_after_known_static_reservations'], [])

    def test_overlay_revision_and_model_are_not_live_selection(self):
        data = fdt({'dtbo-hw_rev': cell(7), 'dtbo-hw_rev_end': cell(255),
                    'fragment@0': {'target-path': b'/\0', '__overlay__': {'model': b'A51 REV02\0'}}})
        summary = formats.summarize_fdt(formats.parse_fdt(data))
        self.assertEqual(summary['hardware_revision_properties'], {'dtbo-hw_rev': 7, 'dtbo-hw_rev_end': 255})
        self.assertEqual(summary['overlay_fragments'][0]['model'], ['A51 REV02'])
        self.assertFalse(summary['safe_for_loader_placement'])

    def test_linux_alignment_uses_address_cells_without_asserting_allocation(self):
        data = fdt({'reserved-memory': {'#address-cells': cell(2), '#size-cells': cell(1),
                    'ion_video_stream': {'size': cell(0x4800000), 'alignment': cell(0, 0x400000)}}})
        summary = formats.summarize_fdt(formats.parse_fdt(data))
        entry = summary['reserved_memory'][0]
        self.assertEqual(entry['alignment'], 0x400000)
        self.assertEqual(entry['alignment_cells'], 2)
        self.assertTrue(entry['alignment_matches_root_address_cells'])
        self.assertEqual(summary['linux_alignment_cell_mismatches'], [])
        self.assertFalse(summary['safe_for_loader_placement'])

    def test_alignment_size_cells_are_not_substituted_for_address_cells(self):
        data = fdt({'#address-cells': cell(1), '#size-cells': cell(2),
                    'reserved-memory': {'#address-cells': cell(1), '#size-cells': cell(2),
                        'matches': {'size': cell(0, 0x1000), 'alignment': cell(0x1000)},
                        'differs': {'size': cell(0, 0x1000), 'alignment': cell(0, 0x1000)}}})
        summary = formats.summarize_fdt(formats.parse_fdt(data))
        self.assertTrue(summary['reserved_memory'][0]['alignment_matches_root_address_cells'])
        self.assertEqual(summary['linux_alignment_cell_mismatches'], ['/reserved-memory/differs'])

    def test_unapplied_overlay_memory_is_not_base_ram(self):
        data = fdt({'memory@0': {'reg': cell(0, 0, 0x10000)},
                    'fragment@0': {'target-path': b'/\0', '__overlay__': {
                        'memory@20000': {'device_type': b'memory\0', 'reg': cell(0, 0x20000, 0x10000)}}}})
        summary = formats.summarize_fdt(formats.parse_fdt(data))
        self.assertEqual(summary['declared_memory_bytes'], 0x10000)
        self.assertTrue(summary['overlay_fragments'][0]['declares_memory_nodes'])
        self.assertFalse(summary['overlay_fragments'][0]['memory_effect_verified'])
        self.assertFalse(summary['safe_for_loader_placement'])

    def test_local_fixup_metadata_is_not_an_overlay_fragment(self):
        data = fdt({'fragment@0': {'target': cell(0xffffffff), '__overlay__': {'model': b'A51\0'}},
                    '__local_fixups__': {'fragment@0': {'__overlay__': {'phandle': cell(0)}}}})
        summary = formats.summarize_fdt(formats.parse_fdt(data))
        self.assertEqual([r['node'] for r in summary['overlay_fragments']], ['/fragment@0/__overlay__'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
