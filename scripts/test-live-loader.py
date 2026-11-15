#!/usr/bin/env python3
"""Guard read-only capture status, observation limits and retained-byte replay."""
import copy
import datetime as dt
import gzip
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


live = module('live_capture_guards', 'capture-live-loader.py')
formats = module('live_fdt_fixtures', 'test-boot-formats.py')
NONCE = '0123456789abcdef0123456789abcdef'
FALSE_FLAGS = ('runtime_memory_ownership_verified', 'safe_for_loader_placement',
               'a51_destination_selected', 'phase_2_device_gate_passed',
               'probe_log_retrieval_verified', 'return_to_android_verified',
               'bootloader_loader_acceptance_verified', 'no_flash_a51_launch_verified')


def response(payload, code=0):
    return payload + b'\nHAKIOS_A51_STATUS_' + NONCE.encode() + b'=' + str(code).encode() + b'\n'


class RemoteStatus(unittest.TestCase):
    def test_binary_payload_is_preserved_exactly(self):
        payload = bytes(range(256)) + b'\0\xff\r\n' + response(b'embedded footer') + b'continued\n'
        self.assertEqual(live.unwrap_status(response(payload), NONCE), (payload, 0))

    def test_remote_failure_with_successful_adb_transport(self):
        payload = b'cat: /missing: No such file or directory\n'
        self.assertEqual(live.decode_response(response(payload, 1), NONCE, 'ok', 0, 4096),
                         (payload, 1, 'command_failed'))

    def test_missing_footer_cannot_be_success(self):
        self.assertEqual(live.decode_response(b'uid=0(root)\n', NONCE, 'ok', 0, 4096),
                         (b'uid=0(root)\n', None, 'missing_remote_status'))

    def test_malformed_or_wrong_nonce_footer(self):
        for tail in (b'-1\n', b'256\n', b'000\n', b'0', b'0\nwarning\n', b'9999\n'):
            with self.subTest(tail=tail), self.assertRaises(ValueError):
                live.unwrap_status(b'\nHAKIOS_A51_STATUS_' + NONCE.encode() + b'=' + tail, NONCE)
        with self.assertRaises(ValueError):
            live.unwrap_status(response(b'data'), 'a' * 32)

    def test_invalid_nonce_cannot_be_shell_text(self):
        for nonce in ('a' * 31, 'A' * 32, '0' * 31 + ';', 0, None):
            with self.subTest(nonce=nonce), self.assertRaises(ValueError):
                live.remote_script('id', nonce)

    def test_transport_failure_timeout_and_overflow_are_preserved(self):
        for status, code in (('command_failed', 1), ('timeout', -9), ('output_limit', 1)):
            with self.subTest(status=status):
                self.assertEqual(live.decode_response(response(b'data'), NONCE, status, code, 4096),
                                 (b'data', 0, status))
        self.assertEqual(live.decode_response(b'', NONCE, 'launch_error', None, 4096),
                         (b'', None, 'launch_error'))

    def test_payload_limit_is_applied_after_footer_removal(self):
        self.assertEqual(live.decode_response(response(b'abcdef'), NONCE, 'ok', 0, 4),
                         (b'abcd', 0, 'output_limit'))

    def test_invalid_transport_types_and_status(self):
        for status, code in (('ok', False), ('ok', None), ('ok', 1), ('command_failed', 0),
                             ('launch_error', 0), ('invented', 0)):
            with self.subTest(status=status, code=code), self.assertRaises(ValueError):
                live.decode_response(b'', NONCE, status, code, 4096)

    def test_bounded_process_keeps_binary_bytes(self):
        metadata, stdout, stderr = live.run_bounded(
            [sys.executable, '-c', 'import sys; sys.stdout.buffer.write(bytes(range(256))); sys.stderr.buffer.write(b"diagnostic")'], 512)
        self.assertEqual((metadata['status'], metadata['exit_code']), ('ok', 0))
        self.assertEqual(stdout, bytes(range(256)))
        self.assertEqual(stderr, b'diagnostic')

    def test_bounded_process_caps_both_streams(self):
        for stream, limit in (('stdout', 1024), ('stderr', 65536)):
            with self.subTest(stream=stream):
                metadata, stdout, stderr = live.run_bounded(
                    [sys.executable, '-c', 'import sys; sys.' + stream + '.buffer.write(b"x" * 200000)'], 1024)
                self.assertEqual(metadata['status'], 'output_limit')
                self.assertLessEqual(len(stdout), 1024)
                self.assertLessEqual(len(stderr), 65536)
                self.assertEqual(len(stdout if stream == 'stdout' else stderr), limit)

    def test_bounded_process_times_out(self):
        metadata, _, _ = live.run_bounded([sys.executable, '-c', 'import time; time.sleep(10)'], 1024, timeout=0.2)
        self.assertEqual(metadata['status'], 'timeout')


class ResourceParsers(unittest.TestCase):
    def test_iomem_inclusive_high_and_redacted_ranges(self):
        result = live.parse_iomem(b'880000000-8ffffffff : System RAM\n  890000000-890ffffff : Kernel data\n00000000-00000000 : redacted\n')
        self.assertEqual((result[0]['start'], result[0]['end_exclusive']), (0x880000000, 0x900000000))
        self.assertEqual(result[1]['indent'], 2)
        self.assertTrue(result[2]['zero_address_record'])
        self.assertEqual(result[2]['end_exclusive'], 1)

    def test_iomem_top_u64_boundary(self):
        self.assertEqual(live.parse_iomem(b'fffffffffffffffe-ffffffffffffffff : last\n')[0]['end_exclusive'], 2 ** 64)

    def test_iomem_malformed_reversed_and_overflow(self):
        for data in (b'no map\n', b'20-10 : reversed\n', b'0-10000000000000000 : overflow\n', b'10-20: missing spaces\n', b'\xff'):
            with self.subTest(data=data), self.assertRaises(ValueError):
                live.parse_iomem(data)

    def test_configuration_disabled_and_absent_symbols(self):
        value = live.config_symbols(gzip.compress(b'CONFIG_KSU=y\n# CONFIG_KEXEC is not set\n'))
        self.assertEqual(value['CONFIG_KSU'], 'y')
        self.assertEqual(value['CONFIG_KEXEC'], 'n')
        self.assertEqual(value['CONFIG_ARCH_KEEP_MEMBLOCK'], 'absent_or_unknown')

    def test_configuration_duplicate_or_invalid_encoding(self):
        for text in (b'CONFIG_KSU=y\n# CONFIG_KSU is not set\n', b'CONFIG_UNKNOWN=y\nCONFIG_UNKNOWN=n\n', b'\xff'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                live.config_symbols(gzip.compress(text))

    def test_configuration_decompression_bound(self):
        with self.assertRaisesRegex(ValueError, 'decompressed configuration'):
            live.config_symbols(gzip.compress(b'x' * (2 * live.MIB + 1)))

    def test_configuration_truncated_gzip(self):
        with self.assertRaises((EOFError, OSError)):
            live.config_symbols(gzip.compress(b'CONFIG_KSU=y\n')[:-5])


class CaptureReplay(unittest.TestCase):
    def setUp(self):
        self.actual_project = live.PROJECT
        self.allowed = (self.actual_project / 'evidence/test-fixtures').resolve()
        self.allowed.mkdir(parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix='live-loader-', dir=self.allowed))
        self.addCleanup(self.cleanup)
        self.patch = mock.patch.object(live, 'PROJECT', self.root / 'project')
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.project = live.PROJECT
        (self.project / 'scripts').mkdir(parents=True)
        self.folder = self.project / 'capture'
        for name in ('queries', 'tools', 'inputs'):
            (self.folder / name).mkdir(parents=True, exist_ok=True)
        for script in ('capture-live-loader.py', 'boot_formats.py'):
            value = (self.actual_project / 'scripts' / script).read_bytes()
            (self.project / 'scripts' / script).write_bytes(value)
            (self.folder / 'tools' / script).write_bytes(value)
        self.fdt = formats.fdt({
            '#address-cells': formats.cell(2), '#size-cells': formats.cell(1),
            'model': b'Synthetic A51 observation\0', 'compatible': b'samsung,fixture\0',
            'memory@80000000': {'device_type': b'memory\0', 'reg': formats.cell(0, 0x80000000, 0x80000000)},
            'memory@880000000': {'device_type': b'memory\0', 'reg': formats.cell(8, 0x80000000, 0x80000000)},
            'reserved-memory': {'#address-cells': formats.cell(2), '#size-cells': formats.cell(1), 'ranges': b'',
                                'ion_video_stream': {'size': formats.cell(0x200000)},
                                'modem': {'reg': formats.cell(0, 0xED000000, 0x08A00000)}},
            'chosen': {'bootargs': b'fixture_private_boot_argument\0', 'rng-seed': b'fixture_seed_bytes',
                       'stdout-path': b'/serial@1000\0', 'linux,initrd-start': formats.cell(0x89000000),
                       'linux,initrd-end': formats.cell(0x89100000)}})
        self.report = {'schema_version': 2, 'scope': 'live_android_read_only_observations',
                       'phone_writes': False, 'serial': 'FIXTURE', 'adb_path': '/fixture/adb',
                       'adb_executable': {'size': 1, 'sha256': live.sha256(b'a')},
                       'remote_status_nonce': NONCE, 'remote_stdout_may_include_stderr': True,
                       'created': self.time(0), 'finished': self.time(100), 'queries': [], 'base_fdts': [], 'local_inputs': {},
                       'transport_check': {'started': self.time(-2), 'finished': self.time(-1), 'status': 'ok',
                           'exit_code': 0, 'argv': ['/fixture/adb', '-s', 'FIXTURE', 'get-state'], 'stdout': 'device\n', 'stderr': ''}}
        trace_dir = self.project / 'trace'
        (trace_dir / 'fdts').mkdir(parents=True)
        trace = {'base_fdts': []}
        for image in ('original-boot', 'installed-boot', 'original-recovery'):
            name = 'fdts/' + image + '.dtb'
            (trace_dir / name).write_bytes(self.fdt)
            item = {'original': 'fixture/' + image, 'copy': name, 'size': len(self.fdt), 'sha256': live.sha256(self.fdt)}
            trace['base_fdts'].append({'image': image, 'input': item})
            copy_name = 'inputs/' + image + '.dtb'
            (self.folder / copy_name).write_bytes(self.fdt)
            self.report['base_fdts'].append(dict(item, image=image, source_copy=name, copy=copy_name))
        live.write_json(trace_dir / 'report.json', trace)
        self.report['source_trace'] = {'report': 'trace/report.json', 'sha256': live.sha256((trace_dir / 'report.json').read_bytes())}
        for key, relative in live.LOCAL_INPUTS.items():
            path = self.project.parent / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(key.encode())
            self.report['local_inputs'][key] = dict(live.digest_file(path), path=relative, exists=True)
        values = {'root_begin': b'uid=0(root) gid=0(root) context=u:r:su:s0\n',
                  'root_end': b'uid=0(root) gid=0(root) context=u:r:su:s0\n',
                  'boot_id_begin': b'12345678-1234-1234-1234-123456789abc\n',
                  'boot_id_end': b'12345678-1234-1234-1234-123456789abc\n',
                  'fdt_begin': self.fdt, 'fdt_end': self.fdt,
                  'dt_model': b'Synthetic A51 observation\0', 'dt_compatible': b'samsung,fixture\0',
                  'config_gz': gzip.compress(b'CONFIG_KSU=y\n# CONFIG_KEXEC is not set\n# CONFIG_DEBUG_FS is not set\n'),
                  'iomem': b'80000000-9fffffff : System RAM\n  81000000-81ffffff : Kernel code\n880000000-8ffffffff : System RAM\n',
                  'meminfo': b'MemTotal: 123456 kB\nMemAvailable: 1234 kB\nCmaTotal: 1024 kB\nCmaFree: 0 kB\n',
                  'pstore_listing': b'console-ramoops-0\n', 'last_kmsg_listing': b'-r--r----- /proc/last_kmsg\n',
                  'pstore_console': b'fixture prior Android kernel log\n', 'last_kmsg_platform_log': b'Memory: fixture\n'}
        for partition, key in (('boot', 'installed_boot'), ('dtbo', 'original_dtbo'), ('recovery', 'original_recovery')):
            item = self.report['local_inputs'][key]
            values[partition + '_size'] = str(item['size']).encode() + b'\n'
            values[partition + '_sha256'] = (item['sha256'] + '  /dev/block/by-name/' + partition + '\n').encode()
        failures = {'dt_video_reg', 'dt_crypto_reg', 'dt_wlbt_reg', 'debugfs_listing', 'kexec_loaded'}
        for number, (name, command, _) in enumerate(live.QUERIES):
            payload, code = (b'cat: fixture interface unavailable\n', 1) if name in failures else (values.get(name, b''), 0)
            item = {'id': name, 'command': command,
                    'argv': ['/fixture/adb', '-s', 'FIXTURE', 'exec-out', 'su -c ' + live.shlex.quote(live.remote_script(command, NONCE))],
                    'started': self.time(number * 2 + 1), 'finished': self.time(number * 2 + 2),
                    'transport_status': 'ok', 'transport_exit_code': 0, 'exit_code': code, 'status': 'ok' if code == 0 else 'command_failed'}
            for stream, data in (('stdout', payload), ('stderr', b''), ('response', response(payload, code))):
                name = 'queries/' + str(number).zfill(2) + '-' + item['id'] + '.' + stream
                (self.folder / name).write_bytes(data)
                item.update({stream: name, stream + '_size': len(data), stream + '_sha256': live.sha256(data)})
            self.report['queries'].append(item)
        self.save(reconstruct=True)

    def cleanup(self):
        if not self.root.resolve().is_relative_to(self.allowed) or self.root.resolve() == self.allowed:
            raise RuntimeError('fixture cleanup escaped intended workspace')
        shutil.rmtree(self.root)

    @staticmethod
    def time(seconds):
        value = dt.datetime(2026, 11, 11, 7, tzinfo=dt.timezone.utc) + dt.timedelta(seconds=seconds)
        return {'utc': value.isoformat(), 'ist': value.astimezone(live.IST).isoformat()}

    def save(self, reconstruct=False):
        if reconstruct:
            self.report['summary'] = live.summarize(self.folder, self.report)
        live.write_json(self.folder / 'report.json', self.report)
        self.reindex()

    def reindex(self):
        live.write_json(self.folder / 'index.json', live.make_index(self.folder))

    def query(self, name):
        return next(item for item in self.report['queries'] if item['id'] == name)

    def replace_payload(self, name, data, code=0):
        item = self.query(name)
        item.update(exit_code=code, status='ok' if code == 0 else 'command_failed')
        for stream, value in (('stdout', data), ('response', response(data, code))):
            (self.folder / item[stream]).write_bytes(value)
            item.update({stream + '_size': len(value), stream + '_sha256': live.sha256(value)})

    def test_complete_capture_reconstructs_without_owned_memory(self):
        report, count = live.verify(self.folder)
        self.assertEqual(count, 6 + 3 * len(live.QUERIES))
        summary = report['summary']
        self.assertTrue(summary['adb_root_verified'] and summary['single_boot_observation_verified'] and summary['live_fdt_export_verified'])
        self.assertEqual(len(summary['query_failures']), 5)
        self.assertTrue(all(summary[key] is False for key in FALSE_FLAGS))
        self.assertTrue(all(item['matches_retained_size_and_sha256'] for item in summary['partitions'].values()))
        self.assertIn('/reserved-memory/ion_video_stream', summary['live_fdt']['dynamic_reservations'])
        self.assertNotIn('gaps_after_known_static_reservations', summary['live_fdt'])
        self.assertNotIn('fixture_seed_bytes', json.dumps(summary))
        self.assertNotIn('fixture_private_boot_argument', json.dumps(summary))

    def test_changed_boot_id_prevents_verified_export(self):
        self.replace_payload('boot_id_end', b'aaaaaaaa-1234-1234-1234-123456789abc\n')
        self.save(reconstruct=True)
        summary = live.verify(self.folder)[0]['summary']
        self.assertFalse(summary['single_boot_observation_verified'] or summary['live_fdt_export_verified'])

    def test_changed_fdt_prevents_verified_export(self):
        self.replace_payload('fdt_end', formats.fdt({'model': b'changed\0'}))
        self.save(reconstruct=True)
        self.assertFalse(live.verify(self.folder)[0]['summary']['live_fdt_export_verified'])

    def test_nonroot_end_prevents_verified_export(self):
        self.replace_payload('root_end', b'uid=2000(shell)\n')
        self.save(reconstruct=True)
        summary = live.verify(self.folder)[0]['summary']
        self.assertFalse(summary['adb_root_verified'] or summary['live_fdt_export_verified'])

    def test_independent_sysfs_mismatch_prevents_verified_export(self):
        self.replace_payload('dt_model', b'changed model\0')
        self.save(reconstruct=True)
        self.assertFalse(live.verify(self.folder)[0]['summary']['live_fdt_export_verified'])

    def test_malformed_or_trailing_fdt_is_rejected(self):
        for data in (self.fdt[:-1], self.fdt + b'unaccounted'):
            with self.subTest(size=len(data)):
                self.replace_payload('fdt_begin', data)
                with self.assertRaises((ValueError, live.FormatError)):
                    live.summarize(self.folder, self.report)

    def test_partition_mismatch_is_observed_without_gate_promotion(self):
        self.replace_payload('boot_sha256', b'a' * 64 + b'  /dev/block/by-name/boot\n')
        self.save(reconstruct=True)
        summary = live.verify(self.folder)[0]['summary']
        self.assertFalse(summary['partitions']['boot']['matches_retained_size_and_sha256'])
        self.assertTrue(all(summary[key] is False for key in FALSE_FLAGS))

    def test_query_allowlist_and_explicit_serial_are_enforced(self):
        for field, value in (('command', 'reboot'), ('id', 'another_query'), ('argv', ['/fixture/adb', 'shell', 'id'])):
            previous = copy.deepcopy(self.query('root_begin'))
            self.query('root_begin')[field] = value
            self.save()
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'fixed read-only'):
                live.verify(self.folder)
            self.report['queries'][0] = previous

    def test_fabricated_success_cannot_override_failed_remote_bytes(self):
        item = self.query('dt_video_reg')
        item.update(exit_code=0, status='ok')
        self.save()
        with self.assertRaisesRegex(ValueError, 'remote response/status'):
            live.verify(self.folder)

    def test_fabricated_payload_cannot_override_raw_response(self):
        item = self.query('root_begin')
        (self.folder / item['stdout']).write_bytes(b'uid=2000(shell)\n')
        item.update(stdout_size=16, stdout_sha256=live.sha256(b'uid=2000(shell)\n'))
        self.save()
        with self.assertRaises(ValueError):
            live.verify(self.folder)

    def test_reindexed_fabricated_summary_is_rejected(self):
        self.report['summary']['runtime_memory_ownership_verified'] = True
        self.report['summary']['safe_for_loader_placement'] = True
        self.save()
        with self.assertRaisesRegex(ValueError, 'stored observations'):
            live.verify(self.folder)

    def test_strict_boolean_integer_types(self):
        updates = (lambda r: r.update(schema_version=True), lambda r: r.update(phone_writes=0),
                   lambda r: r['queries'][0].update(exit_code=False), lambda r: r['queries'][0].update(transport_exit_code=False),
                   lambda r: r['queries'][0].update(stdout_size=True), lambda r: r['local_inputs']['installed_boot'].update(exists=1),
                   lambda r: r['adb_executable'].update(size=True))
        original = copy.deepcopy(self.report)
        for update in updates:
            self.report = copy.deepcopy(original)
            update(self.report)
            self.save()
            with self.subTest(update=update), self.assertRaises(ValueError):
                live.verify(self.folder)

    def test_query_timestamp_order_and_offsets_are_enforced(self):
        self.query('root_begin')['finished'] = self.time(-3)
        self.save()
        with self.assertRaisesRegex(ValueError, 'timestamps'):
            live.verify(self.folder)
        with self.assertRaisesRegex(ValueError, 'UTC/IST'):
            live.time_pair({'utc': self.time(0)['utc'], 'ist': self.time(0)['utc']})

    def test_indexed_byte_tampering_is_rejected(self):
        path = self.folder / self.query('iomem')['stdout']
        path.write_bytes(path.read_bytes().replace(b'RAM', b'BAD'))
        with self.assertRaisesRegex(ValueError, 'indexed file changed'):
            live.verify(self.folder)

    def test_local_input_and_source_trace_drift_are_rejected(self):
        path = self.project.parent / live.LOCAL_INPUTS['installed_boot']
        path.write_bytes(b'different image')
        with self.assertRaisesRegex(ValueError, 'local input bytes changed'):
            live.verify(self.folder)
        path.write_bytes(b'installed_boot')
        (self.project / 'trace/report.json').write_bytes(b'{}\n')
        with self.assertRaisesRegex(ValueError, 'source-trace report changed'):
            live.verify(self.folder)

    def test_reindexed_base_provenance_substitution_is_rejected(self):
        item = self.report['base_fdts'][0]
        value = formats.fdt({'model': b'replaced\0'})
        (self.folder / item['copy']).write_bytes(value)
        item.update(size=len(value), sha256=live.sha256(value))
        self.save(reconstruct=True)
        with self.assertRaisesRegex(ValueError, 'base FDT provenance'):
            live.verify(self.folder)

    def test_matching_tool_revision_is_required(self):
        path = self.folder / 'tools/capture-live-loader.py'
        path.write_bytes(path.read_bytes() + b'\n# altered\n')
        self.reindex()
        with self.assertRaisesRegex(ValueError, 'matching retained script'):
            live.verify(self.folder)

    def test_missing_extra_and_reindexed_extra_files_are_rejected(self):
        path = self.folder / 'extra.txt'
        path.write_bytes(b'extra')
        with self.assertRaisesRegex(ValueError, 'missing, extra'):
            live.verify(self.folder)
        self.reindex()
        with self.assertRaisesRegex(ValueError, 'unexpected retained file set'):
            live.verify(self.folder)
        path.unlink()
        self.reindex()
        (self.folder / self.query('iomem')['stdout']).unlink()
        with self.assertRaises(OSError):
            live.verify(self.folder)

    def test_nested_index_file_cannot_escape_indexing(self):
        (self.folder / 'queries/index.json').write_bytes(b'{}')
        self.reindex()
        with self.assertRaisesRegex(ValueError, 'unexpected retained file set'):
            live.verify(self.folder)

    def test_path_traversal_absolute_and_noncanonical_names(self):
        for name in ('../outside', '/outside', 'C:/outside', 'queries\\file', 'queries/../file',
                     './report.json', 'queries//file', 'queries/./file', '', 'queries/\0'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                live.inside(self.folder, name)

    def test_index_types_counts_sizes_and_total_bounds(self):
        original = live.json_read(self.folder / 'index.json')
        cases = [dict(original, schema_version=True), {'schema_version': 1, 'files': {str(n): {'size': 0, 'sha256': '0' * 64} for n in range(257)}},
                 {'schema_version': 1, 'files': {'report.json': {'size': True, 'sha256': '0' * 64}}},
                 {'schema_version': 1, 'files': {'report.json': {'size': live.FILE_LIMIT + 1, 'sha256': '0' * 64}}},
                 {'schema_version': 1, 'files': {str(n): {'size': live.FILE_LIMIT, 'sha256': '0' * 64} for n in range(9)}}]
        for index in cases:
            live.write_json(self.folder / 'index.json', index)
            with self.subTest(index_count=len(index['files'])), self.assertRaises(ValueError):
                live.verify(self.folder)

    def test_json_duplicate_nonfinite_and_float_overflow(self):
        for value in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1e400}', b'{"x":-1e400}'):
            (self.root / 'bad.json').write_bytes(value)
            with self.subTest(value=value), self.assertRaises(ValueError):
                live.json_read(self.root / 'bad.json')

    def test_json_and_file_reads_are_bounded(self):
        path = self.root / 'oversize'
        path.write_bytes(b'x' * (live.JSON_LIMIT + 1))
        with self.assertRaisesRegex(ValueError, 'file exceeds bound'):
            live.json_read(path)
        with self.assertRaisesRegex(ValueError, 'file exceeds bound'):
            live.bounded_read(path, 16)


if __name__ == '__main__':
    unittest.main(verbosity=2)
