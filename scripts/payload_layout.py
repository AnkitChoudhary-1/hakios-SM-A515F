#!/usr/bin/env python3
"""Version 1 host layout contract. This module never copies to physical memory."""
from collections import OrderedDict
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path, PureWindowsPath
import re

from boot_formats import FormatError, parse_arm64_image, parse_fdt, sha256

PROJECT = Path(__file__).resolve().parents[1]
U64_MAX = (1 << 64) - 1
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_INPUT_BYTES = 256 * 1024 * 1024
MAX_CACHE_BYTES = 128 * 1024 * 1024
ROLES = ('loader', 'kernel', 'payload', 'fdt', 'bss', 'stack', 'page_tables', 'scratch', 'logs')
MEMORY_ROLES = ('bss', 'stack', 'page_tables', 'scratch', 'logs')
PREREQUISITES = ('entry_route', 'cpu_state', 'live_fdt', 'memory_ownership', 'log_retrieval', 'return_path')
STATES = ('observed', 'conditional', 'unknown')
BASES = ('synthetic', 'retained_bytes', 'source_declaration', 'runtime_observation', 'unavailable')
LIMITS = [
    'Host consistency only; no payload execution, physical-memory write or device gate.',
    'Observed retained bytes and declared RAM do not establish available physical memory.',
    'Version 1 accepts synthetic host fixtures only; it has no A51 runtime-evidence importer.',
    'Expanded raw extents are assertions; compression, XNU/Mach-O ABI and firmware acceptance are not proved.',
    'Hashes provide local integrity, not authenticity or hardware validation.',
]


class LayoutError(ValueError):
    def __init__(self, code, location, message):
        self.code, self.location = code, location
        super().__init__(message)

    def issue(self):
        return {'code': self.code, 'location': self.location, 'message': str(self)}


def require(condition, code, location, message):
    if not condition:
        raise LayoutError(code, location, message)


def obj(value, keys, location):
    require(type(value) is dict and set(value) == set(keys), 'manifest_schema', location,
            'Expected exactly these fields: ' + ', '.join(keys))
    return value


def seq(value, location, limit=256):
    require(type(value) is list and len(value) <= limit, 'manifest_schema', location,
            'Expected a bounded JSON array (maximum ' + str(limit) + ')')
    return value


def string(value, location, identifier=False):
    require(type(value) is str and 0 < len(value) <= 1024, 'manifest_schema', location,
            'Expected a nonempty string of at most 1024 characters')
    if identifier:
        require(re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{0,63}', value) is not None,
                'manifest_schema', location, 'Invalid identifier')
    return value


def u64(value, location, positive=False):
    if type(value) is str and re.fullmatch(r'0x[0-9a-fA-F]{1,16}', value):
        value = int(value, 16)
    require(type(value) is int and int(positive) <= value <= U64_MAX, 'u64_bounds', location,
            'Expected a ' + ('positive' if positive else 'nonnegative') + ' unsigned 64-bit integer')
    return value


def alignment(value, location):
    value = u64(value, location, positive=True)
    require(value & (value - 1) == 0, 'alignment_value', location,
            'Alignment must be a positive power of two')
    return value


def add(left, right, location):
    require(left <= U64_MAX - right, 'u64_overflow', location,
            'Unsigned 64-bit addition would overflow, including an unrepresentable exclusive end')
    return left + right


def interval(value, location, extra=()):
    obj(value, ('start', 'size', *extra), location)
    start = u64(value['start'], location + '.start')
    size = u64(value['size'], location + '.size', positive=True)
    return dict(value, start=start, size=size, end_exclusive=add(start, size, location))


def overlaps(a, b):
    return a['start'] < b['end_exclusive'] and b['start'] < a['end_exclusive']


def contains(a, b):
    return a['start'] <= b['start'] and b['end_exclusive'] <= a['end_exclusive']


def checksum(value, location):
    require(type(value) is str and re.fullmatch(r'[0-9a-f]{64}', value) is not None,
            'manifest_schema', location, 'Expected a lowercase SHA-256 digest')
    return value


def unique(items, location):
    ids = [item['id'] for item in items]
    require(len(set(ids)) == len(ids), 'duplicate_id', location, 'Duplicate identifier')


def provenance(value, evidence_ids, location):
    obj(value, ('state', 'basis', 'evidence', 'note'), location)
    require(value['state'] in STATES and value['basis'] in BASES,
            'manifest_schema', location, 'Unsupported evidence state or basis')
    string(value['note'], location + '.note')
    refs = seq(value['evidence'], location + '.evidence', 64)
    for ref in refs:
        string(ref, location + '.evidence', identifier=True)
    require(len(set(refs)) == len(refs) and set(refs).issubset(evidence_ids),
            'evidence_reference', location, 'Duplicate or undefined evidence reference')
    require(value['state'] == 'unknown' or bool(refs), 'evidence_reference', location,
            'Observed/conditional assertions require hash-pinned evidence')
    require(value['basis'] != 'unavailable' or value['state'] == 'unknown',
            'manifest_schema', location, 'Unavailable evidence must have unknown state')
    return value


def normalize(manifest):
    """Reject ambiguous/misspelled fields before assessing incomplete layouts."""
    obj(manifest, ('format', 'schema_version', 'target', 'purpose', 'evidence', 'retained_audit',
                   'memory', 'prerequisites', 'entry', 'components'), 'manifest')
    require(manifest['format'] == 'hakios.payload-layout' and type(manifest['schema_version']) is int
            and manifest['schema_version'] == 1, 'manifest_schema', 'manifest',
            'Unsupported layout format/version')
    require(manifest['target'] in ('synthetic-host', 'a51-retained-host'), 'manifest_schema',
            'target', 'Unsupported target; no runtime A51 target exists in version 1')
    string(manifest['purpose'], 'purpose')
    evidence = []
    for i, rec in enumerate(seq(manifest['evidence'], 'evidence', 64)):
        loc = 'evidence[' + str(i) + ']'
        obj(rec, ('id', 'path', 'size', 'sha256'), loc)
        evidence.append({'id': string(rec['id'], loc + '.id', identifier=True),
                         'path': string(rec['path'], loc + '.path'),
                         'size': u64(rec['size'], loc + '.size', positive=True),
                         'sha256': checksum(rec['sha256'], loc + '.sha256')})
    unique(evidence, 'evidence')
    require(sum(rec['size'] for rec in evidence) <= MAX_INPUT_BYTES, 'input_bounds', 'evidence',
            'Combined pinned inputs exceed 256 MiB')
    ids = {rec['id'] for rec in evidence}
    binding = manifest['retained_audit']
    if binding is not None:
        obj(binding, ('evidence', 'image', 'section', 'entry_index'), 'retained_audit')
        string(binding['evidence'], 'retained_audit.evidence', identifier=True)
        require(binding['evidence'] in ids, 'evidence_reference', 'retained_audit',
                'Retained audit evidence is undefined')
        string(binding['image'], 'retained_audit.image')
        string(binding['section'], 'retained_audit.section')
        binding = dict(binding, entry_index=u64(binding['entry_index'], 'retained_audit.entry_index'))
    require((manifest['target'] == 'a51-retained-host') == (binding is not None),
            'target_binding', 'retained_audit', 'A51 retained target requires an audit; synthetic target excludes it')
    memory = obj(manifest['memory'], ('allowed', 'excluded', 'dynamic'), 'memory')
    ranges = {}
    for kind in ('allowed', 'excluded'):
        ranges[kind] = []
        for i, rec in enumerate(seq(memory[kind], 'memory.' + kind)):
            loc = 'memory.' + kind + '[' + str(i) + ']'
            extra = ('id', 'owner', 'provenance') if kind == 'excluded' else ('id', 'provenance')
            item = interval(rec, loc, extra)
            string(item['id'], loc + '.id', identifier=True)
            if kind == 'excluded':
                string(item['owner'], loc + '.owner')
            provenance(item['provenance'], ids, loc + '.provenance')
            ranges[kind].append(item)
        unique(ranges[kind], 'memory.' + kind)
    dynamic = []
    for i, rec in enumerate(seq(memory['dynamic'], 'memory.dynamic')):
        loc = 'memory.dynamic[' + str(i) + ']'
        obj(rec, ('id', 'owner', 'size', 'alignment', 'alloc_ranges', 'placement',
                  'declaration', 'placement_provenance'), loc)
        item = dict(rec, size=u64(rec['size'], loc + '.size', positive=True))
        string(item['id'], loc + '.id', identifier=True)
        string(item['owner'], loc + '.owner')
        if rec['alignment'] is not None:
            item['alignment'] = alignment(rec['alignment'], loc + '.alignment')
        item['alloc_ranges'] = [interval(r, loc + '.alloc_ranges') for r in seq(rec['alloc_ranges'], loc + '.alloc_ranges')]
        item['placement'] = interval(rec['placement'], loc + '.placement') if rec['placement'] is not None else None
        provenance(item['declaration'], ids, loc + '.declaration')
        provenance(item['placement_provenance'], ids, loc + '.placement_provenance')
        dynamic.append(item)
    unique(dynamic, 'memory.dynamic')
    prereqs = obj(manifest['prerequisites'], PREREQUISITES, 'prerequisites')
    for name, rec in prereqs.items():
        provenance(rec, ids, 'prerequisites.' + name)
    components = []
    for i, rec in enumerate(seq(manifest['components'], 'components', 64)):
        loc = 'components[' + str(i) + ']'
        obj(rec, ('id', 'role', 'start', 'execution_bytes', 'alignment', 'reserve_alignment',
                  'prefix_bytes', 'suffix_bytes', 'format', 'image', 'extent_provenance'), loc)
        item = dict(rec)
        string(item['id'], loc + '.id', identifier=True)
        require(item['role'] in ROLES, 'manifest_schema', loc + '.role', 'Unsupported component role')
        require(item['format'] in ('raw', 'expanded', 'arm64-image', 'fdt', 'zeroed'),
                'manifest_schema', loc + '.format', 'Unsupported content format')
        for field in ('start', 'execution_bytes'):
            if item[field] is not None:
                item[field] = u64(item[field], loc + '.' + field, positive=field == 'execution_bytes')
        for field in ('alignment', 'reserve_alignment'):
            item[field] = alignment(item[field], loc + '.' + field)
        for field in ('prefix_bytes', 'suffix_bytes'):
            item[field] = u64(item[field], loc + '.' + field)
        provenance(item['extent_provenance'], ids, loc + '.extent_provenance')
        content = item['image']
        if content is not None:
            obj(content, ('evidence', 'offset', 'size', 'sha256'), loc + '.image')
            string(content['evidence'], loc + '.image.evidence', identifier=True)
            require(content['evidence'] in ids, 'evidence_reference', loc + '.image',
                    'Component input evidence is undefined')
            item['image'] = dict(content, offset=u64(content['offset'], loc + '.image.offset'),
                                 size=u64(content['size'], loc + '.image.size', positive=True),
                                 sha256=checksum(content['sha256'], loc + '.image.sha256'))
            add(item['image']['offset'], item['image']['size'], loc + '.image')
        components.append(item)
    unique(components, 'components')
    entry = obj(manifest['entry'], ('component', 'offset', 'alignment', 'abi'), 'entry')
    string(entry['component'], 'entry.component', identifier=True)
    string(entry['abi'], 'entry.abi')
    entry = dict(entry, offset=u64(entry['offset'], 'entry.offset'),
                 alignment=alignment(entry['alignment'], 'entry.alignment'))
    return dict(manifest, evidence=evidence, retained_audit=binding, memory=dict(ranges, dynamic=dynamic),
                components=components, entry=entry)


def json_bytes(content):
    require(len(content) <= MAX_JSON_BYTES, 'json_bounds', 'manifest', 'JSON exceeds the 2 MiB limit')

    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate_json_key', key, 'Duplicate JSON key')
            result[key] = value
        return result

    def constant(value):
        raise LayoutError('manifest_schema', 'manifest', 'Nonfinite JSON number: ' + value)

    try:
        return json.loads(content.decode('utf-8-sig'), object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        if isinstance(exc, LayoutError):
            raise
        raise LayoutError('manifest_json', 'manifest', 'Invalid UTF-8 JSON: ' + str(exc)) from exc


def physical_path(value, root=PROJECT):
    if len(value) > 2 and value[1:3] in (':\\', ':/'):
        if os.name == 'nt':
            return Path(value)
        win = PureWindowsPath(value)
        return Path('/mnt') / win.drive[0].lower() / Path(*win.parts[1:])
    if value.startswith('/opt/') and os.name == 'nt':
        return Path(r'\\wsl.localhost\A51-KernelBuilder') / value.lstrip('/')
    path = Path(value)
    return path if path.is_absolute() else root / path


def pin(path, identifier):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return {'id': identifier, 'path': str(path), 'size': path.stat().st_size, 'sha256': digest.hexdigest()}


class Inputs:
    """Use the same checked byte snapshot for every case in one host evaluation."""
    def __init__(self, root=PROJECT):
        self.root, self.cache, self.cache_bytes = root, OrderedDict(), 0
        self.audits = {}

    def read(self, rec):
        key = (rec['path'], rec['size'], rec['sha256'])
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        path = physical_path(rec['path'], self.root)
        require(rec['size'] <= MAX_INPUT_BYTES, 'input_bounds', rec['id'], 'Evidence input exceeds 256 MiB')
        try:
            require(path.stat().st_size == rec['size'], 'input_size', rec['id'],
                    'Input size differs from its pin: ' + rec['path'])
            with path.open('rb') as stream:
                content = stream.read(rec['size'] + 1)
        except OSError as exc:
            raise LayoutError('input_unavailable', rec['id'], 'Cannot read pinned input: ' + rec['path']) from exc
        require(len(content) == rec['size'], 'input_size', rec['id'], 'Input changed/truncated while reading')
        require(sha256(content) == rec['sha256'], 'input_checksum', rec['id'], 'Input checksum differs from its pin')
        if len(content) <= MAX_CACHE_BYTES:
            while self.cache_bytes + len(content) > MAX_CACHE_BYTES:
                _, old = self.cache.popitem(last=False)
                self.cache_bytes -= len(old)
            self.cache[key] = content
            self.cache_bytes += len(content)
        return content

    def retained(self, binding, rec):
        key = (rec['path'], rec['size'], rec['sha256'])
        if key not in self.audits:
            content = self.read(rec)
            spec = importlib.util.spec_from_file_location('layout_boot_audit', Path(__file__).with_name('audit-boot-inputs.py'))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    module.verify_report(physical_path(rec['path'], self.root))
            except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
                raise LayoutError('retained_audit_integrity', 'retained_audit',
                                  'Original-byte boot audit verification failed: ' + str(exc)) from exc
            require(physical_path(rec['path'], self.root).read_bytes() == content, 'retained_audit_integrity',
                    'retained_audit', 'Audit report changed during original-byte verification')
            self.audits[key] = json_bytes(content)
        report = self.audits[key]
        try:
            image = next(i for i in report['images'] if i['name'] == binding['image'])
            table = next(t for t in image['tables'] if t['section'] == binding['section'])
            entry = next(e for e in table['entries'] if e['index'] == binding['entry_index'])
        except (StopIteration, KeyError, TypeError) as exc:
            raise LayoutError('retained_audit_selection', 'retained_audit', 'Selected retained base FDT is absent') from exc
        require(binding['section'] == 'dtb' and bool(entry['summary']['declared_memory']),
                'retained_audit_selection', 'retained_audit', 'An unapplied overlay cannot supply base RAM')
        return retained_facts(entry['summary'], rec['id']), image, entry


def observed(basis, evidence, note):
    return {'state': 'observed', 'basis': basis, 'evidence': evidence, 'note': note}


def unknown(note):
    return {'state': 'unknown', 'basis': 'unavailable', 'evidence': [], 'note': note}


def retained_facts(summary, evidence_id):
    """Import declarations as exclusions, never as an available-memory allowlist."""
    declaration = observed('source_declaration', [evidence_id], 'Observed in retained base FDT; live ownership/selection unknown')
    declared, excluded, dynamic = [], [], []
    for i, span in enumerate(summary['declared_memory']):
        declared.append({'id': 'retained-ram-' + str(i), 'start': span['start'], 'size': span['size'],
                         'end_exclusive': span['end_exclusive'], 'provenance': declaration})
    for node in summary['reserved_memory']:
        for span in node['ranges']:
            excluded.append({'id': 'retained-fixed-' + str(len(excluded)), 'owner': node['node'],
                             'start': span['start'], 'size': span['size'], 'end_exclusive': span['end_exclusive'],
                             'provenance': declaration})
        if node['dynamic_size']:
            dynamic.append({'id': 'retained-dynamic-' + str(len(dynamic)), 'owner': node['node'],
                            'size': node['dynamic_size'], 'alignment': node.get('alignment'),
                            'alloc_ranges': [{k: span[k] for k in ('start', 'size', 'end_exclusive')}
                                             for span in node.get('alloc_ranges', [])],
                            'placement': None, 'declaration': declaration,
                            'placement_provenance': unknown('Dynamic reservation address is absent from retained evidence')})
    for span in summary['memreserve']:
        excluded.append({'id': 'retained-header-' + str(len(excluded)), 'owner': 'FDT header memreserve',
                         'start': span['start'], 'size': span['size'], 'end_exclusive': span['end_exclusive'],
                         'provenance': declaration})
    # Normalize imported arithmetic too; do not rely only on the upstream parser.
    for item in declared + excluded:
        require(add(u64(item['start'], item['id']), u64(item['size'], item['id'], positive=True), item['id'])
                == item['end_exclusive'], 'retained_audit_bounds', item['id'], 'Inconsistent retained interval')
    return {'declared': declared, 'excluded': excluded, 'dynamic': dynamic}


def empty_assessment():
    return {'schema_version': 1, 'validator': 'hakios.payload-layout.v1', 'target': None,
            'status': 'rejected_host_layout', 'host_validation_passed': False,
            'safe_for_loader_placement': False, 'phase_2_device_gate_passed': False, 'phone_writes': False,
            'issues': [], 'memory': {'declared': [], 'allowed': [], 'excluded': [], 'dynamic': []},
            'components': [], 'entry_address': None, 'limits': list(LIMITS)}


def evaluate(manifest, inputs=None):
    result = empty_assessment()
    inputs = inputs or Inputs()
    issues = result['issues']

    def issue(code, location, message):
        issues.append({'code': code, 'location': location, 'message': message})

    try:
        data = normalize(manifest)
    except LayoutError as exc:
        issues.append(exc.issue())
        return result
    result['target'] = data['target']
    pins = {rec['id']: rec for rec in data['evidence']}
    content = {}
    for name, rec in pins.items():
        try:
            content[name] = inputs.read(rec)
        except LayoutError as exc:
            issues.append(exc.issue())
    facts, retained_image, retained_entry = None, None, None
    if data['retained_audit'] is not None:
        issue('a51_runtime_evidence_unavailable', 'target',
              'Retained A51 declarations cannot prove live entry, ownership, FDT, logs or return; version 1 has no runtime importer')
        rec = pins[data['retained_audit']['evidence']]
        if rec['id'] in content:
            try:
                facts, retained_image, retained_entry = inputs.retained(data['retained_audit'], rec)
            except LayoutError as exc:
                issues.append(exc.issue())
    effective = result['memory']
    effective['allowed'] = data['memory']['allowed']
    effective['excluded'] = list(data['memory']['excluded']) + (facts['excluded'] if facts else [])
    effective['dynamic'] = list(data['memory']['dynamic']) + (facts['dynamic'] if facts else [])
    effective['declared'] = facts['declared'] if facts else []
    for name, prov in data['prerequisites'].items():
        if prov['state'] != 'observed':
            issue('prerequisite_unresolved', 'prerequisites.' + name, 'Prerequisite evidence is ' + prov['state'])
        elif prov['basis'] != 'synthetic' or data['target'] != 'synthetic-host':
            issue('prerequisite_unverified', 'prerequisites.' + name,
                  'Retained/source assertions and caller labels cannot establish a runtime prerequisite')
    trusted_allowed = []
    for rec in effective['allowed']:
        prov = rec['provenance']
        if data['target'] == 'synthetic-host' and prov['state'] == 'observed' and prov['basis'] == 'synthetic':
            trusted_allowed.append(rec)
        else:
            issue('allowed_interval_unverified', 'memory.allowed.' + rec['id'],
                  'An available interval needs supported ownership evidence; declared RAM/gaps are insufficient')
    if not trusted_allowed:
        issue('available_memory_unresolved', 'memory.allowed', 'No supported owned interval is available')
    for i, a in enumerate(effective['allowed']):
        for b in effective['allowed'][i + 1:]:
            if overlaps(a, b):
                issue('allowed_intervals_overlap', 'memory.allowed', a['id'] + ' overlaps ' + b['id'])
    for rec in effective['excluded']:
        if rec['provenance']['state'] != 'observed':
            issue('exclusion_unresolved', 'memory.excluded.' + rec['id'], 'Reservation extent/owner is not observed')
    dynamic_placements = []
    for rec in effective['dynamic']:
        loc = 'memory.dynamic.' + rec['id']
        if rec['declaration']['state'] != 'observed':
            issue('dynamic_declaration_unresolved', loc, 'Dynamic reservation size/owner declaration is unresolved')
        placement = rec['placement']
        prov = rec['placement_provenance']
        if placement is None or prov['state'] != 'observed':
            issue('dynamic_ownership_unresolved', loc, 'Dynamic reservation placement/ownership is unresolved')
        if rec['alignment'] is None:
            issue('dynamic_alignment_unresolved', loc, 'Dynamic reservation alignment is unknown')
        if placement is None:
            continue
        dynamic_placements.append(dict(placement, id=rec['id'], owner=rec['owner']))
        if prov['basis'] != 'synthetic' or data['target'] != 'synthetic-host':
            issue('dynamic_ownership_unverified', loc, 'Dynamic ownership evidence is unsupported in this host contract')
        if placement['size'] != rec['size']:
            issue('dynamic_size', loc, 'Placement must cover the full declared allocation size')
        if rec['alignment'] is not None and placement['start'] % rec['alignment']:
            issue('dynamic_alignment', loc, 'Placement violates declared alignment')
        if rec['alloc_ranges'] and not any(contains(r, placement) for r in rec['alloc_ranges']):
            issue('dynamic_alloc_range', loc, 'Placement is outside its allocation constraints')
        if not any(contains(r, placement) for r in trusted_allowed):
            issue('dynamic_outside_allowed', loc, 'Placed dynamic reservation is outside an owned interval')
        for excluded in effective['excluded']:
            if overlaps(placement, excluded):
                issue('dynamic_reserved_overlap', loc, 'Dynamic allocation overlaps ' + excluded['owner'])
    for i, a in enumerate(dynamic_placements):
        for b in dynamic_placements[i + 1:]:
            if overlaps(a, b):
                issue('dynamic_placements_overlap', 'memory.dynamic', a['id'] + ' overlaps ' + b['id'])
    missing = set(ROLES) - {rec['role'] for rec in data['components']}
    for role in ROLES:
        if role in missing:
            issue('component_role_missing', 'components.' + role, 'Full layout requires a separate ' + role + ' component')
    for rec in data['components']:
        loc = 'components.' + rec['id']
        component = {'id': rec['id'], 'role': rec['role'], 'execution_bytes': rec['execution_bytes'],
                     'minimum_execution_bytes': None, 'image_sha256': None, 'touch': None, 'reservation': None}
        result['components'].append(component)
        prov = rec['extent_provenance']
        if prov['state'] != 'observed' or prov['basis'] not in ('synthetic', 'retained_bytes'):
            issue('execution_extent_unverified', loc, 'Full decompressed/zeroed/touched extent is not supported by evidence')
        if rec['role'] in MEMORY_ROLES:
            if rec['format'] != 'zeroed' or rec['image'] is not None:
                issue('component_format', loc, 'Memory/BSS regions require separate zeroed extents without file content')
        elif rec['image'] is None:
            issue('component_input_missing', loc, 'File-backed component has no pinned input')
        if rec['role'] == 'fdt' and rec['format'] != 'fdt':
            issue('component_format', loc, 'FDT requires bounded FDT parsing')
        elif rec['role'] not in MEMORY_ROLES and rec['role'] != 'fdt' and rec['format'] not in ('raw', 'expanded', 'arm64-image'):
            issue('component_format', loc, 'File-backed executable/payload format is unsupported')
        if rec['format'] == 'expanded' and data['target'] != 'synthetic-host':
            issue('expanded_extent_unverified', loc, 'Version 1 cannot verify a real decompressor execution extent')
        image = rec['image']
        if image is not None and image['evidence'] in content:
            try:
                whole = content[image['evidence']]
                end = add(image['offset'], image['size'], loc + '.image')
                require(end <= len(whole), 'component_input_bounds', loc, 'Image slice extends beyond its pinned file')
                blob = whole[image['offset']:end]
                require(sha256(blob) == image['sha256'], 'component_checksum', loc, 'Image slice checksum differs')
                minimum = len(blob)
                if rec['format'] == 'arm64-image':
                    header = parse_arm64_image(blob)
                    require(header['image_size'] > 0, 'execution_extent_unverified', loc,
                            'Legacy zero-size Linux Image header does not define an execution extent')
                    minimum = max(minimum, header['image_size'])
                elif rec['format'] == 'fdt':
                    tree = parse_fdt(blob)
                    require(tree.header['totalsize'] == len(blob), 'component_fdt_bounds', loc,
                            'FDT slice must match totalsize exactly')
                if retained_entry is not None and rec['role'] == 'fdt':
                    require(image['sha256'] == retained_entry['sha256'], 'retained_fdt_mismatch', loc,
                            'Diagnostic FDT differs from the selected retained base; live FDT is still unknown')
                if retained_image is not None and rec['role'] == 'kernel' and rec['format'] == 'arm64-image':
                    require(image['sha256'] == retained_image['boot_header']['sections']['kernel']['sha256'],
                            'retained_kernel_mismatch', loc, 'Diagnostic Linux Image differs from the selected retained image')
                component['minimum_execution_bytes'] = minimum
                component['image_sha256'] = image['sha256']
                if rec['execution_bytes'] is not None and rec['execution_bytes'] < minimum:
                    issue('execution_extent_too_small', loc, 'Full execution extent is smaller than stored/parsed image extent')
            except LayoutError as exc:
                issues.append(exc.issue())
            except FormatError as exc:
                issue('component_binary_format', loc, str(exc))
        if rec['start'] is None:
            issue('component_unplaced', loc, 'No destination is selected')
        if rec['execution_bytes'] is None:
            issue('execution_extent_unresolved', loc, 'Execution extent is unknown')
        if rec['start'] is None or rec['execution_bytes'] is None:
            continue
        try:
            start, size = rec['start'], rec['execution_bytes']
            if start % rec['alignment']:
                issue('component_alignment', loc, 'Content address violates its alignment')
            end = add(start, size, loc)
            require(start >= rec['prefix_bytes'], 'u64_underflow', loc, 'Prefix would begin below address zero')
            reserved_start = (start - rec['prefix_bytes']) & -rec['reserve_alignment']
            reserved_end = add(end, rec['suffix_bytes'], loc)
            reserved_end = add(reserved_end, (-reserved_end) % rec['reserve_alignment'], loc)
            touch = {'start': start, 'size': size, 'end_exclusive': end}
            reserve = {'start': reserved_start, 'size': reserved_end - reserved_start, 'end_exclusive': reserved_end}
            component['touch'], component['reservation'] = touch, reserve
            if not any(contains(r, reserve) for r in trusted_allowed):
                issue('component_outside_allowed', loc, 'Entire extent including prefix, suffix and alignment padding must fit one owned interval')
            for excluded in effective['excluded'] + dynamic_placements:
                if overlaps(reserve, excluded):
                    issue('reserved_overlap', loc, 'Full reservation overlaps ' + excluded['id'] + ' (' + excluded['owner'] + ')')
        except LayoutError as exc:
            issues.append(exc.issue())
    placed = [rec for rec in result['components'] if rec['reservation'] is not None]
    for i, a in enumerate(placed):
        for b in placed[i + 1:]:
            if overlaps(a['reservation'], b['reservation']):
                issue('components_overlap', 'components', a['id'] + ' overlaps ' + b['id'] + ' including effective/padded extent')
    entry = data['entry']
    destination = next((r for r in data['components'] if r['id'] == entry['component']), None)
    if destination is None or destination['role'] != 'loader' or destination['format'] not in ('raw', 'expanded'):
        issue('entry_component', 'entry', 'Entry must refer to a file-backed loader component')
    elif destination['start'] is None or destination['execution_bytes'] is None:
        issue('entry_unresolved', 'entry', 'Loader entry address/extent is unresolved')
    else:
        try:
            address = add(destination['start'], entry['offset'], 'entry')
            result['entry_address'] = address
            if entry['offset'] >= destination['execution_bytes']:
                issue('entry_bounds', 'entry', 'Entry lies outside the loader execution extent')
            if destination['format'] == 'raw' and (destination['image'] is None or entry['offset'] >= destination['image']['size']):
                issue('entry_bounds', 'entry', 'Raw loader entry must lie inside stored code bytes')
            if address % entry['alignment']:
                issue('entry_alignment', 'entry', 'Entry address violates alignment')
        except LayoutError as exc:
            issues.append(exc.issue())
    if not issues:
        result['host_validation_passed'], result['status'] = True, 'accepted_synthetic_host_only'
    return result


def evaluate_bytes(content, inputs=None):
    try:
        return evaluate(json_bytes(content), inputs)
    except LayoutError as exc:
        result = empty_assessment()
        result['issues'].append(exc.issue())
        return result
