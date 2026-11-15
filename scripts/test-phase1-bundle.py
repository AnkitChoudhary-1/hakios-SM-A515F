#!/usr/bin/env python3
"""Exercise bundle integrity failures without altering retained evidence."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('phase1', Path(__file__).with_name('verify-phase1.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BundleIntegrity(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.payload = self.folder / 'serial.log'
        self.payload.write_bytes(b'accepted evidence\n')
        self.record = {'path': 'serial.log', 'size': self.payload.stat().st_size,
                       'sha256': module.digest(self.payload)}
        self.write_index()

    def write_index(self):
        (self.folder / 'index.json').write_text(json.dumps({'schema_version': 1, 'files': [self.record]}))

    def test_valid_bundle(self):
        self.assertEqual(module.verify_bundle(self.folder), 1)

    def test_same_size_corruption(self):
        self.payload.write_bytes(b'corrupt! evidence\n')
        self.assertEqual(self.payload.stat().st_size, self.record['size'])
        with self.assertRaisesRegex(RuntimeError, 'changed'):
            module.verify_bundle(self.folder)

    def test_missing_file(self):
        self.payload.unlink()
        with self.assertRaisesRegex(RuntimeError, 'missing'):
            module.verify_bundle(self.folder)

    def test_path_escape(self):
        self.record['path'] = '../outside.log'
        self.write_index()
        with self.assertRaisesRegex(RuntimeError, 'outside'):
            module.verify_bundle(self.folder)


if __name__ == '__main__':
    unittest.main(verbosity=2)
