#!/usr/bin/env python3
"""Check source-trace bounds, provenance reconstruction and false-claim rejection."""
import contextlib
import copy
import importlib.util
import io
from pathlib import Path
import shutil
import unittest

import source_trace as trace


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


boot_guards = module('trace_boot_fixtures', 'test-boot-audit.py')


class TraceBundle(unittest.TestCase):
    def setUp(self):
        self.fixture = boot_guards.AuditIntegrity('test_valid_fixture')
        self.fixture.setUp()
        self.root = self.fixture.root
        self.addCleanup(self.cleanup_fixture)
        for name in trace.TOOL_FILES:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(trace.PROJECT / name, target)
        self.source_root = self.root / 'linux'
        (self.source_root / 'arch').mkdir(parents=True)
        (self.source_root / 'mm').mkdir()
        (self.source_root / 'arch/entry.S').write_bytes(b'entry:\r\nmov x0, x1\r\nret')
        (self.source_root / 'mm/alloc.c').write_bytes(b'int reserve(void) { return 0; }\n')
        config = b'# CONFIG_DEBUG_FS is not set\nCONFIG_SAMSUNG_PRODUCT_SHIP=y\nCONFIG_RANDOMIZE_BASE=y\nCONFIG_SEC_PM_DEBUG=y\n'
        lineage = trace.json_bytes({'kernel_source': 'https://example.test/linux/commit/' + trace.audit.LINUX_COMMIT})
        for name, content in [('kernel.config', config), ('repack-validation.json', lineage)]:
            path = self.root / 'inputs' / name
            path.write_bytes(content)
            copied = 'references/' + name
            (self.fixture.folder / copied).write_bytes(content)
            self.fixture.report['references'].append({**trace.audit.record(path)[0], 'retained_copy': copied})
        self.fixture.report['counts'] = trace.audit.counts_for(self.fixture.report)
        self.fixture.write_report_and_index()
        self.spec = {
            'schema_version': 1, 'target': 'a51-retained-source',
            'source_root': str(self.source_root), 'lineage_commit': trace.audit.LINUX_COMMIT,
            'boot_report': {'path': 'audit/report.json', 'sha256': trace.sha256((self.fixture.folder / 'report.json').read_bytes())},
            'config_symbols': ['CONFIG_DEBUG_FS', 'CONFIG_SAMSUNG_PRODUCT_SHIP', 'CONFIG_RANDOMIZE_BASE', 'CONFIG_SEC_PM_DEBUG', 'CONFIG_UNKNOWN'],
            'sources': [
                {'path': 'arch/entry.S', 'excerpts': [{'id': 'entry', 'start': 1, 'end': 3, 'purpose': 'Fixture entry bytes'}]},
                {'path': 'mm/alloc.c', 'excerpts': [{'id': 'allocation', 'start': 1, 'end': 1, 'purpose': 'Fixture allocator bytes'}]},
            ],
        }
        self.spec_path = self.root / 'manifests/loader-source-trace.json'
        self.spec_path.parent.mkdir()
        self.spec_path.write_bytes(trace.json_bytes(self.spec))
        self.folder = self.root / 'trace'
        with contextlib.redirect_stdout(io.StringIO()):
            trace.capture_trace(self.spec_path, self.folder, self.root)

    def cleanup_fixture(self):
        allowed = (trace.PROJECT / 'evidence/test-fixtures').resolve()
        if not self.root.resolve().is_relative_to(allowed):
            raise RuntimeError('fixture cleanup escaped its workspace')
        self.fixture.doCleanups()

    def verify(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return trace.verify_trace(self.folder / 'report.json', self.root)

    def reindex(self):
        files = {p.relative_to(self.folder).as_posix(): p.read_bytes()
                 for p in self.folder.rglob('*') if p.is_file() and p.name != 'index.json'}
        (self.folder / 'index.json').write_bytes(trace.json_bytes(trace.make_index(files)))

    def mutate_report(self, update):
        path = self.folder / 'report.json'
        report = trace.decode_json(path.read_bytes())
        update(report)
        path.write_bytes(trace.json_bytes(report))
        self.reindex()

    def mutate_index(self, update):
        path = self.folder / 'index.json'
        index = trace.decode_json(path.read_bytes())
        update(index)
        path.write_bytes(trace.json_bytes(index))

    def test_valid_trace_reconstructs_originals_and_excerpts(self):
        report = self.verify()
        self.assertEqual(report['counts']['source_files'], 2)
        self.assertEqual(report['counts']['excerpts'], 2)
        self.assertEqual(report['counts']['base_fdts'], 3)
        self.assertTrue(all(report[key] is False for key in trace.FALSE_FLAGS))
        self.assertEqual((self.folder / 'excerpts/entry.txt').read_bytes(), b'1:entry:\r\n2:mov x0, x1\r\n3:ret')

    def test_same_size_original_source_drift(self):
        path = self.source_root / 'arch/entry.S'
        path.write_bytes(path.read_bytes().replace(b'mov', b'nop'))
        with self.assertRaisesRegex(ValueError, 'reconstruction'):
            self.verify()

    def test_retained_source_corruption(self):
        path = self.folder / 'sources/arch/entry.S'
        path.write_bytes(path.read_bytes().replace(b'mov', b'nop'))
        with self.assertRaisesRegex(ValueError, 'trace file changed'):
            self.verify()

    def test_reindexed_source_substitution(self):
        (self.folder / 'sources/arch/entry.S').write_bytes(b'other source\n')
        self.reindex()
        with self.assertRaisesRegex(ValueError, 'reconstructed file set'):
            self.verify()

    def test_reindexed_excerpt_substitution(self):
        (self.folder / 'excerpts/entry.txt').write_bytes(b'1:invented observation\n')
        self.reindex()
        with self.assertRaisesRegex(ValueError, 'reconstructed file set'):
            self.verify()

    def test_reindexed_config_claim(self):
        self.mutate_report(lambda r: r['configuration']['facts']['CONFIG_DEBUG_FS'].update(value='y'))
        with self.assertRaisesRegex(ValueError, 'reconstruction'):
            self.verify()

    def test_reindexed_fdt_claim(self):
        self.mutate_report(lambda r: r['base_fdts'][0]['facts'].update(psci={'decoded': {'method': ['smc']}}))
        with self.assertRaisesRegex(ValueError, 'reconstruction'):
            self.verify()

    def test_integer_cannot_replace_false_flag(self):
        self.mutate_report(lambda r: r.update(runtime_memory_ownership_verified=0))
        with self.assertRaisesRegex(ValueError, 'runtime/device claim'):
            self.verify()

    def test_boolean_cannot_replace_line_number(self):
        self.mutate_report(lambda r: r['configuration']['facts']['CONFIG_DEBUG_FS'].update(line=True))
        with self.assertRaisesRegex(ValueError, 'reconstruction'):
            self.verify()

    def test_missing_indexed_file(self):
        (self.folder / 'excerpts/entry.txt').unlink()
        with self.assertRaisesRegex(ValueError, 'missing input'):
            self.verify()

    def test_unindexed_file(self):
        (self.folder / 'extra.txt').write_bytes(b'extra')
        with self.assertRaisesRegex(ValueError, 'unindexed trace files'):
            self.verify()

    def test_reindexed_extra_file(self):
        (self.folder / 'extra.txt').write_bytes(b'extra')
        self.reindex()
        with self.assertRaisesRegex(ValueError, 'reconstructed file set'):
            self.verify()

    def test_index_directory_escape(self):
        self.mutate_index(lambda i: i['files'][0].update(path='../outside.txt'))
        with self.assertRaisesRegex(ValueError, 'escaping relative path'):
            self.verify()

    def test_index_absolute_windows_path(self):
        self.mutate_index(lambda i: i['files'][0].update(path='C:/outside.txt'))
        with self.assertRaisesRegex(ValueError, 'relative path characters'):
            self.verify()

    def test_duplicate_index_path(self):
        self.mutate_index(lambda i: i['files'].append(copy.deepcopy(i['files'][0])))
        with self.assertRaisesRegex(ValueError, 'duplicate/self-referential'):
            self.verify()

    def test_self_referential_index(self):
        self.mutate_index(lambda i: i['files'][0].update(path='index.json'))
        with self.assertRaisesRegex(ValueError, 'duplicate/self-referential'):
            self.verify()

    def test_boolean_indexed_size(self):
        self.mutate_index(lambda i: i['files'][0].update(size=True))
        with self.assertRaisesRegex(ValueError, 'invalid indexed size'):
            self.verify()

    def test_oversized_index_is_rejected_before_decode(self):
        (self.folder / 'index.json').write_bytes(b' ' * (trace.MAX_JSON + 1))
        with self.assertRaisesRegex(ValueError, 'byte limit'):
            self.verify()

    def test_reindexed_oversized_report_is_rejected_before_decode(self):
        (self.folder / 'report.json').write_bytes(b' ' * (trace.MAX_JSON + 1))
        self.reindex()
        with self.assertRaisesRegex(ValueError, 'byte limit'):
            self.verify()

    def test_reindexed_oversized_fdt_is_rejected_before_reconstruction(self):
        report = trace.decode_json((self.folder / 'report.json').read_bytes())
        path = self.folder / report['base_fdts'][0]['input']['copy']
        path.write_bytes(b' ' * (trace.MAX_FDT + 1))
        self.reindex()
        with self.assertRaisesRegex(ValueError, 'byte limit'):
            self.verify()

    def test_oversized_original_source_is_not_captured(self):
        with (self.source_root / 'arch/entry.S').open('wb') as stream:
            stream.truncate(trace.MAX_FILE + 1)
        other = self.root / 'not-created'
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(ValueError, 'byte limit'):
            trace.capture_trace(self.spec_path, other, self.root)
        self.assertFalse(other.exists())

    def test_oversized_spec_is_not_captured(self):
        self.spec_path.write_bytes(b' ' * (trace.MAX_JSON + 1))
        other = self.root / 'not-created'
        with self.assertRaisesRegex(ValueError, 'byte limit'):
            trace.capture_trace(self.spec_path, other, self.root)
        self.assertFalse(other.exists())

    def test_changed_boot_report_pin_is_not_captured(self):
        self.spec['boot_report']['sha256'] = '0' * 64
        self.spec_path.write_bytes(trace.json_bytes(self.spec))
        other = self.root / 'not-created'
        with self.assertRaisesRegex(ValueError, 'boot report hash changed'):
            trace.capture_trace(self.spec_path, other, self.root)
        self.assertFalse(other.exists())

    def test_excerpts_must_fit_the_source(self):
        self.spec['sources'][0]['excerpts'][0]['end'] = 4
        self.spec_path.write_bytes(trace.json_bytes(self.spec))
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(ValueError, 'outside source lines'):
            trace.capture_trace(self.spec_path, self.root / 'not-created', self.root)

    def test_changed_tool_revision_requires_matching_replay(self):
        path = self.root / 'scripts/run.py'
        path.write_bytes(path.read_bytes() + b'# different revision\n')
        with self.assertRaisesRegex(ValueError, 'reconstruction'):
            self.verify()

    def test_capture_never_overwrites_a_retained_folder(self):
        with self.assertRaisesRegex(ValueError, 'already exists'):
            trace.capture_trace(self.spec_path, self.folder, self.root)


class TracePrimitives(unittest.TestCase):
    def test_path_normalization_and_traversal_rejection(self):
        for value in ('.', '..', '../file', '/file', 'a/../file', 'a//file', 'a\\file', 'a/', 'C:/file'):
            with self.subTest(path=value), self.assertRaises(ValueError):
                trace.relative_path(value)

    def test_duplicate_json_keys_rejected(self):
        with self.assertRaisesRegex(ValueError, 'duplicate JSON key'):
            trace.decode_json(b'{"schema_version":1,"schema_version":true}')

    def test_nonfinite_json_rejected(self):
        with self.assertRaisesRegex(ValueError, 'nonfinite'):
            trace.decode_json(b'{"size":NaN}')

    def test_overflowing_json_numbers_rejected(self):
        for value in (b'1e309', b'-1e309'):
            with self.subTest(number=value), self.assertRaisesRegex(ValueError, 'nonfinite'):
                trace.decode_json(b'{"size":' + value + b'}')

    def test_configuration_duplicates_rejected(self):
        with self.assertRaisesRegex(ValueError, 'duplicate configuration'):
            trace.config_facts(b'CONFIG_DEBUG_FS=y\n# CONFIG_DEBUG_FS is not set\n', ['CONFIG_DEBUG_FS'])

    def test_missing_configuration_is_unknown(self):
        facts = trace.config_facts(b'# unrelated\n', ['CONFIG_UNKNOWN'])
        self.assertEqual(facts['CONFIG_UNKNOWN'], {'value': None, 'line': None, 'text': None})

    def test_exact_excerpt_line_endings(self):
        self.assertEqual(trace.numbered_excerpt(b'a\r\nb\nlast', 2, 3), b'2:b\n3:last')

    def test_boolean_excerpt_bounds_rejected(self):
        with self.assertRaisesRegex(ValueError, 'outside source lines'):
            trace.numbered_excerpt(b'one\n', True, 1)

    def test_fdt_facts_decode_original_cells_and_strings(self):
        f = boot_guards.fixtures
        blob = f.fdt({'#address-cells': f.cell(2), '#size-cells': f.cell(2),
                      'psci': {'compatible': b'arm,psci\0', 'method': b'smc\0', 'cpu_on': f.cell(0xc4000003)},
                      'reboot': {'compatible': b'exynos,reboot\0', 'pmu_base': f.cell(0x11860000)},
                      'reserved-memory': {'#address-cells': f.cell(2), '#size-cells': f.cell(2), 'ranges': b'',
                                          'dynamic': {'size': f.cell(0, 4096), 'alignment': f.cell(0, 4096)}}})
        facts = trace.fdt_facts(blob)
        self.assertEqual(facts['psci']['decoded']['cpu_on'], [0xc4000003])
        self.assertEqual(facts['reboot']['decoded']['compatible'], ['exynos,reboot'])
        self.assertEqual(facts['reboot']['decoded']['pmu_base'], [0x11860000])
        self.assertEqual(facts['dynamic_nodes']['/reserved-memory/dynamic']['decoded']['size'], [0, 4096])
        self.assertEqual(facts['reserved_memory'][0]['node'], '/reserved-memory/dynamic')
        self.assertIs(facts['safe_for_loader_placement'], False)
        self.assertIs(facts['live_selection_verified'], False)


if __name__ == '__main__':
    unittest.main(verbosity=2)
