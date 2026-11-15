#!/usr/bin/env python3
"""Cross-check retained FDT headers/nodes and audit properties with WSL libfdt.

No overlays are applied. Commands and raw output are retained under Phase 2.
An existing result can be checksum-verified without repeating the tool calls.
"""
import argparse
import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from boot_formats import parse_fdt, sha256

spec = importlib.util.spec_from_file_location('boot_audit', Path(__file__).with_name('audit-boot-inputs.py'))
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
PROJECT = audit.PROJECT
PROPERTIES = {'#address-cells', '#size-cells', 'reg', 'size', 'alignment', 'alloc-ranges',
              'ranges', 'status', 'device_type', 'no-map', 'reusable', 'model', 'compatible',
              'dtb-hw_rev', 'dtb-hw_rev_end', 'dtbo-hw_rev', 'dtbo-hw_rev_end',
              'target', 'target-path', 'bootargs', 'bootargs_ext', 'stdout-path'}


def save_index(folder):
    records = [dict(audit.record(p)[0], path=p.relative_to(folder).as_posix())
               for p in sorted(folder.rglob('*')) if p.is_file() and p != folder / 'index.json']
    (folder / 'index.json').write_text(json.dumps({'schema_version': 1, 'files': records}, indent=2) + '\n',
                                      encoding='utf-8')


def verify_result(path):
    folder = path.parent
    index = audit.load(folder / 'index.json')
    audit.require(index['schema_version'] == 1, 'unsupported libfdt index')
    seen = set()
    for rec in index['files']:
        audit.require(rec['path'] not in seen and rec['path'] != 'index.json', 'invalid libfdt index entry')
        seen.add(rec['path'])
        content = audit.contained(folder, rec['path']).read_bytes()
        audit.require(len(content) == rec['size'] and sha256(content) == rec['sha256'],
                      'libfdt evidence changed: ' + rec['path'])
    actual = {p.relative_to(folder).as_posix() for p in folder.rglob('*') if p.is_file() and p != folder / 'index.json'}
    audit.require(actual == seen and 'result.json' in seen and path.name == 'result.json', 'unindexed libfdt evidence')
    result = audit.load(path)
    audit.require(result['schema_version'] == 1 and result['status'] == 'passed'
                  and result['phone_writes'] is False and result['phase_2_device_gate_passed'] is False,
                  'unsuccessful or unsupported libfdt result')
    report_path = audit.contained(PROJECT, result['report'])
    audit.require(sha256(report_path.read_bytes()) == result['report_sha256'], 'libfdt source report changed')
    report = audit.load(report_path)
    entries = [e for i in report['images'] for t in i['tables'] for e in t['entries']]
    audit.require(len(result['checks']) == len(entries) == result['counts']['fdt_blobs'], 'libfdt blob count differs')
    audit.require(all(c['status'] == 'passed' for c in result['checks'])
                  and all(c['exit_code'] == 0 for c in result['commands']), 'failed libfdt check or command')
    for check, entry in zip(result['checks'], entries):
        blob_path = audit.contained(report_path.parent, entry['extracted_blob'])
        audit.require(check['blob_sha256'] == entry['sha256'] == sha256(blob_path.read_bytes()),
                      'libfdt source blob changed')
    print('Verified libfdt evidence:', len(seen), 'files;', len(entries), 'FDT blobs')


def crosscheck(report_path):
    audit.require(os.name == 'posix', 'run the libfdt cross-check in A51-KernelBuilder WSL')
    audit.verify_report(report_path)
    report = audit.load(report_path)
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder = PROJECT / 'evidence/phase-2/libfdt' / stamp
    (folder / 'commands').mkdir(parents=True, exist_ok=False)
    result = {'schema_version': 1, 'captured_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
              'status': 'running', 'report': report_path.relative_to(PROJECT).as_posix(),
              'report_sha256': sha256(report_path.read_bytes()), 'phone_writes': False,
              'phase_2_device_gate_passed': False, 'tools': [], 'commands': [], 'checks': [],
              'limits': 'Independent libfdt reads of headers, node counts, root children and selected audit properties. '
                        'No overlay application, live FDT, memory allocation or device execution.'}

    def run(argv):
        number = str(len(result['commands'])).zfill(4)
        rec = {'argv': [str(a) for a in argv], 'started_utc': dt.datetime.now(dt.timezone.utc).isoformat()}
        proc = subprocess.run(rec['argv'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, check=False)
        rec.update(exit_code=proc.returncode, finished_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                   stdout='commands/' + number + '-stdout.txt', stderr='commands/' + number + '-stderr.txt')
        (folder / rec['stdout']).write_bytes(proc.stdout)
        (folder / rec['stderr']).write_bytes(proc.stderr)
        result['commands'].append(rec)
        audit.require(proc.returncode == 0, 'libfdt command failed: ' + ' '.join(rec['argv']))
        return proc.stdout.decode('utf-8')

    try:
        paths = {}
        for name in ('fdtget', 'fdtdump'):
            executable = shutil.which(name)
            audit.require(executable, 'missing host tool: ' + name)
            paths[name] = executable
            rec, _ = audit.record(Path(executable).resolve(), name)
            rec['version'] = run([executable, '-V']).strip()
            result['tools'].append(rec)
        run(['dpkg-query', '-W', '-f', '${Package}\t${Version}\n', 'device-tree-compiler', 'libfdt1'])
        for image in report['images']:
            for table in image['tables']:
                for entry in table['entries']:
                    blob_path = audit.contained(report_path.parent, entry['extracted_blob'])
                    tree = parse_fdt(blob_path.read_bytes())
                    dump = run([paths['fdtdump'], blob_path])
                    header = {k: int(v, 0) for k, v in re.findall(
                        r'^//\s*([a-z0-9_]+):\s*(0x[0-9a-fA-F]+|[0-9]+)', dump, re.MULTILINE)}
                    audit.require(header == tree.header, 'fdtdump header mismatch: ' + str(blob_path))
                    node_count = len(re.findall(r'^[ \t]*[^\s=;]+[ \t]*\{[ \t]*$', dump, re.MULTILINE))
                    audit.require(node_count == len(tree.nodes), 'fdtdump node count mismatch: ' + str(blob_path))
                    children = run([paths['fdtget'], '-l', blob_path, '/']).splitlines()
                    expected_children = {p[1:] for p in tree.nodes if p != '/' and p.count('/') == 1}
                    audit.require(set(children) == expected_children, 'fdtget root children mismatch')
                    selected = {'/'}
                    for node in tree.nodes:
                        if node == '/chosen' or node.startswith('/reserved-memory') or (
                            node.count('/') == 1 and (node.rsplit('/', 1)[-1].startswith('memory')
                                                     or tree.nodes[node].get('device_type') == b'memory\0')):
                            selected.add(node)
                    for fragment in entry['summary']['overlay_fragments']:
                        selected.add(fragment['node'])
                        selected.add(fragment['node'].rsplit('/', 1)[0])
                    pairs = [(node, name) for node in sorted(selected) for name in sorted(tree.nodes[node])
                             if name in PROPERTIES]
                    values = run([paths['fdtget'], '-t', 'bx', blob_path,
                                  *[value for pair in pairs for value in pair]]).splitlines() if pairs else []
                    audit.require(len(values) == len(pairs), 'fdtget returned wrong property count')
                    independent = []
                    for (node, name), value in zip(pairs, values):
                        raw = bytes(int(byte, 16) for byte in value.split())
                        audit.require(raw == tree.nodes[node][name], 'fdtget property mismatch: ' + node + ':' + name)
                        independent.append({'node': node, 'property': name, 'hex': raw.hex()})
                    result['checks'].append({'image': image['name'], 'section': table['section'],
                        'entry': entry['index'], 'blob': entry['extracted_blob'], 'blob_sha256': entry['sha256'],
                        'header': header, 'node_count': node_count, 'root_children': children,
                        'properties': independent, 'status': 'passed'})
                    print('libfdt:', image['name'], table['section'], entry['index'], node_count, 'nodes;', len(pairs), 'properties')
        result['counts'] = {'fdt_blobs': len(result['checks']),
                            'properties': sum(len(c['properties']) for c in result['checks']),
                            'commands': len(result['commands'])}
        result['status'] = 'passed'
    except Exception as exc:
        result.update(status='failed', error=str(exc))
        raise
    finally:
        result['finished_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
        (folder / 'result.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
        save_index(folder)
    verify_result(folder / 'result.json')
    current = {'schema_version': 1, 'result': (folder / 'result.json').relative_to(PROJECT).as_posix(),
               'sha256': sha256((folder / 'result.json').read_bytes()), 'report': result['report'],
               'report_sha256': result['report_sha256'], 'counts': result['counts'], 'status': 'passed_host_crosscheck',
               'phone_writes': False, 'phase_2_device_gate_passed': False}
    (PROJECT / 'manifests/libfdt-check-current.json').write_text(json.dumps(current, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(current, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--report', help='project-relative verified boot report; default uses boot-audit-current.json')
    group.add_argument('--verify-result', help='project-relative existing result to checksum-verify')
    args = parser.parse_args()
    if args.verify_result:
        verify_result(audit.contained(PROJECT, args.verify_result))
    elif args.report:
        crosscheck(audit.contained(PROJECT, args.report))
    else:
        current = audit.load(PROJECT / 'manifests/boot-audit-current.json')
        path = audit.contained(PROJECT, current['report'])
        audit.require(sha256(path.read_bytes()) == current['sha256'], 'current boot report differs from manifest')
        crosscheck(path)


if __name__ == '__main__':
    main()
