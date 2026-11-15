#!/usr/bin/env python3
"""Record a host layout evaluation or expected A51 rejections; never contact a device."""
import argparse
import copy
import datetime as dt
import json
from pathlib import Path
import struct

import payload_layout as layout

PROJECT = layout.PROJECT
CURRENT = PROJECT / 'manifests/payload-layout-current.json'


def encode(value):
    return (json.dumps(value, indent=2) + '\n').encode('utf-8')


def contained(root, relative):
    path = (root / relative).resolve()
    layout.require(path.is_relative_to(root.resolve()) and path != root.resolve(),
                   'evidence_path', str(relative), 'Evidence path escapes its directory')
    return path


def file_record(path, root):
    rec = layout.pin(path, 'file')
    return {key: rec[key] for key in ('size', 'sha256')} | {'path': path.relative_to(root).as_posix()}


def project_pin(path, identifier):
    rec = layout.pin(path, identifier)
    rec['path'] = path.resolve().relative_to(PROJECT.resolve()).as_posix()
    return rec


def same_json(left, right):
    # Python dictionary equality equates True with 1 and False with 0.
    # Retained evidence must preserve JSON types as well as values.
    return json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)


def read_evidence(path):
    # Every generated evidence file is bounded by the manifest/JSON limit.
    # Check before allocation, then bound the read in case the file grows.
    layout.require(path.stat().st_size <= layout.MAX_JSON_BYTES, 'evidence_bounds', str(path),
                   'Evidence file exceeds the 2 MiB limit')
    with path.open('rb') as stream:
        raw = stream.read(layout.MAX_JSON_BYTES + 1)
    layout.require(len(raw) <= layout.MAX_JSON_BYTES, 'evidence_bounds', str(path),
                   'Evidence file exceeds the 2 MiB limit')
    return raw


def requirement(code, location, message_contains=''):
    return {'code': code, 'location': location, 'message_contains': message_contains}


def component(identifier, role, image=None, start=None, size=None, prov=None, kind=None):
    return {'id': identifier, 'role': role, 'start': start, 'execution_bytes': size,
            'alignment': 4096, 'reserve_alignment': 4096, 'prefix_bytes': 0, 'suffix_bytes': 0,
            'format': kind or ('zeroed' if role in layout.MEMORY_ROLES else 'raw'),
            'image': image, 'extent_provenance': prov or layout.unknown('Implementation/extent unavailable')}


def base_manifest(target, evidence, binding=None):
    return {'format': 'hakios.payload-layout', 'schema_version': 1, 'target': target,
            'purpose': 'Host diagnostic only; no executable A51 layout or destination is selected',
            'evidence': evidence, 'retained_audit': binding,
            'memory': {'allowed': [], 'excluded': [], 'dynamic': []},
            'prerequisites': {key: layout.unknown('No live/probe evidence for ' + key) for key in layout.PREREQUISITES},
            'entry': {'component': 'loader', 'offset': 0, 'alignment': 4, 'abi': 'unavailable'},
            'components': [component(role, role, kind='fdt' if role == 'fdt' else None) for role in layout.ROLES]}


def a51_cases(report_pin, inputs):
    binding = {'evidence': report_pin['id'], 'image': 'original-boot', 'section': 'dtb', 'entry_index': 0}
    facts, image, entry = inputs.retained(binding, report_pin)
    boot_pin = {key: image['input'][key] for key in ('path', 'size', 'sha256')} | {'id': 'retained-boot'}
    base = base_manifest('a51-retained-host', [report_pin, boot_pin], binding)
    section = image['boot_header']['sections']['kernel']
    extent = layout.observed('retained_bytes', [report_pin['id'], boot_pin['id']],
                             'Retained Android Linux Image diagnostic, not an XNU or loader implementation')
    kernel = next(rec for rec in base['components'] if rec['role'] == 'kernel')
    kernel.update(format='arm64-image', execution_bytes=image['arm64_image']['image_size'],
                  image={'evidence': boot_pin['id'], 'offset': section['offset'], 'size': section['size'],
                         'sha256': section['sha256']}, extent_provenance=extent)
    fdt = next(rec for rec in base['components'] if rec['role'] == 'fdt')
    fdt.update(execution_bytes=entry['size'], image={'evidence': boot_pin['id'],
               'offset': entry['absolute_file_offset'], 'size': entry['size'], 'sha256': entry['sha256']},
               extent_provenance=layout.observed('retained_bytes', [report_pin['id'], boot_pin['id']],
                                                'Retained base FDT bytes; live merge/fixups and destination unknown'))
    cases = [('unplaced-retained-inputs', base, False,
              [requirement('component_unplaced', 'components.loader'),
               requirement('available_memory_unresolved', 'memory.allowed')]
              + [requirement('prerequisite_unresolved', 'prerequisites.' + key) for key in layout.PREREQUISITES]
              + [requirement('dynamic_ownership_unresolved', 'memory.dynamic.' + rec['id']) for rec in facts['dynamic']])]

    def probe(name, address, requirements, allowed=None):
        candidate = copy.deepcopy(base)
        candidate['purpose'] = 'Expected rejection: ' + name + '; diagnostic address only, no A51 placement selected'
        next(rec for rec in candidate['components'] if rec['role'] == 'kernel')['start'] = address
        if allowed is not None:
            candidate['memory']['allowed'] = [allowed]
        cases.append((name, candidate, False, requirements))

    probe('qemu-modem-address', 0xF0000000,
          [requirement('reserved_overlap', 'components.kernel', '/modem_if')])
    for i, span in enumerate(facts['excluded']):
        probe('fixed-reservation-' + str(i).zfill(2), span['start'],
              [requirement('reserved_overlap', 'components.kernel', span['owner'])])
    for i, bank in enumerate(facts['declared']):
        if bank['start'] <= 0xffffffff:
            continue
        allowed = {key: bank[key] for key in ('id', 'start', 'size', 'provenance')}
        probe('high-bank-declaration-' + str(i), bank['start'],
              [requirement('allowed_interval_unverified', 'memory.allowed.' + bank['id']),
               requirement('component_outside_allowed', 'components.kernel')], allowed)
    summary = entry['summary']
    gaps = summary['gaps_after_known_static_reservations']
    if gaps:
        gap = gaps[0]
        allowed = {'id': 'static-gap', 'start': gap['start'], 'size': gap['size'],
                   'provenance': layout.observed('source_declaration', [report_pin['id']],
                                                'Arithmetic subtraction of static reservations; ownership unknown')}
        probe('static-gap-is-not-owned', gap['start'],
              [requirement('allowed_interval_unverified', 'memory.allowed.static-gap')], allowed)
    labeled = copy.deepcopy(base)
    runtime_label = layout.observed('runtime_observation', [report_pin['id']],
                                    'Deliberately unsupported caller label; this report contains retained/source bytes only')
    labeled['prerequisites'] = {key: runtime_label for key in layout.PREREQUISITES}
    bank = facts['declared'][0]
    labeled['memory']['allowed'] = [{'id': 'caller-runtime-label', 'start': bank['start'], 'size': bank['size'],
                                    'provenance': runtime_label}]
    labeled['purpose'] = 'Expected rejection of caller runtime labels applied to retained evidence'
    cases.append(('runtime-labels-cannot-promote-retained-data', labeled, False,
                  [requirement('a51_runtime_evidence_unavailable', 'target'),
                   requirement('allowed_interval_unverified', 'memory.allowed.caller-runtime-label')]))
    return cases


def synthetic_files():
    # A valid empty FDT, and deliberately nonexecutable text for integrity/layout fixtures.
    structure = struct.pack('>4I', 1, 0, 2, 9)
    tree = struct.pack('>10I', 0xd00dfeed, 72, 56, 72, 40, 17, 16, 0, 0, 16) + b'\0' * 16 + structure
    return {'inputs/synthetic-input.txt': b'Synthetic host layout fixture. These bytes are not executable firmware.\n',
            'inputs/synthetic.dtb': tree}


def synthetic_manifest(pins):
    base = base_manifest('synthetic-host', pins)
    base['purpose'] = 'Synthetic host arithmetic/integrity example; input text is not executable machine code'
    prov = layout.observed('synthetic', [rec['id'] for rec in pins], 'Synthetic assumptions for host tests only')
    base['prerequisites'] = {key: prov for key in layout.PREREQUISITES}
    base['entry']['abi'] = 'synthetic fixture; no actual CPU entry ABI'
    start = 0x880000000
    base['memory']['allowed'] = [{'id': 'synthetic-owned', 'start': start, 'size': 0x200000, 'provenance': prov}]
    text = next(rec for rec in pins if rec['id'] == 'synthetic-input')
    tree = next(rec for rec in pins if rec['id'] == 'synthetic-fdt')
    for i, rec in enumerate(base['components']):
        role = rec['role']
        source = tree if role == 'fdt' else text
        image = None if role in layout.MEMORY_ROLES else {'evidence': source['id'], 'offset': 0,
                                                        'size': source['size'], 'sha256': source['sha256']}
        rec.update(start=start + 0x4000 * (i + 1), execution_bytes=8192 if role in ('kernel', 'payload') else 4096,
                   extent_provenance=prov, image=image)
        if role == 'payload':
            rec['format'] = 'expanded'
    return base


def meets_expectation(case):
    assessment = case['assessment']
    expected = case['expected_host_validation_passed']
    if expected is not None and assessment['host_validation_passed'] is not expected:
        return False
    return all(any(issue['code'] == wanted['code'] and issue['location'] == wanted['location']
                   and wanted['message_contains'] in issue['message'] for issue in assessment['issues'])
               for wanted in case['required_issues'])


def counts(cases):
    first = cases[0]['assessment']['memory']
    accepted = sum(case['assessment']['host_validation_passed'] for case in cases)
    return {'cases': len(cases), 'accepted': accepted, 'rejected': len(cases) - accepted,
            'declared_banks': len(first['declared']), 'fixed_exclusions': len(first['excluded']),
            'dynamic_reservations': len(first['dynamic'])}


def capture(folder, operation, cases, inputs, generated=(), report_pin=None, source_pin=None):
    records = []
    for name, raw, expected, requirements in cases:
        path = contained(folder, 'cases/' + name + '.json')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        records.append({'id': name, 'manifest': file_record(path, folder),
                        'expected_host_validation_passed': expected, 'required_issues': requirements,
                        'assessment': layout.evaluate_bytes(raw, inputs)})
    result = {'format': 'hakios.payload-layout-result', 'schema_version': 1,
              'captured_utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'scope': 'host_only',
              'operation': operation, 'phone_writes': False, 'safe_for_loader_placement': False,
              'phase_2_device_gate_passed': False, 'a51_destination_selected': False,
              'retained_audit': report_pin, 'source_manifest': source_pin,
              'generated_inputs': list(generated), 'cases': records, 'counts': counts(records),
              'all_expectations_met': all(meets_expectation(case) for case in records)}
    (folder / 'result.json').write_bytes(encode(result))
    files = [file_record(p, folder) for p in sorted(folder.rglob('*')) if p.is_file()]
    (folder / 'index.json').write_bytes(encode({'schema_version': 1, 'files': files,
        'limits': 'Local integrity; original externally pinned files are required for result readback.'}))
    return result


def verify_result(path, inputs=None):
    inputs = inputs or layout.Inputs()
    folder = path.parent
    index = layout.json_bytes(read_evidence(folder / 'index.json'))
    layout.obj(index, ('schema_version', 'files', 'limits'), 'index')
    layout.require(type(index['schema_version']) is int and index['schema_version'] == 1,
                   'evidence_schema', 'index', 'Unsupported checksum index version')
    layout.string(index['limits'], 'index.limits')
    seen = set()
    for rec in layout.seq(index['files'], 'index.files'):
        layout.obj(rec, ('path', 'size', 'sha256'), 'index.file')
        layout.string(rec['path'], 'index.file.path')
        layout.u64(rec['size'], 'index.file.size')
        layout.checksum(rec['sha256'], 'index.file.sha256')
        target = contained(folder, rec['path'])
        layout.require(rec['path'] not in seen and rec['path'] != 'index.json', 'evidence_index',
                       rec['path'], 'Duplicate/self-referential checksum entry')
        seen.add(rec['path'])
        raw = read_evidence(target)
        layout.require(len(raw) == rec['size'] and layout.sha256(raw) == rec['sha256'],
                       'evidence_checksum', rec['path'], 'Indexed layout evidence changed')
    actual = {p.relative_to(folder).as_posix() for p in folder.rglob('*')
              if p.is_file() and p != folder / 'index.json'}
    layout.require(actual == seen and path.name == 'result.json' and 'result.json' in seen,
                   'evidence_index', 'index', 'Missing, unindexed or incorrectly named evidence')
    result = layout.json_bytes(read_evidence(path))
    layout.obj(result, ('format', 'schema_version', 'captured_utc', 'scope', 'operation', 'phone_writes',
                       'safe_for_loader_placement', 'phase_2_device_gate_passed', 'a51_destination_selected',
                       'retained_audit', 'source_manifest', 'generated_inputs', 'cases', 'counts',
                       'all_expectations_met'), 'result')
    layout.require(result['format'] == 'hakios.payload-layout-result' and type(result['schema_version']) is int
                   and result['schema_version'] == 1 and result['scope'] == 'host_only',
                   'evidence_schema', 'result', 'Unsupported result format/version/scope')
    for key in ('phone_writes', 'safe_for_loader_placement', 'phase_2_device_gate_passed', 'a51_destination_selected'):
        layout.require(result[key] is False, 'evidence_claim', key, 'Unsupported device/placement claim')
    timestamp = dt.datetime.fromisoformat(layout.string(result['captured_utc'], 'captured_utc'))
    layout.require(timestamp.utcoffset() == dt.timedelta(0), 'evidence_schema', 'captured_utc', 'Capture time must be UTC')
    operation = result['operation']
    expected_files, expected_cases = {'result.json'}, None
    if operation == 'demonstrate_retained_a51':
        layout.require(result['retained_audit'] is not None and result['source_manifest'] is None
                       and result['generated_inputs'] == [], 'evidence_schema', 'result', 'Inconsistent A51 demo inputs')
        expected_cases = [(name, encode(manifest), passed, requirements)
                          for name, manifest, passed, requirements in a51_cases(result['retained_audit'], inputs)]
    elif operation == 'demonstrate_synthetic':
        layout.require(result['retained_audit'] is None and result['source_manifest'] is None,
                       'evidence_schema', 'result', 'Inconsistent synthetic inputs')
        generated = []
        pins = []
        for relative, raw in synthetic_files().items():
            target = contained(folder, relative)
            layout.require(read_evidence(target) == raw, 'evidence_synthetic_fixture', relative, 'Synthetic fixture changed')
            generated.append(file_record(target, folder))
            identifier = 'synthetic-fdt' if relative.endswith('.dtb') else 'synthetic-input'
            pins.append(project_pin(target, identifier))
            expected_files.add(relative)
        layout.require(same_json(generated, result['generated_inputs']), 'evidence_schema', 'generated_inputs',
                       'Synthetic generated-input records differ')
        expected_cases = [('synthetic-host-example', encode(synthetic_manifest(pins)), True, [])]
    elif operation == 'validate_manifest':
        layout.require(result['retained_audit'] is None and result['generated_inputs'] == []
                       and result['source_manifest'] is not None, 'evidence_schema', 'result', 'Inconsistent candidate input')
        layout.obj(result['source_manifest'], ('id', 'path', 'size', 'sha256'), 'source_manifest')
        layout.require(result['source_manifest']['id'] == 'source-manifest', 'evidence_schema',
                       'source_manifest.id', 'Unexpected source-manifest identity')
        layout.string(result['source_manifest']['path'], 'source_manifest.path')
        layout.require(layout.u64(result['source_manifest']['size'], 'source_manifest.size') <= layout.MAX_JSON_BYTES,
                       'evidence_bounds', 'source_manifest.size', 'Evidence file exceeds the 2 MiB limit')
        layout.checksum(result['source_manifest']['sha256'], 'source_manifest.sha256')
    else:
        raise layout.LayoutError('evidence_schema', 'operation', 'Unsupported evidence operation')
    cases = layout.seq(result['cases'], 'cases', 64)
    layout.require(bool(cases) and (expected_cases is None or len(cases) == len(expected_cases)),
                   'evidence_cases', 'cases', 'Incorrect number of cases')
    if operation == 'validate_manifest':
        layout.require(len(cases) == 1, 'evidence_cases', 'cases', 'Candidate evaluation requires one case')
    for i, case in enumerate(cases):
        layout.obj(case, ('id', 'manifest', 'expected_host_validation_passed', 'required_issues', 'assessment'), 'case')
        layout.string(case['id'], 'case.id', identifier=True)
        layout.obj(case['manifest'], ('path', 'size', 'sha256'), 'case.manifest')
        relative = case['manifest']['path']
        layout.require(relative == 'cases/' + case['id'] + '.json' and relative in seen,
                       'evidence_cases', 'case.manifest', 'Case is missing or has an unexpected path')
        raw = read_evidence(contained(folder, relative))
        layout.require(same_json(file_record(contained(folder, relative), folder), case['manifest']),
                       'evidence_cases', 'case.manifest', 'Manifest identity differs')
        expected_files.add(relative)
        if expected_cases is not None:
            name, expected_raw, passed, requirements = expected_cases[i]
            layout.require(case['id'] == name and raw == expected_raw
                           and case['expected_host_validation_passed'] is passed and case['required_issues'] == requirements,
                           'evidence_cases', relative, 'Stored diagnostic differs from reconstruction from original inputs')
        else:
            pin = result['source_manifest']
            layout.require(case['id'] == 'candidate' and case['expected_host_validation_passed'] is None
                           and case['required_issues'] == [] and pin['size'] == len(raw)
                           and pin['sha256'] == layout.sha256(raw), 'evidence_cases', relative, 'Candidate snapshot identity differs')
        recomputed = layout.evaluate_bytes(raw, inputs)
        layout.require(same_json(recomputed, case['assessment']), 'evidence_reconstruction', relative,
                       'Stored assessment differs from replay of exact manifest and pinned inputs')
    layout.require(expected_files == seen, 'evidence_index', 'index', 'Unexpected indexed evidence')
    layout.require(same_json(result['counts'], counts(cases))
                   and result['all_expectations_met'] is all(meets_expectation(case) for case in cases),
                   'evidence_counts', 'result', 'Counts/expected-rejection status differ')
    print('Verified layout result:', len(seen), 'indexed files;', len(cases), 'replayed cases;',
          result['counts']['accepted'], 'accepted synthetic;', result['counts']['rejected'], 'rejected; device gate false')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--manifest', help='validate a JSON manifest; rejected candidates return exit 1')
    action.add_argument('--demonstrate-a51', action='store_true', help='prove expected rejections from retained original boot evidence')
    action.add_argument('--demonstrate-synthetic', action='store_true', help='retain a passing synthetic host example')
    action.add_argument('--verify-result', help='replay a project-relative retained result without creating evidence')
    parser.add_argument('--report', help='project-relative boot audit report for --demonstrate-a51')
    args = parser.parse_args()
    if args.report and not args.demonstrate_a51:
        parser.error('--report requires --demonstrate-a51')
    inputs = layout.Inputs()
    if args.verify_result:
        verify_result(contained(PROJECT, args.verify_result), inputs)
        return 0
    folder = PROJECT / 'evidence/phase-2/layout' / dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    report_pin, source_pin = None, None
    if args.demonstrate_a51:
        if args.report:
            report = args.report
        else:
            pointer = layout.json_bytes((PROJECT / 'manifests/boot-audit-current.json').read_bytes())
            report = pointer['report']
            path = contained(PROJECT, report)
            layout.require(layout.sha256(path.read_bytes()) == pointer['sha256'], 'retained_audit_integrity',
                           'report', 'Current boot-audit pointer checksum differs')
        report_pin = layout.pin(contained(PROJECT, report), 'boot-audit')
        cases = [(name, encode(manifest), passed, requirements)
                 for name, manifest, passed, requirements in a51_cases(report_pin, inputs)]
        operation = 'demonstrate_retained_a51'
    elif args.manifest:
        path = layout.physical_path(args.manifest)
        layout.require(path.stat().st_size <= layout.MAX_JSON_BYTES, 'json_bounds', 'manifest', 'Manifest exceeds 2 MiB')
        source_pin = layout.pin(path, 'source-manifest')
        layout.require(source_pin['size'] <= layout.MAX_JSON_BYTES, 'json_bounds', 'manifest', 'Manifest exceeds 2 MiB')
        cases = [('candidate', read_evidence(path), None, [])]
        operation = 'validate_manifest'
    else:
        operation = 'demonstrate_synthetic'
    folder.mkdir(parents=True, exist_ok=False)
    generated = []
    if args.demonstrate_synthetic:
        pins = []
        for relative, raw in synthetic_files().items():
            path = contained(folder, relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            generated.append(file_record(path, folder))
            pins.append(project_pin(path, 'synthetic-fdt' if relative.endswith('.dtb') else 'synthetic-input'))
        cases = [('synthetic-host-example', encode(synthetic_manifest(pins)), True, [])]
    result = capture(folder, operation, cases, inputs, generated, report_pin, source_pin)
    # Use a fresh resolver for publication: re-read originals rather than trusting the creation cache.
    verify_result(folder / 'result.json')
    passed = result['all_expectations_met']
    if operation == 'validate_manifest':
        passed = result['cases'][0]['assessment']['host_validation_passed']
    pointer = {'schema_version': 1, 'result': (folder / 'result.json').relative_to(PROJECT).as_posix(),
               'sha256': layout.sha256((folder / 'result.json').read_bytes()), 'counts': result['counts'],
               'operation': operation, 'host_check_completed': True, 'expected_checks_passed': passed,
               'safe_for_loader_placement': False, 'phase_2_device_gate_passed': False, 'phone_writes': False}
    CURRENT.write_bytes(encode(pointer))
    print(json.dumps(pointer, indent=2))
    for case in result['cases']:
        codes = sorted({issue['code'] for issue in case['assessment']['issues']})
        print(case['id'], case['assessment']['status'], ','.join(codes))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
