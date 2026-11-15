#!/usr/bin/env python3
"""Exercise corruption and false-claim rejection using disposable audit fixtures."""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


audit = module('boot_audit', 'audit-boot-inputs.py')
fixtures = module('boot_fixtures', 'test-boot-formats.py')


class AuditIntegrity(unittest.TestCase):
    def setUp(self):
        fixture_root = audit.PROJECT / 'evidence/test-fixtures'
        fixture_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='boot-audit-', dir=fixture_root)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.folder = self.root / 'audit'
        self.folder.mkdir()
        inputs = self.root / 'inputs'
        inputs.mkdir()
        pinned = []
        images, generated = [], {}
        tree = fixtures.fdt({'model': b'A51 fixture\0', 'memory@0': {'reg': fixtures.cell(0, 0, 0x10000)}})
        for basename, role in audit.IMAGE_NAMES.items():
            content = fixtures.table(tree) if role == 'original-dtbo' else fixtures.boot(
                dt=fixtures.table(tree), recovery_dtbo=fixtures.table(tree) if role == 'recovery' else b'')
            path = inputs / basename
            path.write_bytes(content)
            pin = audit.record(path)[0]
            pinned.append(pin)
            image, blobs = audit.inspect_image(pin, 9)
            images.append(image)
            generated.update(blobs)
        inventory_path = inputs / 'inventory.json'
        inventory_path.write_text(json.dumps({'retained_inputs': pinned, 'device_queries': [
            {'argv': ['getprop', 'ro.boot.revision'], 'exit_code': 0, 'output': '9\n'}]}), encoding='utf-8')
        source = inputs / 'source.txt'
        source.write_bytes(b'retained reference\n')
        generated['references/source.txt'] = source.read_bytes()
        self.report = {'schema_version': 1, 'phone_writes': False, 'phase_2_device_gate_passed': False,
                       'reported_revision_is_verified_pcb_identity': False, 'reported_boot_revision': 9,
                       'inventory': audit.record(inventory_path)[0], 'images': images,
                       'references': [dict(audit.record(source)[0], retained_copy='references/source.txt')]}
        self.report['counts'] = audit.counts_for(self.report)
        for relative, content in generated.items():
            target = self.folder / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        self.write_report_and_index()

    def write_report_and_index(self):
        (self.folder / 'report.json').write_text(json.dumps(self.report), encoding='utf-8')
        records = [dict(audit.record(p)[0], path=p.relative_to(self.folder).as_posix())
                   for p in sorted(self.folder.rglob('*')) if p.is_file() and p != self.folder / 'index.json']
        (self.folder / 'index.json').write_text(json.dumps({'schema_version': 1, 'files': records}), encoding='utf-8')

    def verify(self):
        with contextlib.redirect_stdout(io.StringIO()):
            audit.verify_report(self.folder / 'report.json')

    def test_valid_fixture(self):
        self.verify()

    def test_same_size_blob_corruption(self):
        path = next((self.folder / 'dt').glob('*.dtb'))
        content = bytearray(path.read_bytes())
        content[-1] ^= 1
        path.write_bytes(content)
        with self.assertRaisesRegex(RuntimeError, 'audit file changed'):
            self.verify()

    def test_missing_indexed_blob(self):
        next((self.folder / 'dt').glob('*.dtb')).unlink()
        with self.assertRaises(FileNotFoundError):
            self.verify()

    def test_original_image_corruption(self):
        path = Path(self.report['images'][0]['input']['path'])
        content = bytearray(path.read_bytes())
        content[100] ^= 1
        path.write_bytes(content)
        with self.assertRaisesRegex(RuntimeError, 'Phase 1 pin'):
            self.verify()

    def test_directory_escape(self):
        index_path = self.folder / 'index.json'
        index = audit.load(index_path)
        index['files'][0]['path'] = '../outside.txt'
        index_path.write_text(json.dumps(index), encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, 'escapes'):
            self.verify()

    def test_reindexed_false_memory_summary(self):
        self.report['images'][0]['tables'][0]['entries'][0]['summary']['declared_memory_bytes'] = 1
        self.write_report_and_index()
        with self.assertRaisesRegex(RuntimeError, 'summary differs from original'):
            self.verify()

    def test_reindexed_blob_substitution_cannot_change_original(self):
        entry = self.report['images'][0]['tables'][0]['entries'][0]
        (self.folder / entry['extracted_blob']).write_bytes(fixtures.fdt({'model': b'other\0'}))
        self.write_report_and_index()
        with self.assertRaisesRegex(RuntimeError, 'blob differs from original'):
            self.verify()

    def test_device_execution_claim_is_rejected(self):
        self.report['phase_2_device_gate_passed'] = True
        self.write_report_and_index()
        with self.assertRaisesRegex(RuntimeError, 'unsupported device claim'):
            self.verify()

    def test_safe_placement_claim_is_rejected(self):
        self.report['images'][0]['tables'][0]['entries'][0]['summary']['safe_for_loader_placement'] = True
        self.write_report_and_index()
        with self.assertRaisesRegex(RuntimeError, 'summary differs from original'):
            self.verify()

    def test_unindexed_file_is_rejected(self):
        (self.folder / 'extra.txt').write_text('unexpected', encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, 'unindexed'):
            self.verify()

    def test_inconsistent_counts_are_rejected(self):
        self.report['counts']['fdt_blobs'] += 1
        self.write_report_and_index()
        with self.assertRaisesRegex(RuntimeError, 'counts disagree'):
            self.verify()

    def test_duplicate_image_is_rejected(self):
        self.report['images'][1] = copy.deepcopy(self.report['images'][0])
        self.write_report_and_index()
        with self.assertRaisesRegex(RuntimeError, 'duplicate audited image'):
            self.verify()

    def test_revision_must_match_retained_query(self):
        self.report['reported_boot_revision'] = 8
        self.write_report_and_index()
        with self.assertRaisesRegex(RuntimeError, 'revision differs'):
            self.verify()


if __name__ == '__main__':
    unittest.main(verbosity=2)
