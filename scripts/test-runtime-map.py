#!/usr/bin/env python3
"""Guard historical memory projection and offline packet reconstruction."""
import copy
import datetime as dt
import importlib.util
import io
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import runtime_observations as observations

PROJECT = Path(__file__).resolve().parents[1]


def timestamp(second=0):
    utc = dt.datetime(2026, 11, 11, tzinfo=dt.timezone.utc) + dt.timedelta(seconds=second)
    return {'utc': utc.isoformat(),
            'ist': utc.astimezone(dt.timezone(dt.timedelta(hours=5, minutes=30))).isoformat()}


def span(start, size):
    return {'start': start, 'size': size, 'end_exclusive': start + size}


def fixture_report():
    banks = [span(0x80000000, 0x20000000), span(0x880000000, 0x10000000),
             span(0x890000000, 0x10000000)]
    banks = [item | {'enabled': True, 'node': '/memory@' + hex(item['start'])} for item in banks]
    fixed = {'node': '/reserved-memory/fixed', 'enabled': True, 'no_map': False,
             'reusable': False, 'ranges': [span(0x81000000, 0x1000)], 'dynamic_size': None}
    dynamic = {'node': '/reserved-memory/dynamic', 'enabled': True, 'no_map': False,
               'reusable': False, 'ranges': [], 'dynamic_size': 0x2000,
               'alignment': 0x1000, 'alloc_ranges': [span(0x80000000, 0x20000000)]}
    tree = {'declared_memory': banks, 'declared_memory_bytes': 0x40000000,
            'root_address_cells': 2, 'root_size_cells': 1,
            'memreserve': [span(0x82000000, 0x1000)], 'reserved_memory': [fixed, dynamic],
            'dynamic_reservations': [dynamic['node']], 'untranslated_reserved_ranges': [],
            'linux_alignment_cell_mismatches': [], 'safe_for_loader_placement': False,
            'sha256': 'a' * 64,
            'initrd_cells': {'linux,initrd-start': [0x83000000], 'linux,initrd-end': [0x83001000]}}
    iomem = [
        {'indent': 0, 'start': 0x10000000, 'end_exclusive': 0x10001000,
         'owner': 'MMIO parent', 'zero_address_record': False},
        {'indent': 2, 'start': 0x10000000, 'end_exclusive': 0x10001000,
         'owner': 'MMIO child', 'zero_address_record': False},
        {'indent': 0, 'start': 0x80000000, 'end_exclusive': 0xa0000000,
         'owner': 'System RAM', 'zero_address_record': False},
        {'indent': 2, 'start': 0x84000000, 'end_exclusive': 0x84001000,
         'owner': 'Kernel code', 'zero_address_record': False},
        {'indent': 0, 'start': 0x880000000, 'end_exclusive': 0x8a0000000,
         'owner': 'System RAM', 'zero_address_record': False},
    ]
    summary = {name: False for name in observations.FALSE_FLAGS}
    summary.update(adb_root_verified=True, single_boot_observation_verified=True,
                   live_fdt_export_verified=True, capture_complete=True,
                   live_fdt=tree, iomem=iomem, kernel_configuration={'CONFIG_KEXEC': 'n'},
                   meminfo_kib={'MemFree': 1000000, 'MemAvailable': 1000000}, query_failures=[])
    return {'schema_version': 2, 'scope': 'live_android_read_only_observations',
            'phone_writes': False, 'created': timestamp(), 'finished': timestamp(1),
            'summary': summary}


class ArithmeticGuards(unittest.TestCase):
    def test_half_open_endpoint_and_last_supported_address(self):
        self.assertEqual(observations.interval(2**64 - 2, 1), span(2**64 - 2, 1))

    def test_end_at_two_to_64_is_rejected(self):
        with self.assertRaises(ValueError):
            observations.interval(2**64 - 1, 1)

    def test_interval_rejects_boolean_string_negative_zero_and_overflow(self):
        for start, size in ((True, 1), (0, True), ('0x80000000', 1), (-1, 1),
                            (0, 0), (0, -1), (2**64, 1), (0, 2**64)):
            with self.subTest(start=start, size=size), self.assertRaises(ValueError):
                observations.interval(start, size)

    def test_union_sorts_merges_adjacency_and_does_not_double_count(self):
        records = [span(30, 10), span(10, 10), span(15, 20), span(10, 10), span(100, 2)]
        self.assertEqual(observations.union_ranges(records), [span(10, 30), span(100, 2)])

    def test_union_empty_is_empty(self):
        self.assertEqual(observations.union_ranges([]), [])

    def test_union_rejects_inconsistent_and_boolean_ends(self):
        for end in (11, True):
            with self.subTest(end=end), self.assertRaises(ValueError):
                observations.union_ranges([{'start': 0, 'size': 1, 'end_exclusive': end}])

    def test_json_rejects_duplicate_nonfinite_float_overflow_and_invalid_utf8(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}',
                    b'{"a":1e999}', b'\xff', b'\xef\xbb\xbf{}'):
            with self.subTest(raw=raw), self.assertRaises((ValueError, UnicodeError)):
                observations.strict_json(raw)

    def test_json_depth_limit_and_quoted_brackets(self):
        self.assertEqual(observations.strict_json(b'[' * 64 + b'0' + b']' * 64),
                         self.nested(64))
        with self.assertRaises(ValueError):
            observations.strict_json(b'[' * 65 + b'0' + b']' * 65)
        self.assertEqual(observations.strict_json(observations.encode({'text': '[{\\\"' * 100})),
                         {'text': '[{\\\"' * 100})

    @staticmethod
    def nested(depth):
        value = 0
        for _ in range(depth):
            value = [value]
        return value

    def test_bound_is_checked_before_file_open(self):
        parent = PROJECT / 'evidence/test-fixtures/runtime-map'
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent, prefix='read-bound-') as temporary:
            path = Path(temporary) / 'large.json'
            path.write_bytes(b'123456789')
            with mock.patch.object(Path, 'open', side_effect=AssertionError('oversized file was opened')):
                with self.assertRaisesRegex(ValueError, 'pre-read bound'):
                    observations.bounded_read(path, 8)

    def test_bounded_encoding_accepts_exact_limit_and_rejects_one_byte_less(self):
        value = {'escaped': '\u20ac"\\' * 16}
        expected = observations.encode(value)
        with mock.patch.object(observations, 'JSON_LIMIT', len(expected)):
            self.assertEqual(observations.bounded_encode(value), expected)
        with mock.patch.object(observations, 'JSON_LIMIT', len(expected) - 1):
            with self.assertRaisesRegex(ValueError, 'output bound'):
                observations.bounded_encode(value)

    def test_bounded_encoding_stops_at_overflowing_chunk(self):
        def chunks():
            yield '{}'
            yield ' ' * 32
            raise AssertionError('encoder continued after output overflow')
        encoder = mock.Mock()
        encoder.iterencode.return_value = chunks()
        with mock.patch.object(observations, 'JSON_LIMIT', 32), \
                mock.patch.object(observations.json, 'JSONEncoder', return_value=encoder):
            with self.assertRaisesRegex(ValueError, 'output bound'):
                observations.bounded_encode({})


class ProjectionGuards(unittest.TestCase):
    def setUp(self):
        self.report = fixture_report()
        self.summary = self.report['summary']
        self.tree = self.summary['live_fdt']

    def normalized(self):
        return observations.normalize(self.report)

    def test_complete_capture_keeps_all_gates_false(self):
        result = self.normalized()
        self.assertTrue(result['dram_and_iomem_unions_agree'])
        self.assertEqual(result['declared_dram_union'], [span(0x80000000, 0x20000000),
                                                        span(0x880000000, 0x20000000)])
        self.assertEqual(result['verified_owned_intervals'], [])
        self.assertTrue(all(value is False for value in result['flags'].values()))
        self.assertIs(result['phone_queries_this_import'], False)
        self.assertIs(result['phone_writes'], False)

    def test_source_schema_scope_and_write_types_are_strict(self):
        for field, value in (('schema_version', True), ('schema_version', 1),
                             ('scope', 'synthetic'), ('phone_writes', 0), ('phone_writes', True)):
            report = copy.deepcopy(self.report)
            report[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                observations.normalize(report)

    def test_incomplete_unprivileged_unstable_or_boolean_capture_is_rejected(self):
        for field in ('adb_root_verified', 'single_boot_observation_verified',
                      'live_fdt_export_verified', 'capture_complete'):
            for value in (False, 1):
                report = copy.deepcopy(self.report)
                report['summary'][field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    observations.normalize(report)

    def test_every_promoted_or_integer_source_gate_is_rejected(self):
        for field in observations.FALSE_FLAGS:
            for value in (True, 0):
                report = copy.deepcopy(self.report)
                report['summary'][field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    observations.normalize(report)

    def test_fdt_placement_gate_cannot_be_promoted(self):
        self.tree['safe_for_loader_placement'] = True
        with self.assertRaises(ValueError):
            self.normalized()

    def test_untranslated_ranges_and_cell_mismatches_are_rejected(self):
        for field in ('untranslated_reserved_ranges', 'linux_alignment_cell_mismatches'):
            report = copy.deepcopy(self.report)
            report['summary']['live_fdt'][field] = ['/reserved-memory/bus']
            with self.subTest(field=field), self.assertRaises(ValueError):
                observations.normalize(report)

    def test_overlapping_fdt_banks_are_rejected(self):
        self.tree['declared_memory'].append(copy.deepcopy(self.tree['declared_memory'][0]))
        self.tree['declared_memory_bytes'] += 0x20000000
        with self.assertRaisesRegex(ValueError, 'overlapping'):
            self.normalized()

    def test_disabled_bank_does_not_supply_dram(self):
        self.tree['declared_memory'].append(span(0x40000000, 0x1000) |
                                            {'node': '/memory-disabled', 'enabled': False})
        self.assertEqual(len(self.normalized()['declared_dram']), 3)

    def test_bank_arithmetic_and_total_types_are_rechecked(self):
        for field, value in (('start', True), ('size', 0), ('end_exclusive', 1)):
            report = copy.deepcopy(self.report)
            report['summary']['live_fdt']['declared_memory'][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                observations.normalize(report)
        self.tree['declared_memory_bytes'] = True
        with self.assertRaises(ValueError):
            self.normalized()

    def test_duplicate_linux_ram_is_union_counted_without_ownership(self):
        self.summary['iomem'].append(copy.deepcopy(self.summary['iomem'][-1]))
        result = self.normalized()
        self.assertTrue(result['dram_and_iomem_unions_agree'])
        self.assertEqual(sum(item['size'] for item in result['linux_system_ram_union']), 0x40000000)
        self.assertEqual(result['verified_owned_intervals'], [])

    def test_mismatched_ram_views_are_observed_without_gate_promotion(self):
        self.summary['iomem'][-1]['end_exclusive'] -= 0x1000
        result = self.normalized()
        self.assertIs(result['dram_and_iomem_unions_agree'], False)
        self.assertTrue(all(value is False for value in result['flags'].values()))

    def test_iomem_child_requires_containing_parent(self):
        for mutation in ('orphan', 'outside', 'nested_ram'):
            report = copy.deepcopy(self.report)
            records = report['summary']['iomem']
            if mutation == 'orphan':
                records[0]['indent'] = 2
            elif mutation == 'outside':
                records[1]['end_exclusive'] += 1
            else:
                records[1]['owner'] = 'System RAM'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                observations.normalize(report)

    def test_iomem_integer_boolean_and_endpoint_bounds_are_strict(self):
        for field, value in (('indent', False), ('start', True), ('end_exclusive', True),
                             ('end_exclusive', 2**64), ('zero_address_record', 0)):
            report = copy.deepcopy(self.report)
            report['summary']['iomem'][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                observations.normalize(report)

    def test_redacted_iomem_is_retained_without_real_extent(self):
        self.summary['iomem'].append({'indent': 0, 'start': 0, 'end_exclusive': 1,
                                     'owner': 'redacted resource', 'zero_address_record': True})
        result = self.normalized()
        self.assertEqual(result['redacted_iomem_records'], [{'record': 5, 'owner': 'redacted resource'}])
        self.assertFalse(any(item['owner'] == 'redacted resource' for item in result['observed_exclusions']))

    def test_redacted_iomem_addresses_reject_boolean_values(self):
        self.summary['iomem'].append({'indent': 0, 'start': False, 'end_exclusive': True,
                                     'owner': 'redacted', 'zero_address_record': True})
        with self.assertRaises(ValueError):
            self.normalized()

    def test_redacted_record_cannot_support_a_following_child(self):
        self.summary['iomem'] = [
            {'indent': 0, 'start': 0, 'end_exclusive': 1, 'owner': 'redacted', 'zero_address_record': True},
            {'indent': 2, 'start': 0, 'end_exclusive': 1, 'owner': 'child', 'zero_address_record': False}]
        with self.assertRaises(ValueError):
            self.normalized()

    def test_dynamic_alloc_ranges_remain_constraints_without_placement(self):
        result = self.normalized()
        dynamic = result['unplaced_dynamic_reservations'][0]
        self.assertEqual(dynamic['alloc_ranges'], [span(0x80000000, 0x20000000)])
        self.assertIsNone(dynamic['placement'])
        self.assertIs(dynamic['ownership_verified'], False)
        self.assertIn(dynamic['owner'], observations.diagnose_span(result, 0x86000000, 4096)['unresolved_dynamic_owners'])

    def test_dynamic_size_alignment_and_summary_are_checked(self):
        for field, value in (('dynamic_size', True), ('dynamic_size', 0),
                             ('alignment', True), ('alignment', 3), ('alignment', 2**64)):
            report = copy.deepcopy(self.report)
            report['summary']['live_fdt']['reserved_memory'][1][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                observations.normalize(report)
        self.tree['dynamic_reservations'] = []
        with self.assertRaises(ValueError):
            self.normalized()

    def test_no_map_and_reusable_are_both_conservative_exclusions(self):
        self.tree['reserved_memory'][0].update(no_map=True, reusable=True)
        result = self.normalized()
        diagnostic = observations.diagnose_span(result, 0x81000000, 1)
        fixed = next(item for item in diagnostic['conflicts'] if item['kind'] == 'fixed_reservation')
        self.assertIs(fixed['no_map'], True)
        self.assertIs(fixed['reusable'], True)
        self.assertIs(diagnostic['usable_for_loader'], False)

    def test_reservation_flag_types_are_strict(self):
        for field in ('enabled', 'no_map', 'reusable'):
            report = copy.deepcopy(self.report)
            report['summary']['live_fdt']['reserved_memory'][0][field] = 1
            with self.subTest(field=field), self.assertRaises(ValueError):
                observations.normalize(report)

    def test_one_cell_initrd_is_valid_with_two_cell_root(self):
        self.assertEqual(self.normalized()['initrd'], span(0x83000000, 0x1000))

    def test_two_cell_high_initrd_is_valid(self):
        self.tree['initrd_cells'] = {'linux,initrd-start': [8, 0x85000000],
                                     'linux,initrd-end': [8, 0x85001000]}
        self.assertEqual(self.normalized()['initrd'], span(0x885000000, 0x1000))

    def test_absent_initrd_is_explicitly_absent(self):
        self.tree['initrd_cells'] = {}
        self.assertIsNone(self.normalized()['initrd'])

    def test_partial_zero_reversed_outside_and_invalid_cells_are_rejected(self):
        values = [
            {'linux,initrd-start': [0x83000000]},
            {'linux,initrd-start': [0x83000000], 'linux,initrd-end': [0x83000000]},
            {'linux,initrd-start': [0x83001000], 'linux,initrd-end': [0x83000000]},
            {'linux,initrd-start': [0x40000000], 'linux,initrd-end': [0x40001000]},
            {'linux,initrd-start': [True], 'linux,initrd-end': [10]},
            {'linux,initrd-start': [2**32], 'linux,initrd-end': [10]},
            {'linux,initrd-start': [0, 0, 0], 'linux,initrd-end': [10]},
        ]
        for value in values:
            self.tree['initrd_cells'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.normalized()

    def test_known_static_gap_and_memavailable_never_authorize_placement(self):
        diagnostic = observations.diagnose_span(self.normalized(), 0x86000000, 4096)
        self.assertTrue(diagnostic['declared_dram_coverage'] and diagnostic['linux_system_ram_coverage'])
        self.assertEqual(diagnostic['conflicts'], [])
        self.assertIs(diagnostic['usable_for_loader'], False)
        self.assertIs(diagnostic['runtime_memory_ownership_verified'], False)
        self.assertIs(diagnostic['phase_2_device_gate_passed'], False)

    def test_conflict_overlap_uses_half_open_boundaries(self):
        result = self.normalized()
        before = observations.diagnose_span(result, 0x81000000 - 1, 1)
        inside = observations.diagnose_span(result, 0x81000000, 1)
        after = observations.diagnose_span(result, 0x81001000, 1)
        owner = '/reserved-memory/fixed'
        self.assertFalse(any(item['owner'] == owner for item in before['conflicts']))
        self.assertTrue(any(item['owner'] == owner for item in inside['conflicts']))
        self.assertFalse(any(item['owner'] == owner for item in after['conflicts']))

    def test_mmio_and_linux_kernel_resources_are_observed_exclusions(self):
        result = self.normalized()
        for start, owner in ((0x10000000, 'MMIO child'), (0x84000000, 'Kernel code')):
            diagnostic = observations.diagnose_span(result, start, 1)
            self.assertTrue(any(item['owner'] == owner for item in diagnostic['conflicts']))
            self.assertIs(diagnostic['usable_for_loader'], False)

    def test_kexec_enabled_cannot_prove_entry_or_ownership(self):
        self.summary['kernel_configuration']['CONFIG_KEXEC'] = 'y'
        self.assertTrue(all(value is False for value in self.normalized()['flags'].values()))

    def test_all_demonstrations_reject_loader_use(self):
        checks = observations.demonstrations(self.normalized())
        self.assertTrue(checks['cases'])
        self.assertTrue(all(case['result']['usable_for_loader'] is False for case in checks['cases']))

    def test_total_exclusion_bound_spans_multiple_reservation_nodes(self):
        fixed = self.tree['reserved_memory'][0]
        self.tree['reserved_memory'] = [dict(fixed, node='/reserved-memory/bound-' + str(number),
                                                   ranges=[span(0x81000000, 4096)] * 171)
                                        for number in range(3)]
        self.tree['dynamic_reservations'] = []
        with self.assertRaisesRegex(ValueError, 'too many observed exclusions'):
            self.normalized()

    def test_direct_diagnosis_rejects_oversized_exclusion_list(self):
        result = self.normalized()
        result['observed_exclusions'] = [result['observed_exclusions'][0]] * (observations.EXCLUSION_LIMIT + 1)
        with self.assertRaisesRegex(ValueError, 'too many observed exclusions'):
            observations.diagnose_span(result, 0x81000000, 1)

    def test_diagnostic_case_limit_accepts_boundary_and_rejects_next_case(self):
        result = self.normalized()
        records = [span(0x100000000 + number * 4096, 1) |
                   {'owner': '/reserved-memory/case-' + str(number),
                    'basis': 'synthetic_guard', 'kind': 'fixed_reservation'}
                   for number in range(observations.CASE_LIMIT - 3)]
        result['observed_exclusions'] = records[:-1]
        self.assertEqual(len(observations.demonstrations(result)['cases']), observations.CASE_LIMIT)
        result['observed_exclusions'] = records
        with self.assertRaisesRegex(ValueError, 'too many diagnostic cases'):
            observations.demonstrations(result)

    def test_conflict_limit_accepts_boundary_and_rejects_next_expansion(self):
        result = self.normalized()
        record = span(0x100000000, 4096) | {'owner': '/reserved-memory/conflict',
                  'basis': 'synthetic_guard', 'kind': 'fixed_reservation'}
        result['observed_exclusions'] = [record] * 32
        checks = observations.demonstrations(result)
        self.assertEqual(sum(len(case['result']['conflicts']) for case in checks['cases']),
                         observations.CONFLICT_LIMIT)
        self.assertTrue(all(case['result']['usable_for_loader'] is False for case in checks['cases']))
        result['observed_exclusions'].append(record)
        with self.assertRaisesRegex(ValueError, 'conflict expansion exceeds bound'):
            observations.demonstrations(result)

    def test_duplicate_reservation_amplification_is_rejected_before_output(self):
        self.tree['reserved_memory'][0]['ranges'] = [span(0x81000000, 4096)] * 128
        self.assertLess(len(observations.encode(self.report)), observations.JSON_LIMIT)
        result = self.normalized()
        with self.assertRaisesRegex(ValueError, 'conflict expansion exceeds bound'):
            observations.demonstrations(result)


class PacketGuards(unittest.TestCase):
    def setUp(self):
        self.allowed = (PROJECT / 'evidence/test-fixtures/runtime-map').resolve()
        self.allowed.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=self.allowed, prefix='packet-')
        self.root = Path(self.temporary.name).resolve()
        self.project = self.root / 'project'
        (self.project / 'scripts').mkdir(parents=True)
        self.folder = self.project / 'evidence/phase-2/runtime-map/fixture'
        self.folder.mkdir(parents=True)
        self.source = self.project / 'evidence/phase-2/live-loader/fixture/report.json'
        self.source.parent.mkdir(parents=True)
        self.report = fixture_report()
        self.source.write_bytes(observations.encode(self.report))
        self.source_index = self.source.parent / 'index.json'
        self.source_index.write_bytes(observations.encode({'schema_version': 1, 'files': {}}))
        for name in observations.TOOLS:
            shutil.copyfile(PROJECT / 'scripts' / name, self.project / 'scripts' / name)
            target = self.folder / 'tools' / name
            target.parent.mkdir(exist_ok=True)
            shutil.copyfile(PROJECT / 'scripts' / name, target)
        (self.folder / 'inputs').mkdir()
        shutil.copyfile(self.source, self.folder / 'inputs/live-report.json')
        shutil.copyfile(self.source_index, self.folder / 'inputs/live-index.json')
        projection = observations.normalize(self.report)
        checks = observations.demonstrations(projection)
        (self.folder / 'map.json').write_bytes(observations.encode(projection))
        (self.folder / 'diagnostics.json').write_bytes(observations.encode(checks))
        self.result = {'format': 'hakios.a51-runtime-map-result', 'schema_version': 1,
                       'created': timestamp(2), 'finished': timestamp(3),
                       'source': {key: {'path': path.relative_to(self.project).as_posix(),
                                        **observations.identity(path)}
                                  for key, path in (('report', self.source), ('index', self.source_index))},
                       'source_capture_files': 153,
                       'tools': {name: observations.identity(self.project / 'scripts' / name)
                                 for name in observations.TOOLS},
                       'counts': observations.counts_for(projection, checks),
                       'flags': projection['flags'], 'phone_queries': False, 'phone_writes': False}
        self.write_result()
        self.reindex()
        self.project_patch = mock.patch.object(observations, 'PROJECT', self.project)
        self.project_patch.start()
        self.source_patch = mock.patch.object(observations, 'load_source',
                                             return_value=(copy.deepcopy(self.report), 153))
        self.load_source = self.source_patch.start()

    def tearDown(self):
        self.source_patch.stop()
        self.project_patch.stop()
        if not self.root.is_relative_to(self.allowed):
            raise RuntimeError('fixture cleanup escaped intended project directory')
        self.temporary.cleanup()

    def write_result(self):
        (self.folder / 'result.json').write_bytes(observations.encode(self.result))

    def reindex(self):
        (self.folder / 'index.json').write_bytes(observations.encode(observations.packet_index(self.folder)))

    def mutate_json(self, name, mutate):
        path = self.folder / name
        value = observations.read_json(path)
        mutate(value)
        path.write_bytes(observations.encode(value))
        self.reindex()

    def validate(self):
        return observations.validate_packet(self.folder)

    def test_packet_reconstructs_and_calls_full_source_verifier(self):
        with mock.patch.object(subprocess, 'Popen', side_effect=AssertionError('process execution forbidden')):
            result = self.validate()
        self.assertEqual(result['counts']['verified_owned_intervals'], 0)
        self.load_source.assert_called_once_with(self.source)
        self.assertEqual(len(observations.read_json(self.folder / 'index.json')['files']), 10)

    def test_changed_indexed_bytes_are_rejected(self):
        with (self.folder / 'map.json').open('ab') as stream:
            stream.write(b' ')
        with self.assertRaisesRegex(ValueError, 'indexed packet bytes'):
            self.validate()

    def test_missing_role_is_rejected_before_source_verification(self):
        value = observations.read_json(self.folder / 'index.json')
        value['files'].pop('map.json')
        (self.folder / 'index.json').write_bytes(observations.encode(value))
        with self.assertRaises(ValueError):
            self.validate()
        self.load_source.assert_not_called()

    def test_extra_unindexed_file_is_rejected(self):
        (self.folder / 'extra.txt').write_bytes(b'extra')
        with self.assertRaises(ValueError):
            self.validate()

    def test_extra_empty_root_directory_is_rejected_before_source_verification(self):
        (self.folder / 'extra' / 'nested').mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, 'extra'):
            self.validate()
        self.load_source.assert_not_called()

    def test_extra_empty_input_or_tool_directory_is_rejected(self):
        for name in ('inputs', 'tools'):
            path = self.folder / name / 'empty'
            path.mkdir()
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'extra'):
                self.validate()
            path.rmdir()
        self.load_source.assert_not_called()

    def test_valid_packet_never_recursively_walks_directories(self):
        with mock.patch.object(Path, 'rglob', side_effect=AssertionError('recursive packet walk forbidden')):
            self.assertEqual(self.validate()['counts']['verified_owned_intervals'], 0)

    def test_packet_walk_stops_at_first_entry_beyond_expected_root_count(self):
        real_iterdir = Path.iterdir

        def root_entries():
            yield from real_iterdir(self.folder)
            yield self.folder / 'first-extra'
            raise AssertionError('walk consumed beyond first extra entry')

        def bounded_entries(path):
            return root_entries() if path == self.folder else real_iterdir(path)

        with mock.patch.object(Path, 'iterdir', bounded_entries):
            with self.assertRaisesRegex(ValueError, 'extra packet entry'):
                self.validate()
        self.load_source.assert_not_called()

    def test_expected_input_directory_cannot_be_replaced_by_file(self):
        inputs = self.folder / 'inputs'
        inputs.rename(self.root / 'inputs-backup')
        inputs.write_bytes(b'')
        with self.assertRaisesRegex(ValueError, 'entry type mismatch'):
            self.validate()
        self.load_source.assert_not_called()

    def test_extra_indexed_role_is_rejected(self):
        value = observations.read_json(self.folder / 'index.json')
        value['files']['extra.txt'] = {'size': 0, 'sha256': '0' * 64}
        (self.folder / 'index.json').write_bytes(observations.encode(value))
        with self.assertRaises(ValueError):
            self.validate()

    def test_index_identity_boolean_is_rejected(self):
        value = observations.read_json(self.folder / 'index.json')
        value['files']['map.json']['size'] = True
        (self.folder / 'index.json').write_bytes(observations.encode(value))
        with self.assertRaises(ValueError):
            self.validate()

    def test_index_per_file_bound_precedes_indexed_reads(self):
        value = observations.read_json(self.folder / 'index.json')
        value['files']['map.json']['size'] = observations.JSON_LIMIT + 1
        (self.folder / 'index.json').write_bytes(observations.encode(value))
        with mock.patch.object(observations, 'bounded_read', wraps=observations.bounded_read) as read:
            with self.assertRaises(ValueError):
                self.validate()
        self.assertEqual([call.args[0] for call in read.call_args_list], [self.folder / 'index.json'])

    def test_index_aggregate_bound_precedes_indexed_reads(self):
        value = observations.read_json(self.folder / 'index.json')
        for item in value['files'].values():
            item['size'] = observations.JSON_LIMIT
        (self.folder / 'index.json').write_bytes(observations.encode(value))
        with mock.patch.object(observations, 'bounded_read', wraps=observations.bounded_read) as read:
            with self.assertRaisesRegex(ValueError, 'aggregate'):
                self.validate()
        self.assertEqual([call.args[0] for call in read.call_args_list], [self.folder / 'index.json'])

    def test_actual_oversize_is_rejected_before_open(self):
        path = self.folder / 'map.json'
        path.write_bytes(b' ' * (observations.JSON_LIMIT + 1))
        real_open = Path.open

        def open_checked(item, *args, **kwargs):
            if item == path:
                raise AssertionError('oversized indexed file was opened')
            return real_open(item, *args, **kwargs)

        with mock.patch.object(Path, 'open', open_checked):
            with self.assertRaisesRegex(ValueError, 'pre-read bound'):
                self.validate()

    def test_reindexed_fabricated_map_is_rejected(self):
        self.mutate_json('map.json', lambda value: value['verified_owned_intervals'].append(span(0x86000000, 4096)))
        with self.assertRaisesRegex(ValueError, 'map does not reconstruct'):
            self.validate()

    def test_reindexed_fabricated_diagnostics_are_rejected(self):
        self.mutate_json('diagnostics.json', lambda value: value['cases'][0]['result'].update(usable_for_loader=True))
        with self.assertRaisesRegex(ValueError, 'diagnostics do not reconstruct'):
            self.validate()

    def test_reindexed_wrong_count_is_rejected(self):
        self.result['counts']['declared_banks'] = True
        self.write_result()
        self.reindex()
        with self.assertRaisesRegex(ValueError, 'counts mismatch'):
            self.validate()

    def test_reindexed_result_gate_or_phone_claim_is_rejected(self):
        self.result['flags']['safe_for_loader_placement'] = True
        self.write_result()
        self.reindex()
        with self.assertRaisesRegex(ValueError, 'promotes'):
            self.validate()

    def test_result_extra_field_is_rejected(self):
        self.result['unexpected'] = True
        self.write_result()
        self.reindex()
        with self.assertRaises(ValueError):
            self.validate()

    def test_boolean_source_capture_count_is_rejected(self):
        self.result['source_capture_files'] = True
        self.write_result()
        self.reindex()
        with self.assertRaisesRegex(ValueError, 'source capture count'):
            self.validate()

    def test_changed_original_report_and_index_pins_are_rejected(self):
        for path in (self.source, self.source_index):
            original = path.read_bytes()
            path.write_bytes(original + b' ')
            with self.subTest(path=path.name), self.assertRaisesRegex(ValueError, 'source copy/pin mismatch'):
                self.validate()
            path.write_bytes(original)
        self.load_source.assert_not_called()

    def test_reindexed_source_copy_substitution_is_rejected(self):
        self.mutate_json('inputs/live-report.json', lambda value: value.update(scope='substituted'))
        with self.assertRaisesRegex(ValueError, 'source copy/pin mismatch'):
            self.validate()

    def test_source_report_and_index_must_share_capture_directory(self):
        other = self.project / 'evidence/phase-2/live-loader/other/index.json'
        other.parent.mkdir(parents=True)
        shutil.copyfile(self.source_index, other)
        self.result['source']['index']['path'] = other.relative_to(self.project).as_posix()
        self.write_result()
        self.reindex()
        with self.assertRaisesRegex(ValueError, 'association'):
            self.validate()

    def test_source_path_traversal_is_rejected(self):
        self.result['source']['report']['path'] = '../report.json'
        self.write_result()
        self.reindex()
        with self.assertRaises(ValueError):
            self.validate()

    def test_full_source_verifier_failure_is_propagated(self):
        self.load_source.side_effect = ValueError('original capture does not reconstruct')
        with self.assertRaisesRegex(ValueError, 'does not reconstruct'):
            self.validate()

    def test_original_source_change_during_full_verification_is_rejected(self):
        def changed_source(_path):
            self.source.write_bytes(self.source.read_bytes() + b' ')
            return copy.deepcopy(self.report), 153
        self.load_source.side_effect = changed_source
        with self.assertRaises(ValueError):
            self.validate()

    def test_original_index_change_during_full_verification_is_rejected(self):
        def changed_source_index(_path):
            self.source_index.write_bytes(self.source_index.read_bytes() + b' ')
            return copy.deepcopy(self.report), 153
        self.load_source.side_effect = changed_source_index
        with self.assertRaises(ValueError):
            self.validate()

    def test_verified_report_must_equal_pinned_original_bytes(self):
        report = copy.deepcopy(self.report)
        report['summary']['meminfo_kib']['MemAvailable'] += 1
        self.load_source.return_value = (report, 153)
        with self.assertRaisesRegex(ValueError, 'verified report differs from pinned bytes'):
            self.validate()

    def test_matching_retained_and_current_tools_are_required(self):
        for path in (self.folder / 'tools/runtime_observations.py', self.project / 'scripts/runtime_observations.py'):
            original = path.read_bytes()
            path.write_bytes(original + b'\n# changed\n')
            self.reindex()
            with self.subTest(path=str(path)), self.assertRaisesRegex(ValueError, 'matching trusted'):
                self.validate()
            path.write_bytes(original)
            self.reindex()

    def test_timestamp_order_and_utc_ist_labels_are_checked(self):
        self.result['created'], self.result['finished'] = timestamp(4), timestamp(3)
        self.write_result()
        self.reindex()
        with self.assertRaisesRegex(ValueError, 'reversed'):
            self.validate()
        self.result['created'], self.result['finished'] = timestamp(2), timestamp(3)
        self.result['finished']['ist'] = self.result['finished']['utc']
        self.write_result()
        self.reindex()
        with self.assertRaisesRegex(ValueError, 'labels disagree'):
            self.validate()

    def test_reversed_source_capture_times_are_rejected(self):
        report = copy.deepcopy(self.report)
        report['created'] = timestamp(2)
        self.source.write_bytes(observations.encode(report))
        shutil.copyfile(self.source, self.folder / 'inputs/live-report.json')
        self.result['source']['report'].update(observations.identity(self.source))
        self.write_result()
        self.reindex()
        self.load_source.return_value = (report, 153)
        with self.assertRaisesRegex(ValueError, 'import predates its completed source capture'):
            self.validate()

    def test_import_cannot_predate_completed_source_capture(self):
        report = copy.deepcopy(self.report)
        report['finished'] = timestamp(3)
        self.source.write_bytes(observations.encode(report))
        shutil.copyfile(self.source, self.folder / 'inputs/live-report.json')
        self.result['source']['report'].update(observations.identity(self.source))
        self.write_result()
        self.reindex()
        self.load_source.return_value = (report, 153)
        with self.assertRaisesRegex(ValueError, 'import predates its completed source capture'):
            self.validate()


class CliGuards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('runtime_map_guard_cli', PROJECT / 'scripts/import-runtime-map.py')
        cls.cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.cli)

    def test_action_is_required(self):
        with mock.patch.object(sys, 'argv', ['import-runtime-map.py']), mock.patch('sys.stderr', io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                self.cli.main()
        self.assertEqual(raised.exception.code, 2)

    def test_import_and_replay_are_mutually_exclusive(self):
        argv = ['import-runtime-map.py', '--import-report', 'report.json', '--verify-result', 'result.json']
        with mock.patch.object(sys, 'argv', argv), mock.patch('sys.stderr', io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                self.cli.main()
        self.assertEqual(raised.exception.code, 2)

    def test_derived_output_bounds_reject_before_creating_or_writing_packet(self):
        for label, owner_length, expected_encodes in (('map', 300000, 1), ('diagnostics', 65536, 2)):
            report = fixture_report()
            fixed = report['summary']['live_fdt']['reserved_memory'][0]
            fixed['node'] = '/reserved-memory/' + 'x' * owner_length
            fixed['ranges'] = [span(0x81000000, 4096)] * 8
            self.assertLess(len(observations.encode(report)), observations.JSON_LIMIT)
            with self.subTest(output=label), \
                    mock.patch.object(observations, 'load_source', return_value=(report, 153)), \
                    mock.patch.object(observations, 'bounded_encode', wraps=observations.bounded_encode) as encode, \
                    mock.patch.object(Path, 'mkdir', side_effect=AssertionError('packet created before output bound')) as mkdir, \
                    mock.patch.object(Path, 'write_bytes', side_effect=AssertionError('packet written before output bound')) as write, \
                    mock.patch.object(self.cli.shutil, 'copyfile', side_effect=AssertionError('packet copied before output bound')) as copy:
                with self.assertRaisesRegex(ValueError, 'output bound'):
                    self.cli.capture(Path('report.json'))
                self.assertEqual(encode.call_count, expected_encodes)
                mkdir.assert_not_called()
                write.assert_not_called()
                copy.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
