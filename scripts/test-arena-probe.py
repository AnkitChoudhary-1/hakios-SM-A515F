 #!/usr/bin/env python3
"""Reject altered budgets and forged/stale allocation lifetimes offline."""
import copy
import json
import unittest
import arena_probe as arena

NORMAL = '0123456789abcdef'
FAILURE = 'fedcba9876543210'


def sample():
    lines = []
    for run, reason in [(NORMAL, 'unload'), (FAILURE, 'requested_init_failure')]:
        lines.extend(['HAKIOS_ARENA run=' + run + ' stage=acquire phys=0x90000000 bytes=65536 order=4',
                      'HAKIOS_ARENA run=' + run + ' stage=selfcheck regions=6 zero=pass pattern=pass'])
        if reason == 'unload':
            lines.append('HAKIOS_ARENA run=' + run + ' stage=loaded')
        lines.append('HAKIOS_ARENA run=' + run + ' stage=release phys=0x90000000 bytes=65536 order=4 reason=' + reason + ' integrity=pass cleared=pass')
    return '\n'.join(lines)


class Guards(unittest.TestCase):
    def test_fixed_budget_and_header(self):
        value = arena.validate_budget(arena.read_json(arena.PROJECT / 'manifests/arena-probe-budget.json'))
        self.assertEqual(sum(r['bytes'] for r in value['regions']), 65536)
        self.assertEqual((arena.PROJECT / 'diagnostics/arena-probe/arena_budget.h').read_text(encoding='utf-8'), arena.header(value))

    def test_budget_mutations(self):
        value = arena.budget()
        mutations = [('arena_bytes', 131072), ('order', True), ('schema_version', True),
                     ('payload_budget_final', True), ('a51_destination_selected', True),
                     ('phase_2_device_gate_passed', True), ('scope', 'a51_payload_owned')]
        for key, changed in mutations:
            with self.subTest(key=key):
                bad = copy.deepcopy(value)
                bad[key] = changed
                with self.assertRaises(ValueError):
                    arena.validate_budget(bad)
        for role in ['offset', 'bytes', 'pattern']:
            with self.subTest(region_field=role):
                bad = copy.deepcopy(value)
                bad['regions'][1][role] += 4096
                with self.assertRaises(ValueError):
                    arena.validate_budget(bad)

    def test_lifetimes_closed(self):
        result = arena.lifetimes(sample(), NORMAL, FAILURE)
        self.assertEqual(len(result), 2)
        self.assertTrue(all(r['state'] == 'released' and not r['active_owned_interval']
                            and not r['safe_for_loader_placement'] for r in result))

    def test_lifetime_mutations(self):
        changes = [('phys=0x90000000', 'phys=0x90001000'), ('bytes=65536', 'bytes=4096'),
                   ('order=4', 'order=3'), ('integrity=pass', 'integrity=fail'),
                   ('cleared=pass', 'cleared=fail'), ('regions=6', 'regions=5'),
                   ('reason=unload', 'reason=still_owned')]
        for old, new in changes:
            with self.subTest(field=old):
                with self.assertRaises(ValueError):
                    arena.lifetimes(sample().replace(old, new, 1), NORMAL, FAILURE)
        with self.assertRaises(ValueError):
            arena.lifetimes('\n'.join(sample().splitlines()[:-1]), NORMAL, FAILURE)
        with self.assertRaises(ValueError):
            arena.lifetimes(sample(), NORMAL, NORMAL)


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Guards)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(json.dumps({'passed': result.wasSuccessful(), 'test_methods': result.testsRun,
                      'budget_mutations': 10, 'lifetime_rejections': 9}))
    raise SystemExit(0 if result.wasSuccessful() else 1)
