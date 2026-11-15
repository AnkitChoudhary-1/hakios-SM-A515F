#!/usr/bin/env python3
"""Guard against false acceptance using a real QEMU transcript and fault cases."""
import importlib.util
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('qemu_open', PROJECT/'scripts/qemu-open.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
SERIAL = (PROJECT/'evidence/qemu/20261110T163402791610Z/serial.log').read_text(errors='replace')
HELLO = 'Hello from user space on Darwin!'
VERSION = 'kernel.ver=2.3.4-hakios-darwin22.5-g63fc2b46'


class Acceptance(unittest.TestCase):
    def passes(self, serial=SERIAL, code=0):
        return module.validate_serial(serial, code)[3]

    def test_real_run(self):
        self.assertTrue(self.passes())

    def test_complete_markers_at_bounded_timeout(self):
        self.assertTrue(self.passes(code=124))

    def test_loader_version_cannot_replace_user_sysctl(self):
        prefix, program = SERIAL.split(HELLO, 1)
        self.assertIn(VERSION, prefix)
        self.assertFalse(self.passes(prefix+HELLO+program.replace(VERSION, 'kernel.ver=(sysctl unavailable)')))

    def test_crash_before_hello_cannot_be_hidden_by_later_output(self):
        self.assertFalse(self.passes('panic(cpu 0): data abort\n'+SERIAL))

    def test_wrong_user_identity(self):
        self.assertFalse(self.passes(SERIAL.replace('I am process 1, uid 0,', 'I am process 2, uid 501,')))

    def test_nonzero_process_exit(self):
        self.assertFalse(self.passes(SERIAL.replace('(signal 0, exit 0)', '(signal 0, exit 1)')))

    def test_missing_hello(self):
        self.assertFalse(self.passes(SERIAL.replace(HELLO, 'no user program')))

    def test_other_panic(self):
        self.assertFalse(self.passes(SERIAL+'\npanic(cpu 0): unexpected memory fault\n'))

    def test_abnormal_runner_exit(self):
        self.assertFalse(self.passes(code=139))


if __name__ == '__main__':
    unittest.main(verbosity=2)
