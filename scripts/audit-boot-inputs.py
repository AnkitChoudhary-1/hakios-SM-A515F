#!/usr/bin/env python3
"""Audit hash-locked retained A51 images and keep an append-only host report.

Run through run.py on Windows or WSL. No ADB, image repacking, or device writes.
"""
import argparse
import datetime as dt
import json
import os
from pathlib import Path, PureWindowsPath

from boot_formats import parse_arm64_image, parse_boot, parse_dt_table, sha256, summarize_fdt

PROJECT = Path(__file__).resolve().parents[1]
WORKSPACE = PROJECT.parent
INVENTORY = PROJECT / 'manifests/inventory-snapshots/20261110T162732057411Z.json'
LINUX_COMMIT = '468ab8343364e4d3a267e670fa6a22fd4197a805'
IMAGE_NAMES = {
    'a51-pixelos-original-boot.img': 'original-boot',
    'a51-pixelos-original-dtbo.img': 'original-dtbo',
    'a51-twrp-original-recovery.img': 'recovery',
    'A51-PixelOS-Everline-KernelSU-Next-boot.img': 'installed-android-boot',
}
LINUX_REFERENCES = [
    'Documentation/arm64/booting.txt', 'arch/arm64/kernel/head.S',
    'arch/arm64/boot/dts/Makefile', 'arch/arm64/boot/dts/exynos/exynos9610.dts',
    'drivers/of/of_reserved_mem.c',
    'arch/arm64/boot/dts/exynos/exynos9610-rmem.dtsi',
    'arch/arm64/boot/dts/samsung/exynos9611-a51_common.dtsi',
    'arch/arm64/boot/dts/samsung/exynos9611-a51_eur_open_00.dts',
    'arch/arm64/boot/dts/samsung/exynos9611-a51_eur_open_01.dts',
    'arch/arm64/boot/dts/samsung/exynos9611-a51_eur_open_03.dts',
    'arch/arm64/boot/dts/samsung/exynos9611-a51_eur_open_07.dts',
]


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def load(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def input_path(value):
    if len(value) > 2 and value[1:3] in (':\\', ':/'):
        if os.name == 'nt':
            return Path(value)
        win = PureWindowsPath(value)
        return Path('/mnt') / win.drive[0].lower() / Path(*win.parts[1:])
    if value.startswith('/opt/') and os.name == 'nt':
        return Path(r'\\wsl.localhost\A51-KernelBuilder') / value.lstrip('/')
    return Path(value)


def record(path, label=None):
    content = path.read_bytes()
    return {'path': str(path), 'size': len(content), 'sha256': sha256(content),
            **({'label': label} if label else {})}, content


def contained(root, relative):
    path = (root / relative).resolve()
    require(path.is_relative_to(root.resolve()), 'evidence path escapes its directory: ' + relative)
    return path


def reported_revision(inventory):
    queries = [q for q in inventory['device_queries'] if q['argv'][-1] == 'ro.boot.revision']
    require(len(queries) == 1 and queries[0]['exit_code'] == 0, 'missing retained boot revision')
    return int(queries[0]['output'].strip())


def inspect_image(pinned, revision):
    """Bind every extracted blob and summary to the hash-checked original bytes."""
    content = input_path(pinned['path']).read_bytes()
    require(len(content) == pinned['size'] and sha256(content) == pinned['sha256'],
            'retained image differs from Phase 1 pin: ' + pinned['path'])
    name = IMAGE_NAMES[PureWindowsPath(pinned['path']).name]
    image = {'name': name, 'input': pinned, 'tables': []}
    generated = {}
    if content[:8] == b'ANDROID!':
        require(name != 'original-dtbo', 'DTBO input unexpectedly contains a boot image')
        image['boot_header'] = parse_boot(content)
        sections = image['boot_header']['sections']
        section = sections['kernel']
        image['arm64_image'] = parse_arm64_image(content[section['offset']:section['offset'] + section['size']])
        containers = [(key, sections[key]) for key in ('dtb', 'recovery_dtbo') if sections[key]['size']]
    else:
        require(name == 'original-dtbo', 'unexpected image container')
        containers = [('dtbo', {'offset': 0, 'size': len(content)})]
    for kind, section in containers:
        data = content[section['offset']:section['offset'] + section['size']]
        header, entries = parse_dt_table(data)
        table = {'section': kind, 'file_offset': section['offset'], 'section_size': section['size'],
                 'section_sha256': sha256(data), 'header': header, 'entries': []}
        for entry in entries:
            blob = entry.pop('blob')
            summary = summarize_fdt(entry.pop('tree'))
            relative = 'dt/' + name + '-' + kind + '-' + str(entry['index']).zfill(2) + '.dtb'
            generated[relative] = blob
            entry.update(extracted_blob=relative, sha256=sha256(blob), summary=summary,
                         absolute_file_offset=section['offset'] + entry['offset'])
            props = summary['hardware_revision_properties']
            prefix = 'dtbo' if 'dtbo-hw_rev' in props else 'dtb'
            low, high = props.get(prefix + '-hw_rev'), props.get(prefix + '-hw_rev_end')
            entry['matches_reported_revision'] = low <= revision <= high if low is not None and high is not None else None
            entry['live_selection_verified'] = False
            table['entries'].append(entry)
        image['tables'].append(table)
    return image, generated


def counts_for(report):
    return {'images': len(report['images']), 'dt_tables': sum(len(i['tables']) for i in report['images']),
            'fdt_blobs': sum(len(t['entries']) for i in report['images'] for t in i['tables']),
            'references': len(report['references'])}


def audit():
    inventory = load(INVENTORY)
    inputs = inventory['retained_inputs']
    selected = [r for r in inputs if PureWindowsPath(r['path']).name in IMAGE_NAMES]
    require(len(selected) == 4, 'expected four pinned retained images')
    revision = reported_revision(inventory)
    report = {'schema_version': 1, 'captured_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
              'scope': 'host audit of retained images and source; no live device query or execution',
              'phone_writes': False, 'phase_2_device_gate_passed': False,
              'inventory': record(INVENTORY)[0], 'reported_boot_revision': revision,
              'reported_revision_is_verified_pcb_identity': False,
              'images': [], 'references': [],
              'linux_source_provenance': {'recorded_upstream_commit': LINUX_COMMIT,
                  'url': 'https://github.com/Parbindar7/android_kernel_samsung_universal9611/commit/' + LINUX_COMMIT,
                  'status': 'existing Android source with local adaptations; retained file hashes pin the inspected bytes'},
              'limits': ['No overlays applied and no live FDT/bootloader fixups captured.',
                        'Static reservation gaps exclude unknown dynamic, secure and bootloader allocations.',
                        'Header load addresses are metadata, not verified Samsung entry addresses.',
                        'No loader, XNU phone execution, log retrieval or return procedure is proven.']}
    generated = {}
    for pinned in selected:
        image, blobs = inspect_image(pinned, revision)
        generated.update(blobs)
        report['images'].append(image)
    for pinned in inputs:
        name = PureWindowsPath(pinned['path']).name
        if name in ('kernel.config', 'repack-validation.json'):
            source = input_path(pinned['path'])
            content = source.read_bytes()
            require(len(content) == pinned['size'] and sha256(content) == pinned['sha256'], 'retained source record changed')
            relative = 'references/' + name
            generated[relative] = content
            report['references'].append(dict(pinned, retained_copy=relative))
            if name == 'repack-validation.json':
                require(LINUX_COMMIT in json.loads(content)['kernel_source'], 'Android source lineage changed')
    for relative in LINUX_REFERENCES:
        logical = '/opt/a51-everline/src/' + relative
        rec, content = record(input_path(logical))
        rec['path'] = logical
        copy_path = 'references/linux/' + relative
        generated[copy_path] = content
        report['references'].append(dict(rec, retained_copy=copy_path))
    report['counts'] = counts_for(report)
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder = PROJECT / 'evidence/phase-2/boot-audit' / stamp
    folder.mkdir(parents=True, exist_ok=False)
    for relative, content in generated.items():
        path = contained(folder, relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    (folder / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    indexed = [dict(record(p)[0], path=p.relative_to(folder).as_posix())
               for p in sorted(folder.rglob('*')) if p.is_file()]
    (folder / 'index.json').write_text(json.dumps({'schema_version': 1, 'files': indexed,
        'limits': 'Local integrity against this index; original images remain outside the bundle.'}, indent=2) + '\n', encoding='utf-8')
    verify_report(folder / 'report.json')
    current = {'schema_version': 1, 'captured_utc': report['captured_utc'],
               'report': (folder / 'report.json').relative_to(PROJECT).as_posix(),
               'sha256': sha256((folder / 'report.json').read_bytes()), 'counts': report['counts'],
               'status': 'verified_host_structure_live_entry_memory_selection_and_return_unknown',
               'phone_writes': False, 'phase_2_device_gate_passed': False}
    (PROJECT / 'manifests/boot-audit-current.json').write_text(json.dumps(current, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(current, indent=2))
    for image in report['images']:
        for table in image['tables']:
            for entry in table['entries']:
                summary = entry['summary']
                print(image['name'], table['section'], entry['index'],
                      'memory_bytes=' + str(summary['declared_memory_bytes']),
                      'revision=' + str(summary['hardware_revision_properties']),
                      'matches_reported=' + str(entry['matches_reported_revision']))


def verify_report(path):
    folder = path.parent
    index = load(folder / 'index.json')
    require(index['schema_version'] == 1 and index['files'], 'invalid audit index')
    seen = set()
    for rec in index['files']:
        require(rec['path'] not in seen and rec['path'] != 'index.json', 'duplicate/self-referential audit entry')
        seen.add(rec['path'])
        target = contained(folder, rec['path'])
        content = target.read_bytes()
        require(len(content) == rec['size'] and sha256(content) == rec['sha256'], 'audit file changed: ' + rec['path'])
    require('report.json' in seen and path.name == 'report.json', 'audit report is not indexed')
    actual = {p.relative_to(folder).as_posix() for p in folder.rglob('*') if p.is_file() and p != folder / 'index.json'}
    require(actual == seen, 'audit directory has missing or unindexed files')
    report = load(path)
    require(report['schema_version'] == 1, 'unsupported audit schema')
    require(report['phone_writes'] is False and report['phase_2_device_gate_passed'] is False
            and report['reported_revision_is_verified_pcb_identity'] is False, 'unsupported device claim')
    originals = [report['inventory']] + [i['input'] for i in report['images']] + report['references']
    expected_files = {'report.json'}
    for rec in [report['inventory']] + report['references']:
        content = input_path(rec['path']).read_bytes()
        require(len(content) == rec['size'] and sha256(content) == rec['sha256'], 'original audit input changed: ' + rec['path'])
        if 'retained_copy' in rec:
            require(rec['retained_copy'] in seen, 'unindexed reference copy')
            require(sha256(contained(folder, rec['retained_copy']).read_bytes()) == rec['sha256'], 'reference copy differs')
            expected_files.add(rec['retained_copy'])
    inventory = load(input_path(report['inventory']['path']))
    revision = reported_revision(inventory)
    require(revision == report['reported_boot_revision'], 'reported revision differs from retained inventory')
    pinned_images = {r['path']: r for r in inventory['retained_inputs']
                     if PureWindowsPath(r['path']).name in IMAGE_NAMES}
    require(len(report['images']) == 4 and len(pinned_images) == 4, 'expected four pinned retained images')
    names = set()
    blobs = 0
    for image in report['images']:
        require(image['name'] not in names, 'duplicate audited image')
        names.add(image['name'])
        require(pinned_images.get(image['input']['path']) == image['input'], 'image pin differs from retained inventory')
        expected_image, expected_blobs = inspect_image(image['input'], revision)
        require(expected_image == image, 'stored image/DT summary differs from original input')
        for table in image['tables']:
            for entry in table['entries']:
                require(entry['extracted_blob'] in seen, 'unindexed DT blob')
                blob = contained(folder, entry['extracted_blob']).read_bytes()
                require(blob == expected_blobs[entry['extracted_blob']], 'extracted DT blob differs from original image')
                expected_files.add(entry['extracted_blob'])
                blobs += 1
    require(names == set(IMAGE_NAMES.values()), 'audited image identities disagree')
    require(report['counts'] == counts_for(report), 'audit counts disagree')
    require(seen == expected_files, 'audit index contains unexpected evidence')
    print('Verified audit:', len(seen), 'indexed files;', len(originals), 'original hashes;', blobs, 'FDT summaries')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-report', help='project-relative report to verify without creating new evidence')
    args = parser.parse_args()
    if args.verify_report:
        verify_report(contained(PROJECT, args.verify_report))
    else:
        audit()


if __name__ == '__main__':
    main()
