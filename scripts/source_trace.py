"""Bounded capture and reconstruction of retained Linux source declarations.

This tool preserves source bytes, numbered excerpts and config/FDT facts. It
does not implement a loader, query a phone or establish runtime ownership.
"""
import datetime as dt
import importlib.util
import json
import math
from pathlib import Path, PurePosixPath, PureWindowsPath
import re

from boot_formats import cells, parse_fdt, sha256, strings, summarize_fdt

PROJECT = Path(__file__).resolve().parents[1]
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
MAX_JSON = 512 * 1024
MAX_FILE = 4 * 1024 * 1024
MAX_FDT = 2 * 1024 * 1024
MAX_TOTAL = 32 * 1024 * 1024
MAX_FILES = 256
TOOL_FILES = (
    'scripts/source_trace.py', 'scripts/trace-loader-sources.py',
    'scripts/test-source-trace.py', 'scripts/boot_formats.py',
    'scripts/audit-boot-inputs.py', 'scripts/run.py',
)
FALSE_FLAGS = (
    'phone_writes', 'phone_queries', 'phase_2_device_gate_passed',
    'safe_for_loader_placement', 'a51_destination_selected',
    'live_fdt_selection_verified', 'runtime_memory_ownership_verified',
    'probe_log_retrieval_verified', 'return_to_android_verified',
)

_spec = importlib.util.spec_from_file_location('trace_boot_audit', Path(__file__).with_name('audit-boot-inputs.py'))
audit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(audit)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def same_json(left, right):
    # JSON booleans must not compare equal to integer metadata.
    return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(right, sort_keys=True, allow_nan=False)


def relative_path(value):
    require(isinstance(value, str) and 0 < len(value) <= 300, 'invalid relative path')
    require(not any(c in value for c in '\\:\x00\r\n'), 'invalid relative path characters')
    path = PurePosixPath(value)
    require(path.parts and not path.is_absolute() and path.as_posix() == value
            and all(part not in ('.', '..') for part in path.parts), 'noncanonical/escaping relative path')
    return value


def contained(root, value):
    path = (root / relative_path(value)).resolve()
    require(path.is_relative_to(root.resolve()), 'path escapes its root: ' + value)
    return path


def original_path(value, project):
    require(isinstance(value, str) and value, 'invalid original path')
    mapped = audit.input_path(value)
    if mapped.is_absolute():
        return mapped
    return contained(project, value)


def bounded_read(path, limit=MAX_FILE):
    require(path.is_file(), 'missing input: ' + str(path))
    require(path.stat().st_size <= limit, 'input exceeds byte limit: ' + str(path))
    with path.open('rb') as stream:
        content = stream.read(limit + 1)
    require(len(content) <= limit, 'input grew beyond byte limit: ' + str(path))
    return content


def decode_json(content):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate JSON key: ' + key)
            result[key] = value
        return result

    def constant(value):
        raise ValueError('nonfinite JSON constant: ' + value)

    def finite_float(value):
        result = float(value)
        require(math.isfinite(result), 'nonfinite JSON number: ' + value)
        return result

    return json.loads(content.decode('utf-8-sig'), object_pairs_hook=pairs,
                      parse_constant=constant, parse_float=finite_float)


def retained_limit(name):
    if name in ('specification.json', 'report.json', 'inputs/boot-report.json', 'inputs/repack-validation.json'):
        return MAX_JSON
    if name.startswith('fdts/'):
        return MAX_FDT
    return MAX_FILE


def json_bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')


def record(original, copy, content):
    return {'original': original, 'copy': copy, 'size': len(content), 'sha256': sha256(content)}


def validate_spec(spec):
    keys = {'schema_version', 'target', 'source_root', 'lineage_commit', 'boot_report', 'config_symbols', 'sources'}
    require(isinstance(spec, dict) and set(spec) == keys, 'unsupported specification fields')
    require(type(spec['schema_version']) is int and spec['schema_version'] == 1, 'unsupported specification version')
    require(spec['target'] == 'a51-retained-source', 'unsupported trace target')
    require(isinstance(spec['source_root'], str) and audit.input_path(spec['source_root']).is_absolute(), 'source root must be absolute')
    require(isinstance(spec['lineage_commit'], str) and re.fullmatch(r'[0-9a-f]{40}', spec['lineage_commit']), 'invalid lineage commit')
    boot = spec['boot_report']
    require(isinstance(boot, dict) and set(boot) == {'path', 'sha256'}, 'invalid boot report pin')
    require(isinstance(boot['path'], str) and boot['path'], 'invalid boot report path')
    require(isinstance(boot['sha256'], str) and re.fullmatch(r'[0-9a-f]{64}', boot['sha256']), 'invalid boot report hash')
    symbols = spec['config_symbols']
    require(isinstance(symbols, list) and 0 < len(symbols) <= 64, 'invalid config symbol count')
    require(all(isinstance(s, str) and re.fullmatch(r'CONFIG_[A-Z0-9_]+', s) for s in symbols), 'invalid config symbol')
    require(len(set(symbols)) == len(symbols), 'duplicate config symbol')
    sources = spec['sources']
    require(isinstance(sources, list) and 0 < len(sources) <= 64, 'invalid source count')
    seen_paths, seen_ids = set(), set()
    for source in sources:
        require(isinstance(source, dict) and set(source) == {'path', 'excerpts'}, 'invalid source entry')
        path = relative_path(source['path'])
        require(path not in seen_paths, 'duplicate source path')
        seen_paths.add(path)
        excerpts = source['excerpts']
        require(isinstance(excerpts, list) and 0 < len(excerpts) <= 8, 'invalid excerpt count')
        for excerpt in excerpts:
            require(isinstance(excerpt, dict) and set(excerpt) == {'id', 'start', 'end', 'purpose'}, 'invalid excerpt fields')
            name = excerpt['id']
            require(isinstance(name, str) and re.fullmatch(r'[a-z0-9][a-z0-9-]{0,79}', name), 'invalid excerpt id')
            require(name not in seen_ids, 'duplicate excerpt id')
            seen_ids.add(name)
            require(type(excerpt['start']) is int and type(excerpt['end']) is int
                    and 1 <= excerpt['start'] <= excerpt['end'] <= 100000
                    and excerpt['end'] - excerpt['start'] < 4096, 'invalid excerpt bounds')
            require(isinstance(excerpt['purpose'], str) and 0 < len(excerpt['purpose']) <= 500, 'invalid excerpt purpose')
    require(len(seen_ids) <= 128, 'too many excerpts')


def numbered_excerpt(content, start, end):
    # Keep the original line ending bytes and the final newline's presence.
    content.decode('utf-8')
    lines = content.splitlines(keepends=True)
    require(type(start) is int and type(end) is int and 1 <= start <= end <= len(lines), 'excerpt outside source lines')
    return b''.join(str(i).encode('ascii') + b':' + lines[i - 1] for i in range(start, end + 1))


def config_facts(content, symbols):
    definitions = {}
    for number, line in enumerate(content.decode('utf-8').splitlines(), 1):
        enabled = re.fullmatch(r'(CONFIG_[A-Z0-9_]+)=(.*)', line)
        disabled = re.fullmatch(r'# (CONFIG_[A-Z0-9_]+) is not set', line)
        if enabled or disabled:
            symbol = (enabled or disabled)[1]
            require(symbol not in definitions, 'duplicate configuration definition: ' + symbol)
            definitions[symbol] = {'value': enabled[2] if enabled else 'n', 'line': number, 'text': line}
    return {symbol: definitions.get(symbol, {'value': None, 'line': None, 'text': None}) for symbol in symbols}


def node_facts(tree, path):
    properties = tree.nodes.get(path)
    if properties is None:
        return None
    decoded = {}
    for key, value in properties.items():
        if key in ('compatible', 'method'):
            decoded[key] = strings(value)
        elif key in ('cpu_suspend', 'cpu_off', 'cpu_on', 'pmu_base', 'reg', 'size', 'alignment', 'alloc-ranges'):
            decoded[key] = cells(value)
    return {'raw_properties': {key: value.hex() for key, value in sorted(properties.items())}, 'decoded': decoded}


def fdt_facts(content):
    tree = parse_fdt(content)
    summary = summarize_fdt(tree)
    log_paths = sorted(path for path in tree.nodes if path.startswith('/reserved-memory/debug_snapshot/'))
    return {
        'psci': node_facts(tree, '/psci'), 'reboot': node_facts(tree, '/reboot'),
        'debug_snapshot_nodes': {path: node_facts(tree, path) for path in log_paths},
        'dynamic_nodes': {path: node_facts(tree, path) for path in summary['dynamic_reservations']},
        'declared_memory': summary['declared_memory'], 'declared_memory_bytes': summary['declared_memory_bytes'],
        'reserved_memory': summary['reserved_memory'],
        'safe_for_loader_placement': False, 'live_selection_verified': False,
    }


def collect(spec_content, created, project=PROJECT):
    require(len(spec_content) <= MAX_JSON, 'specification exceeds byte limit')
    spec = decode_json(spec_content)
    validate_spec(spec)
    require(isinstance(created, dict) and set(created) == {'utc', 'ist'}, 'invalid capture times')
    utc, ist = (dt.datetime.fromisoformat(created[key]) for key in ('utc', 'ist'))
    require(utc.utcoffset() == dt.timedelta(0) and ist.utcoffset() == dt.timedelta(hours=5, minutes=30)
            and utc == ist, 'capture UTC/IST labels disagree')
    files = {'specification.json': spec_content}

    def retain(logical, relative, limit=None):
        require(relative not in files, 'duplicate retained path')
        content = bounded_read(original_path(logical, project), retained_limit(relative) if limit is None else limit)
        files[relative] = content
        require(sum(map(len, files.values())) <= MAX_TOTAL, 'trace exceeds total byte limit')
        return record(logical, relative, content), content

    boot_pin = spec['boot_report']
    boot_record, boot_content = retain(boot_pin['path'], 'inputs/boot-report.json')
    require(boot_record['sha256'] == boot_pin['sha256'], 'selected boot report hash changed')
    boot_path = original_path(boot_pin['path'], project)
    audit.verify_report(boot_path)
    boot = decode_json(boot_content)
    references = {PureWindowsPath(rec['path']).name: rec for rec in boot['references']}
    inputs = {}
    for basename in ('kernel.config', 'repack-validation.json'):
        require(basename in references, 'missing audited reference: ' + basename)
        pin = references[basename]
        rec, content = retain(pin['path'], 'inputs/' + basename)
        require(type(pin['size']) is int and rec['size'] == pin['size'] and rec['sha256'] == pin['sha256'], 'audited reference changed')
        inputs[basename] = (rec, content)
    lineage = decode_json(inputs['repack-validation.json'][1])
    url = lineage.get('kernel_source')
    require(isinstance(url, str) and url.endswith('/commit/' + spec['lineage_commit']), 'lineage record does not match commit')
    source_root = original_path(spec['source_root'], project)
    require(source_root.is_dir(), 'source root is unavailable')
    sources = []
    for source in spec['sources']:
        name = source['path']
        physical = contained(source_root, name)
        logical = spec['source_root'].rstrip('/\\') + '/' + name
        require(original_path(logical, project).resolve() == physical, 'source path resolution disagrees')
        rec, content = retain(logical, 'sources/' + name)
        excerpts = []
        for selection in source['excerpts']:
            excerpt = numbered_excerpt(content, selection['start'], selection['end'])
            require(len(excerpt) <= MAX_FILE, 'numbered excerpt exceeds byte limit')
            path = 'excerpts/' + selection['id'] + '.txt'
            require(path not in files, 'duplicate excerpt output')
            files[path] = excerpt
            require(sum(map(len, files.values())) <= MAX_TOTAL, 'trace exceeds total byte limit')
            excerpts.append({**selection, 'copy': path, 'size': len(excerpt), 'sha256': sha256(excerpt)})
        sources.append({'input': rec, 'line_count': len(content.splitlines()), 'excerpts': excerpts})
    base_fdts = []
    for image in boot['images']:
        for table in image['tables']:
            if table['section'] != 'dtb':
                continue
            for entry in table['entries']:
                extracted = relative_path(entry['extracted_blob'])
                logical = str(boot_path.parent / extracted)
                # Store project-relative identities where possible, for both hosts.
                if (boot_path.parent / extracted).is_relative_to(project):
                    logical = (boot_path.parent / extracted).relative_to(project).as_posix()
                rec, content = retain(logical, 'fdts/' + image['name'] + '.dtb', MAX_FDT)
                require(same_json(summarize_fdt(parse_fdt(content)), entry['summary']), 'base FDT differs from audited summary')
                require(entry['live_selection_verified'] is False, 'unsupported audited live-selection claim')
                base_fdts.append({'image': image['name'], 'audit_entry': extracted, 'input': rec, 'facts': fdt_facts(content)})
    require(len(base_fdts) == 3, 'expected three retained base FDTs')
    tools = [retain(name, 'tools/' + Path(name).name)[0] for name in TOOL_FILES]
    require(len(files) + 1 <= MAX_FILES and sum(map(len, files.values())) <= MAX_TOTAL, 'trace bundle exceeds limits')
    report = {
        'schema_version': 1, 'kind': 'retained_a51_source_trace',
        'scope': 'source_and_retained_image_declarations_only', 'created': created,
        'specification': {'copy': 'specification.json', 'size': len(spec_content), 'sha256': sha256(spec_content)},
        'boot_audit': boot_record,
        'checkout': {'path': spec['source_root'], 'git_metadata_present': (source_root / '.git').exists(),
                     'lineage_is_recorded_not_verified_git_checkout': True},
        'lineage': {'input': inputs['repack-validation.json'][0], 'kernel_source': url, 'recorded_commit': spec['lineage_commit']},
        'configuration': {'input': inputs['kernel.config'][0], 'facts': config_facts(inputs['kernel.config'][1], spec['config_symbols'])},
        'sources': sources, 'base_fdts': base_fdts, 'tools': tools,
        'counts': {'source_files': len(sources), 'excerpts': sum(len(s['excerpts']) for s in sources),
                   'base_fdts': len(base_fdts), 'config_symbols': len(spec['config_symbols']),
                   'tool_scripts': len(tools), 'indexed_files': len(files) + 1},
        **{key: False for key in FALSE_FLAGS},
    }
    files['report.json'] = json_bytes(report)
    require(len(files['report.json']) <= MAX_JSON, 'trace report exceeds byte limit')
    require(sum(map(len, files.values())) <= MAX_TOTAL, 'trace report exceeds total byte limit')
    return report, files


def make_index(files):
    require(0 < len(files) <= MAX_FILES, 'invalid index file count')
    return {'schema_version': 1, 'files': [
        {'path': path, 'size': len(content), 'sha256': sha256(content)} for path, content in sorted(files.items())
    ]}


def verify_trace(path, project=PROJECT):
    require(path.name == 'report.json', 'trace report must be named report.json')
    folder = path.parent.resolve()
    index = decode_json(bounded_read(folder / 'index.json', MAX_JSON))
    require(isinstance(index, dict) and set(index) == {'schema_version', 'files'}
            and type(index['schema_version']) is int and index['schema_version'] == 1, 'invalid trace index')
    records = index['files']
    require(isinstance(records, list) and 0 < len(records) <= MAX_FILES, 'invalid index file count')
    seen, observed, total = set(), {}, 0
    for rec in records:
        require(isinstance(rec, dict) and set(rec) == {'path', 'size', 'sha256'}, 'invalid index record')
        name = relative_path(rec['path'])
        require(name not in seen and name != 'index.json', 'duplicate/self-referential index path')
        seen.add(name)
        require(type(rec['size']) is int and 0 <= rec['size'] <= MAX_FILE, 'invalid indexed size')
        require(isinstance(rec['sha256'], str) and re.fullmatch(r'[0-9a-f]{64}', rec['sha256']), 'invalid indexed hash')
        total += rec['size']
        require(total <= MAX_TOTAL, 'indexed total exceeds byte limit')
        content = bounded_read(contained(folder, name), retained_limit(name))
        require(len(content) == rec['size'] and sha256(content) == rec['sha256'], 'indexed trace file changed: ' + name)
        observed[name] = content
    actual = {p.relative_to(folder).as_posix() for p in folder.rglob('*') if p.is_file() and p != folder / 'index.json'}
    require(actual == seen, 'missing or unindexed trace files')
    require({'report.json', 'specification.json'} <= seen, 'missing indexed trace report/specification')
    report = decode_json(observed['report.json'])
    require(isinstance(report, dict), 'invalid trace report')
    require(all(report.get(key) is False for key in FALSE_FLAGS), 'unsupported runtime/device claim')
    expected, files = collect(observed['specification.json'], report.get('created'), project)
    require(same_json(report, expected), 'trace report differs from original-byte reconstruction')
    require(same_json(index, make_index(files)), 'trace index differs from reconstructed file set')
    require(observed == files, 'retained trace bytes differ from reconstructed originals/excerpts')
    print('Verified source trace:', expected['counts'])
    print('Source declarations only; device/placement/log-retrieval/return flags remain false')
    return expected


def capture_trace(spec_path, folder, project=PROJECT):
    require(folder.resolve().is_relative_to(project.resolve()), 'capture folder must stay inside project')
    require(not folder.exists(), 'trace capture folder already exists')
    now = dt.datetime.now(dt.timezone.utc)
    created = {'utc': now.isoformat(), 'ist': now.astimezone(IST).isoformat()}
    report, files = collect(bounded_read(spec_path, MAX_JSON), created, project)
    folder.mkdir(parents=True, exist_ok=False)
    for name, content in files.items():
        target = contained(folder, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    (folder / 'index.json').write_bytes(json_bytes(make_index(files)))
    verify_trace(folder / 'report.json', project)
    return report
