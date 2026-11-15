#!/usr/bin/env python3
"""Meaningful host guards for full extents, uncertain ownership and replayed evidence."""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest

import payload_layout as layout


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


cli = module('layout_cli', 'validate-payload-layout.py')


class Fixture(unittest.TestCase):
    def setUp(self):
        fixture_root = layout.PROJECT / 'evidence/test-fixtures'
        fixture_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='payload-layout-', dir=fixture_root)
        self.root = Path(self.temp.name).resolve()
        # TemporaryDirectory cleanup is restricted to this checked, newly created fixture.
        self.assertTrue(self.root.is_relative_to(fixture_root.resolve()))
        self.addCleanup(self.temp.cleanup)
        self.pins = []
        for relative, raw in cli.synthetic_files().items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            self.pins.append(layout.pin(path, 'synthetic-fdt' if relative.endswith('.dtb') else 'synthetic-input'))
        self.manifest = cli.synthetic_manifest(self.pins)
        self.base = self.manifest['memory']['allowed'][0]['start']
        self.prov = self.manifest['memory']['allowed'][0]['provenance']

    def comp(self, role, data=None):
        return next(rec for rec in (data or self.manifest)['components'] if rec['role'] == role)

    def assess(self, data=None):
        result = layout.evaluate(self.manifest if data is None else data)
        for key in ('safe_for_loader_placement', 'phase_2_device_gate_passed', 'phone_writes'):
            self.assertIs(result[key], False)
        return result

    def accepted(self, data=None):
        result = self.assess(data)
        self.assertTrue(result['host_validation_passed'], result['issues'])
        self.assertEqual(result['status'], 'accepted_synthetic_host_only')
        return result

    def rejected(self, code, location=None, data=None):
        result = self.assess(data)
        self.assertFalse(result['host_validation_passed'])
        self.assertTrue(any(issue['code'] == code and (location is None or issue['location'] == location)
                            for issue in result['issues']), result['issues'])
        return result

    def new_input(self, raw, role, kind):
        path = self.root / (role + '-new.bin')
        path.write_bytes(raw)
        rec = layout.pin(path, role + '-new')
        self.manifest['evidence'].append(rec)
        self.comp(role).update(format=kind, image={'evidence': rec['id'], 'offset': 0,
                                                 'size': rec['size'], 'sha256': rec['sha256']})

    def exclusion(self, start, size=4096, identifier='excluded'):
        return {'id': identifier, 'start': start, 'size': size, 'owner': identifier, 'provenance': self.prov}

    def dynamic(self):
        rec = {'id': 'dynamic', 'owner': 'synthetic DMA', 'size': 0x4000, 'alignment': 0x1000,
               'alloc_ranges': [{'start': self.base + 0x100000, 'size': 0x100000}],
               'placement': {'start': self.base + 0x180000, 'size': 0x4000},
               'declaration': self.prov, 'placement_provenance': self.prov}
        self.manifest['memory']['dynamic'] = [rec]
        return rec


class ArithmeticAndExtent(Fixture):
    def test_positive_above_4_gib_and_all_separate_roles(self):
        result = self.accepted()
        self.assertEqual(len(result['components']), 9)
        self.assertTrue(all(rec['reservation']['start'] > 0xffffffff for rec in result['components']))
        self.assertGreater(self.comp('kernel')['execution_bytes'], self.comp('kernel')['image']['size'])

    def test_hex_addresses_and_sizes_are_not_truncated(self):
        for rec in self.manifest['components']:
            rec['start'], rec['execution_bytes'] = hex(rec['start']), hex(rec['execution_bytes'])
        allowed = self.manifest['memory']['allowed'][0]
        allowed['start'], allowed['size'] = hex(allowed['start']), hex(allowed['size'])
        self.accepted()

    def test_positive_near_64_bit_upper_boundary(self):
        delta = ((1 << 64) - 0x300000) - self.base
        self.manifest['memory']['allowed'][0]['start'] += delta
        for rec in self.manifest['components']:
            rec['start'] += delta
        self.accepted()

    def test_adjacent_components_do_not_overlap(self):
        for i, rec in enumerate(self.manifest['components']):
            rec.update(start=self.base + (i + 1) * 4096, execution_bytes=4096)
        self.accepted()

    def test_exact_allowed_exclusive_end(self):
        allowed = self.manifest['memory']['allowed'][0]
        self.comp('logs')['start'] = allowed['start'] + allowed['size'] - 4096
        self.accepted()
        self.comp('logs')['execution_bytes'] += 1
        self.rejected('component_outside_allowed')

    def test_touching_reservation_boundary_is_permitted(self):
        self.manifest['memory']['excluded'] = [self.exclusion(self.comp('loader')['start'] + 4096)]
        self.accepted()

    def test_one_component_cannot_span_adjacent_allowed_intervals(self):
        allowed = self.manifest['memory']['allowed'][0]
        self.manifest['memory']['allowed'] = [
            dict(allowed, id='left', size=0x5000),
            dict(allowed, id='right', start=self.base + 0x5000, size=0x1fb000)]
        self.comp('loader')['execution_bytes'] = 8192
        self.rejected('component_outside_allowed', 'components.loader')

    def test_discontiguous_bank_hole_is_not_ram(self):
        self.manifest['memory']['allowed'] = [
            {'id': 'low', 'start': 0x80000000, 'size': 0x80000000, 'provenance': self.prov},
            {'id': 'high', 'start': 0x880000000, 'size': 0x80000000, 'provenance': self.prov}]
        self.comp('loader')['start'] = 0x100000000
        self.rejected('component_outside_allowed', 'components.loader')

    def test_noninteger_negative_boolean_and_overwide_addresses(self):
        for value in (-1, True, 1.5, '4294967296', '0x', 1 << 64, '0x10000000000000000'):
            with self.subTest(value=value):
                data = copy.deepcopy(self.manifest)
                self.comp('loader', data)['start'] = value
                self.rejected('u64_bounds', data=data)

    def test_zero_and_negative_execution_sizes(self):
        for value in (0, -1, False):
            with self.subTest(value=value):
                data = copy.deepcopy(self.manifest)
                self.comp('kernel', data)['execution_bytes'] = value
                self.rejected('u64_bounds', data=data)

    def test_zero_memory_interval(self):
        self.manifest['memory']['allowed'][0]['size'] = 0
        self.rejected('u64_bounds')

    def test_invalid_alignments(self):
        for value in (0, 3, -2, True, 1 << 64):
            with self.subTest(value=value):
                data = copy.deepcopy(self.manifest)
                self.comp('loader', data)['alignment'] = value
                self.rejected('alignment_value' if value == 3 else 'u64_bounds', data=data)

    def test_interval_end_at_2_to_64_is_rejected(self):
        self.manifest['memory']['allowed'][0].update(start=(1 << 64) - 4096, size=4096)
        self.rejected('u64_overflow')

    def test_execution_addition_overflow(self):
        self.comp('loader').update(start=(1 << 64) - 4096, execution_bytes=4096)
        self.rejected('u64_overflow', 'components.loader')

    def test_alignment_roundup_overflow(self):
        self.comp('loader').update(start=(1 << 64) - 4096, execution_bytes=2048)
        self.rejected('u64_overflow', 'components.loader')

    def test_suffix_addition_overflow(self):
        self.comp('loader')['suffix_bytes'] = layout.U64_MAX
        self.rejected('u64_overflow')

    def test_prefix_underflow(self):
        self.comp('loader').update(start=16, alignment=1, reserve_alignment=1, prefix_bytes=17)
        self.rejected('u64_underflow', 'components.loader')

    def test_misaligned_content(self):
        self.comp('loader')['start'] += 1
        self.rejected('component_alignment', 'components.loader')

    def test_alignment_padding_before_content_is_excluded(self):
        start = self.comp('loader')['start']
        self.comp('loader')['prefix_bytes'] = 1
        self.manifest['memory']['excluded'] = [self.exclusion(start - 4096)]
        self.rejected('reserved_overlap', 'components.loader')

    def test_suffix_and_padding_after_content_are_excluded(self):
        start = self.comp('loader')['start']
        self.comp('loader')['suffix_bytes'] = 1
        self.manifest['memory']['excluded'] = [self.exclusion(start + 4096)]
        self.rejected('reserved_overlap', 'components.loader')

    def test_expanded_extent_overlaps_another_component(self):
        self.comp('payload')['execution_bytes'] = 0x5000
        self.rejected('components_overlap')

    def test_bss_stack_page_tables_scratch_and_logs_cannot_alias_loader(self):
        for role in layout.MEMORY_ROLES:
            with self.subTest(role=role):
                data = copy.deepcopy(self.manifest)
                self.comp(role, data)['start'] = self.comp('loader', data)['start']
                self.rejected('components_overlap', data=data)

    def test_every_required_component_role_is_enforced(self):
        for role in layout.ROLES:
            with self.subTest(role=role):
                data = copy.deepcopy(self.manifest)
                data['components'] = [rec for rec in data['components'] if rec['role'] != role]
                self.rejected('component_role_missing', 'components.' + role, data=data)

    def test_unplaced_and_unknown_execution_extents(self):
        self.comp('loader').update(start=None, execution_bytes=None)
        self.rejected('component_unplaced', 'components.loader')
        self.rejected('execution_extent_unresolved', 'components.loader')

    def test_conditional_execution_extent_is_not_supported(self):
        self.comp('kernel')['extent_provenance'] = dict(self.prov, state='conditional')
        self.rejected('execution_extent_unverified', 'components.kernel')

    def test_stored_file_cannot_exceed_execution_extent(self):
        self.comp('kernel')['execution_bytes'] = self.comp('kernel')['image']['size'] - 1
        self.rejected('execution_extent_too_small', 'components.kernel')

    def test_arm64_image_effective_extent_includes_unstored_bytes(self):
        raw = struct.pack('<IIQQQQQQ4sI', 0x14000010, 0, 0x80000, 0x10000, 10, 0, 0, 0, b'ARM\x64', 0)
        self.new_input(raw, 'kernel', 'arm64-image')
        self.comp('kernel').update(start=self.base + 0x100000, execution_bytes=64)
        self.rejected('execution_extent_too_small', 'components.kernel')
        self.comp('kernel')['execution_bytes'] = 0x10000
        result = self.accepted()
        self.assertEqual(next(rec for rec in result['components'] if rec['role'] == 'kernel')['minimum_execution_bytes'], 0x10000)

    def test_legacy_image_with_zero_extent_is_unknown(self):
        raw = struct.pack('<IIQQQQQQ4sI', 0x14000010, 0, 0x80000, 0, 10, 0, 0, 0, b'ARM\x64', 0)
        self.new_input(raw, 'kernel', 'arm64-image')
        self.rejected('execution_extent_unverified', 'components.kernel')

    def test_observed_exclusions_are_enforced_individually(self):
        spans = [self.exclusion(self.base + 0x100000 + i * 0x4000, identifier='reserved-' + str(i))
                 for i in range(15)]
        self.manifest['memory']['excluded'] = spans
        self.accepted()
        for span in spans:
            with self.subTest(owner=span['owner']):
                data = copy.deepcopy(self.manifest)
                self.comp('loader', data)['start'] = span['start']
                result = self.rejected('reserved_overlap', 'components.loader', data=data)
                self.assertTrue(any(span['owner'] in issue['message'] for issue in result['issues']))


class IntegrityAndEntry(Fixture):
    def test_truncated_input(self):
        path = Path(self.pins[0]['path'])
        path.write_bytes(path.read_bytes()[:-1])
        self.rejected('input_size')

    def test_same_size_input_drift(self):
        path = Path(self.pins[0]['path'])
        raw = bytearray(path.read_bytes())
        raw[-1] ^= 1
        path.write_bytes(raw)
        self.rejected('input_checksum')

    def test_missing_input(self):
        Path(self.pins[0]['path']).unlink()
        self.rejected('input_unavailable')

    def test_slice_outside_file(self):
        self.comp('kernel')['image']['offset'] = self.pins[0]['size']
        self.rejected('component_input_bounds', 'components.kernel')

    def test_slice_checksum_drift(self):
        self.comp('kernel')['image']['sha256'] = '0' * 64
        self.rejected('component_checksum', 'components.kernel')

    def test_slice_addition_overflow(self):
        self.comp('kernel')['image']['offset'] = layout.U64_MAX
        self.rejected('u64_overflow')

    def test_rehashed_invalid_fdt_still_fails(self):
        self.new_input(b'\0' * 72, 'fdt', 'fdt')
        self.rejected('component_binary_format', 'components.fdt')

    def test_fdt_trailing_bytes_are_not_silently_accepted(self):
        self.new_input(cli.synthetic_files()['inputs/synthetic.dtb'] + b'extra', 'fdt', 'fdt')
        self.rejected('component_fdt_bounds', 'components.fdt')

    def test_fdt_execution_size_cannot_truncate_tree(self):
        self.comp('fdt')['execution_bytes'] = 40
        self.rejected('execution_extent_too_small', 'components.fdt')

    def test_nonfile_bss_cannot_be_declared_as_raw_input(self):
        self.comp('bss').update(format='raw', image=copy.deepcopy(self.comp('kernel')['image']))
        self.rejected('component_format', 'components.bss')

    def test_file_backed_loader_requires_an_input(self):
        self.comp('loader')['image'] = None
        self.rejected('component_input_missing', 'components.loader')

    def test_raw_entry_cannot_point_into_zero_extension(self):
        self.manifest['entry']['offset'] = 1024
        self.rejected('entry_bounds', 'entry')

    def test_entry_at_exclusive_extent_end(self):
        self.manifest['entry']['offset'] = self.comp('loader')['execution_bytes']
        self.rejected('entry_bounds', 'entry')

    def test_entry_must_select_loader(self):
        for name in ('kernel', 'stack', 'absent'):
            with self.subTest(name=name):
                data = copy.deepcopy(self.manifest)
                data['entry']['component'] = name
                self.rejected('entry_component', 'entry', data=data)

    def test_entry_alignment(self):
        self.manifest['entry']['offset'] = 1
        self.rejected('entry_alignment', 'entry')

    def test_entry_overflow(self):
        self.comp('loader').update(start=layout.U64_MAX - 7, alignment=1)
        self.manifest['entry']['offset'] = 8
        self.rejected('u64_overflow', 'entry')

    def test_schema_rejects_unknown_fields_and_versions(self):
        for field, value in (('schema_version', 2), ('schema_version', True), ('extra', False)):
            with self.subTest(field=field, value=value):
                data = copy.deepcopy(self.manifest)
                data[field] = value
                self.rejected('manifest_schema', data=data)

    def test_duplicate_ids_and_undefined_evidence(self):
        self.manifest['components'][1]['id'] = self.manifest['components'][0]['id']
        self.rejected('duplicate_id')
        self.manifest['components'][1]['id'] = 'kernel'
        self.comp('kernel')['image']['evidence'] = 'absent'
        self.rejected('evidence_reference')

    def test_duplicate_json_and_nonfinite_numbers(self):
        for raw, code in ((b'{"format":1,"format":2}', 'duplicate_json_key'), (b'{"value":NaN}', 'manifest_schema')):
            with self.subTest(raw=raw):
                result = layout.evaluate_bytes(raw)
                self.assertFalse(result['host_validation_passed'])
                self.assertEqual(result['issues'][0]['code'], code)

    def test_json_and_combined_input_limits(self):
        result = layout.evaluate_bytes(b' ' * (layout.MAX_JSON_BYTES + 1))
        self.assertEqual(result['issues'][0]['code'], 'json_bounds')
        self.manifest['evidence'][0]['size'] = layout.MAX_INPUT_BYTES + 1
        self.rejected('input_bounds')

    def test_malformed_reference_type_is_a_schema_error(self):
        self.comp('kernel')['image']['evidence'] = []
        self.rejected('manifest_schema')


class Ownership(Fixture):
    def test_each_entry_fdt_memory_logging_return_prerequisite_is_required(self):
        for key in layout.PREREQUISITES:
            for state in ('unknown', 'conditional'):
                with self.subTest(prerequisite=key, state=state):
                    data = copy.deepcopy(self.manifest)
                    data['prerequisites'][key] = dict(self.prov, state=state)
                    self.rejected('prerequisite_unresolved', 'prerequisites.' + key, data=data)

    def test_source_declaration_cannot_become_a_runtime_prerequisite(self):
        self.manifest['prerequisites']['entry_route'] = dict(self.prov, basis='source_declaration')
        self.rejected('prerequisite_unverified', 'prerequisites.entry_route')

    def test_declared_ram_runtime_label_and_unknown_intervals_are_not_allowlists(self):
        for state, basis in (('observed', 'source_declaration'), ('observed', 'runtime_observation'),
                             ('unknown', 'synthetic'), ('conditional', 'synthetic')):
            with self.subTest(state=state, basis=basis):
                data = copy.deepcopy(self.manifest)
                data['memory']['allowed'][0]['provenance'] = dict(self.prov, state=state, basis=basis)
                self.rejected('allowed_interval_unverified', data=data)

    def test_unknown_excluded_ownership_blocks_layout(self):
        rec = self.exclusion(self.base + 0x100000)
        rec['provenance'] = dict(self.prov, state='conditional')
        self.manifest['memory']['excluded'] = [rec]
        self.rejected('exclusion_unresolved')

    def test_overlapping_allowed_intervals_are_ambiguous(self):
        rec = dict(self.manifest['memory']['allowed'][0], id='overlap')
        self.manifest['memory']['allowed'].append(rec)
        self.rejected('allowed_intervals_overlap')

    def test_fully_declared_synthetic_dynamic_placement_is_accepted(self):
        self.dynamic()
        self.accepted()

    def test_unplaced_dynamic_reservation_blocks_even_an_unused_gap(self):
        self.dynamic()['placement'] = None
        self.rejected('dynamic_ownership_unresolved')

    def test_unknown_dynamic_alignment(self):
        self.dynamic()['alignment'] = None
        self.rejected('dynamic_alignment_unresolved')

    def test_partial_dynamic_placement(self):
        self.dynamic()['placement']['size'] -= 1
        self.rejected('dynamic_size')

    def test_dynamic_alignment_violation(self):
        self.dynamic()['placement']['start'] += 1
        self.rejected('dynamic_alignment')

    def test_dynamic_allocation_constraints_are_not_locations(self):
        self.dynamic()['alloc_ranges'] = [{'start': self.base + 0x160000, 'size': 0x10000}]
        self.rejected('dynamic_alloc_range')

    def test_dynamic_placement_outside_owned_interval(self):
        self.dynamic()['placement']['start'] = self.base + 0x200000
        self.rejected('dynamic_outside_allowed')

    def test_dynamic_placement_overlaps_static_reservation(self):
        rec = self.dynamic()
        self.manifest['memory']['excluded'] = [self.exclusion(rec['placement']['start'])]
        self.rejected('dynamic_reserved_overlap')

    def test_dynamic_placement_overlaps_loader(self):
        self.dynamic()['placement']['start'] = self.comp('loader')['start']
        self.rejected('reserved_overlap', 'components.loader')

    def test_dynamic_placements_cannot_overlap_each_other(self):
        rec = self.dynamic()
        self.manifest['memory']['dynamic'].append(dict(rec, id='other'))
        self.rejected('dynamic_placements_overlap')

    def test_dynamic_size_owner_and_placement_evidence_must_be_observed(self):
        for field in ('declaration', 'placement_provenance'):
            with self.subTest(field=field):
                data = copy.deepcopy(self.manifest)
                rec = self.dynamic()
                data['memory']['dynamic'] = [copy.deepcopy(rec)]
                data['memory']['dynamic'][0][field] = dict(self.prov, state='conditional')
                self.rejected('dynamic_declaration_unresolved' if field == 'declaration' else 'dynamic_ownership_unresolved',
                              data=data)

    def test_dynamic_runtime_label_is_unsupported(self):
        self.dynamic()['placement_provenance'] = dict(self.prov, basis='runtime_observation')
        self.rejected('dynamic_ownership_unverified')

    def test_a51_target_cannot_omit_retained_binding(self):
        self.manifest['target'] = 'a51-retained-host'
        self.rejected('target_binding')


class EvidenceReplay(Fixture):
    def setUp(self):
        super().setUp()
        self.folder = self.root / 'bundle'
        self.folder.mkdir()
        generated, pins = [], []
        for relative, raw in cli.synthetic_files().items():
            path = self.folder / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            generated.append(cli.file_record(path, self.folder))
            pins.append(cli.project_pin(path, 'synthetic-fdt' if relative.endswith('.dtb') else 'synthetic-input'))
        self.result = cli.capture(self.folder, 'demonstrate_synthetic',
                                  [('synthetic-host-example', cli.encode(cli.synthetic_manifest(pins)), True, [])],
                                  layout.Inputs(), generated)

    def reindex(self):
        (self.folder / 'result.json').write_bytes(cli.encode(self.result))
        files = [cli.file_record(p, self.folder) for p in sorted(self.folder.rglob('*'))
                 if p.is_file() and p != self.folder / 'index.json']
        (self.folder / 'index.json').write_bytes(cli.encode({'schema_version': 1, 'files': files, 'limits': 'test'}))

    def verify(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return cli.verify_result(self.folder / 'result.json')

    def test_valid_retained_synthetic_example_replays(self):
        self.assertEqual(self.verify()['counts']['accepted'], 1)

    def test_same_size_manifest_corruption(self):
        path = self.folder / self.result['cases'][0]['manifest']['path']
        raw = bytearray(path.read_bytes())
        raw[-1] ^= 1
        path.write_bytes(raw)
        with self.assertRaisesRegex(layout.LayoutError, 'Indexed layout evidence changed'):
            self.verify()

    def test_missing_indexed_file(self):
        (self.folder / 'inputs/synthetic.dtb').unlink()
        with self.assertRaises(FileNotFoundError):
            self.verify()

    def test_evidence_path_escape(self):
        index = layout.json_bytes((self.folder / 'index.json').read_bytes())
        index['files'][0]['path'] = '../escape'
        (self.folder / 'index.json').write_bytes(cli.encode(index))
        with self.assertRaisesRegex(layout.LayoutError, 'escapes'):
            self.verify()

    def test_unindexed_file(self):
        (self.folder / 'extra.txt').write_text('unexpected', encoding='utf-8')
        with self.assertRaisesRegex(layout.LayoutError, 'unindexed'):
            self.verify()

    def test_reindexed_host_outcome_is_rejected_by_recomputation(self):
        self.result['cases'][0]['assessment']['host_validation_passed'] = False
        self.reindex()
        with self.assertRaisesRegex(layout.LayoutError, 'differs from replay'):
            self.verify()

    def test_reindexed_numeric_boolean_cannot_change_json_evidence_types(self):
        self.result['cases'][0]['assessment']['host_validation_passed'] = 1
        self.reindex()
        with self.assertRaisesRegex(layout.LayoutError, 'differs from replay'):
            self.verify()

    def test_reindexed_numeric_count_cannot_be_replaced_with_boolean(self):
        self.result['counts']['accepted'] = True
        self.reindex()
        with self.assertRaisesRegex(layout.LayoutError, 'Counts'):
            self.verify()

    def test_reindexed_device_claims_are_rejected(self):
        for flag in ('phone_writes', 'safe_for_loader_placement', 'phase_2_device_gate_passed', 'a51_destination_selected'):
            with self.subTest(flag=flag):
                self.result[flag] = True
                self.reindex()
                with self.assertRaisesRegex(layout.LayoutError, 'Unsupported device'):
                    self.verify()
                self.result[flag] = False

    def test_reindexed_component_omission_cannot_change_demo(self):
        case = self.result['cases'][0]
        path = self.folder / case['manifest']['path']
        manifest = layout.json_bytes(path.read_bytes())
        manifest['components'].pop()
        path.write_bytes(cli.encode(manifest))
        case['manifest'] = cli.file_record(path, self.folder)
        case['assessment'] = layout.evaluate(manifest)
        self.reindex()
        with self.assertRaisesRegex(layout.LayoutError, 'differs from reconstruction'):
            self.verify()

    def test_reindexed_counts_and_expected_status(self):
        self.result['counts']['accepted'] = 10
        self.reindex()
        with self.assertRaisesRegex(layout.LayoutError, 'Counts'):
            self.verify()

    def test_reindexed_generated_input_is_not_a_new_fixture(self):
        path = self.folder / 'inputs/synthetic-input.txt'
        path.write_bytes(b'X' * path.stat().st_size)
        self.reindex()
        with self.assertRaisesRegex(layout.LayoutError, 'Synthetic fixture changed'):
            self.verify()

    def test_candidate_replay_keeps_exact_original_manifest_snapshot(self):
        folder = self.root / 'candidate'
        folder.mkdir()
        raw = cli.encode(self.manifest)
        source = self.root / 'source.json'
        source.write_bytes(raw)
        result = cli.capture(folder, 'validate_manifest', [('candidate', raw, None, [])], layout.Inputs(),
                             source_pin=layout.pin(source, 'source-manifest'))
        source.write_text('original candidate edited later', encoding='utf-8')
        with contextlib.redirect_stdout(io.StringIO()):
            replay = cli.verify_result(folder / 'result.json')
        self.assertEqual(result, replay)

    def test_reindexed_false_pass_for_a_rejected_candidate_is_rejected(self):
        folder = self.root / 'rejected'
        folder.mkdir()
        self.manifest['prerequisites']['entry_route'] = layout.unknown('Entry unavailable')
        raw = cli.encode(self.manifest)
        source = self.root / 'rejected-source.json'
        source.write_bytes(raw)
        result = cli.capture(folder, 'validate_manifest', [('candidate', raw, None, [])], layout.Inputs(),
                             source_pin=layout.pin(source, 'source-manifest'))
        self.assertFalse(result['cases'][0]['assessment']['host_validation_passed'])
        result['cases'][0]['assessment']['host_validation_passed'] = True
        (folder / 'result.json').write_bytes(cli.encode(result))
        files = [cli.file_record(p, folder) for p in sorted(folder.rglob('*'))
                 if p.is_file() and p != folder / 'index.json']
        (folder / 'index.json').write_bytes(cli.encode({'schema_version': 1, 'files': files, 'limits': 'test'}))
        with self.assertRaisesRegex(layout.LayoutError, 'differs from replay'):
            cli.verify_result(folder / 'result.json')

    def test_empty_manifest_retains_a_replayable_rejection(self):
        folder = self.root / 'empty'
        folder.mkdir()
        source = self.root / 'empty-source.json'
        source.write_bytes(b'')
        result = cli.capture(folder, 'validate_manifest', [('candidate', b'', None, [])], layout.Inputs(),
                             source_pin=layout.pin(source, 'source-manifest'))
        self.assertFalse(result['cases'][0]['assessment']['host_validation_passed'])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(result, cli.verify_result(folder / 'result.json'))

    def test_empty_candidate_manifest_size_cannot_be_replaced_with_boolean(self):
        folder = self.root / 'empty-size-type'
        folder.mkdir()
        source = self.root / 'empty-size-source.json'
        source.write_bytes(b'')
        result = cli.capture(folder, 'validate_manifest', [('candidate', b'', None, [])], layout.Inputs(),
                             source_pin=layout.pin(source, 'source-manifest'))
        result['cases'][0]['manifest']['size'] = False
        (folder / 'result.json').write_bytes(cli.encode(result))
        files = [cli.file_record(p, folder) for p in sorted(folder.rglob('*'))
                 if p.is_file() and p != folder / 'index.json']
        (folder / 'index.json').write_bytes(cli.encode({'schema_version': 1, 'files': files, 'limits': 'test'}))
        with self.assertRaisesRegex(layout.LayoutError, 'Manifest identity differs'):
            cli.verify_result(folder / 'result.json')

    def test_index_file_is_bounded_before_json_parsing(self):
        (self.folder / 'index.json').write_bytes(b' ' * (layout.MAX_JSON_BYTES + 1))
        with self.assertRaisesRegex(layout.LayoutError, 'Evidence file exceeds'):
            self.verify()

    def test_oversized_case_snapshot_is_rejected_at_evidence_boundary(self):
        folder = self.root / 'oversized-case'
        folder.mkdir()
        source = self.root / 'oversized-source.json'
        raw = b' ' * (layout.MAX_JSON_BYTES + 1)
        source.write_bytes(raw)
        cli.capture(folder, 'validate_manifest', [('candidate', raw, None, [])], layout.Inputs(),
                    source_pin=layout.pin(source, 'source-manifest'))
        with self.assertRaisesRegex(layout.LayoutError, 'Evidence file exceeds'):
            cli.verify_result(folder / 'result.json')


class RetainedA51(unittest.TestCase):
    def setUp(self):
        audit_tests = module('layout_audit_fixtures', 'test-boot-audit.py')
        self.audit, fixtures = audit_tests.audit, audit_tests.fixtures
        self.fixture = audit_tests.AuditIntegrity()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.assertTrue(self.fixture.root.is_relative_to((layout.PROJECT / 'evidence/test-fixtures').resolve()))
        tree = fixtures.fdt({
            '#address-cells': fixtures.cell(2), '#size-cells': fixtures.cell(1),
            'memory@80000000': {'reg': fixtures.cell(0, 0x80000000, 0x80000000)},
            'memory@880000000': {'reg': fixtures.cell(8, 0x80000000, 0x80000000)},
            'memory@900000000': {'reg': fixtures.cell(9, 0, 0x80000000)},
            'reserved-memory': {'#address-cells': fixtures.cell(2), '#size-cells': fixtures.cell(1), 'ranges': b'',
                                'modem_if': {'reg': fixtures.cell(0, 0xed000000, 0x08a00000)},
                                'dynamic_fixture': {'size': fixtures.cell(0x10000), 'alignment': fixtures.cell(0, 0x1000)}}})
        images, generated, pins = [], {}, []
        for old in self.fixture.report['images']:
            path = Path(old['input']['path'])
            content = fixtures.table(tree) if old['name'] == 'original-dtbo' else fixtures.boot(
                dt=fixtures.table(tree), recovery_dtbo=fixtures.table(tree) if old['name'] == 'recovery' else b'')
            path.write_bytes(content)
            pin = self.audit.record(path)[0]
            pins.append(pin)
            image, blobs = self.audit.inspect_image(pin, 9)
            images.append(image)
            generated.update(blobs)
        inventory = Path(self.fixture.report['inventory']['path'])
        inventory.write_text(json.dumps({'retained_inputs': pins, 'device_queries': [
            {'argv': ['getprop', 'ro.boot.revision'], 'exit_code': 0, 'output': '9\n'}]}), encoding='utf-8')
        self.fixture.report.update(images=images, inventory=self.audit.record(inventory)[0])
        self.fixture.report['counts'] = self.audit.counts_for(self.fixture.report)
        for relative, raw in generated.items():
            (self.fixture.folder / relative).write_bytes(raw)
        self.fixture.write_report_and_index()
        self.pin = layout.pin(self.fixture.folder / 'report.json', 'boot-audit')

    def cases(self):
        return cli.a51_cases(self.pin, layout.Inputs())

    def test_verified_source_declarations_remain_unusable_for_a51(self):
        name, manifest, passed, required = self.cases()[0]
        result = layout.evaluate(manifest)
        self.assertFalse(result['host_validation_passed'])
        self.assertEqual(len(result['memory']['declared']), 3)
        self.assertEqual(len(result['memory']['excluded']), 1)
        self.assertEqual(len(result['memory']['dynamic']), 1)
        self.assertEqual(result['memory']['allowed'], [])
        self.assertIs(result['safe_for_loader_placement'], False)

    def test_all_fixture_a51_diagnostics_are_expected_rejections(self):
        inputs = layout.Inputs()
        for name, manifest, passed, required in self.cases():
            with self.subTest(case=name):
                case = {'assessment': layout.evaluate(manifest, inputs),
                        'expected_host_validation_passed': passed, 'required_issues': required}
                self.assertTrue(cli.meets_expectation(case), case['assessment']['issues'])

    def test_caller_cannot_omit_imported_modem_exclusion_or_dynamic_owner(self):
        manifest = next(case[1] for case in self.cases() if case[0] == 'qemu-modem-address')
        manifest['memory']['excluded'] = []
        manifest['memory']['dynamic'] = []
        result = layout.evaluate(manifest)
        self.assertTrue(any(issue['code'] == 'reserved_overlap' and 'modem_if' in issue['message']
                            for issue in result['issues']))
        self.assertTrue(any(issue['code'] == 'dynamic_ownership_unresolved' for issue in result['issues']))

    def test_reindexed_false_source_summary_is_rejected_against_original_bytes(self):
        self.fixture.report['images'][0]['tables'][0]['entries'][0]['summary']['reserved_memory'] = []
        self.fixture.write_report_and_index()
        changed = layout.pin(self.fixture.folder / 'report.json', 'boot-audit')
        binding = {'evidence': changed['id'], 'image': 'original-boot', 'section': 'dtb', 'entry_index': 0}
        result = layout.evaluate(cli.base_manifest('a51-retained-host', [changed], binding))
        self.assertTrue(any(issue['code'] == 'retained_audit_integrity' for issue in result['issues']), result['issues'])

    def test_unapplied_overlay_is_not_a_ram_allowlist(self):
        binding = {'evidence': self.pin['id'], 'image': 'original-dtbo', 'section': 'dtbo', 'entry_index': 0}
        result = layout.evaluate(cli.base_manifest('a51-retained-host', [self.pin], binding))
        self.assertTrue(any(issue['code'] == 'retained_audit_selection' for issue in result['issues']), result['issues'])

    def test_a51_binding_cannot_be_relabelled_synthetic(self):
        manifest = self.cases()[0][1]
        manifest['target'] = 'synthetic-host'
        result = layout.evaluate(manifest)
        self.assertEqual(result['issues'][0]['code'], 'target_binding')


if __name__ == '__main__':
    unittest.main(verbosity=2)
