"""Extract the owner's IPSW and prepare the published flash layout. Local writes only."""
import hashlib
import json
import pathlib
import shutil
import struct
import subprocess
import zipfile

REPO = pathlib.Path('/opt/a51-hakios/upstream-a51/hakios')
IPSW = pathlib.Path('/mnt/d/iPhone10,3,iPhone10,6_16.5_20F66_Restore.ipsw')
SCRATCH = pathlib.Path('/mnt/d/A51-iOS16.5-build/work/ipsw-images')
OUT = pathlib.Path('/mnt/c/Users/Ankit/Documents/Codex/2026-11-21/hi-2/outputs')
MEMBERS = ['096-04088-077.dmg', '096-04666-078.dmg', '096-03536-083.dmg']
EXPECTED_PREFIXES = ['9f430a58', '2279bf44', '6b9d1f09']
TOTAL = 2042368 * 4096


def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def apfs(path):
    with path.open('rb') as f:
        head = f.read(4096)
    if head[32:36] != b'NXSB':
        raise RuntimeError(f'{path}: missing APFS container signature')
    bs, blocks = struct.unpack_from('<IQ', head, 36)
    if bs != 4096 or bs * blocks != path.stat().st_size:
        raise RuntimeError(f'{path}: APFS size differs from file size')
    return {'block_size': bs, 'blocks': blocks, 'bytes': bs * blocks}


def main():
    SCRATCH.mkdir(parents=True, exist_ok=True)
    records = []
    with zipfile.ZipFile(IPSW) as archive:
        for member in MEMBERS:
            dest = SCRATCH / member
            info = archive.getinfo(member)
            if not dest.exists():
                print(f'Extracting {member}: {info.file_size:,} bytes', flush=True)
                partial = dest.with_suffix('.dmg.partial')
                with archive.open(member) as source, partial.open('xb') as output:
                    shutil.copyfileobj(source, output, 4 * 1024 * 1024)
                if partial.stat().st_size != info.file_size:
                    raise RuntimeError(f'Wrong extracted size: {member}')
                partial.rename(dest)
            if dest.stat().st_size != info.file_size:
                raise RuntimeError(f'Existing file has wrong size: {dest}')
            records.append({'member': member, 'source_sha256': digest(dest), 'source_bytes': info.file_size})
            print(f'Extracted {member}: {records[-1]["source_sha256"]}', flush=True)

    root = SCRATCH / 'rootfs.apfs'
    if not root.exists():
        print('Decompressing root DMG to raw APFS...', flush=True)
        partial = root.with_suffix('.apfs.partial')
        subprocess.run(['python3', str(REPO / 'tools/apfs/dmg.py'), 'extract',
                        str(SCRATCH / MEMBERS[0]), str(partial), '--apfs'], cwd=REPO, check=True)
        apfs(partial)
        partial.rename(root)
    images = [root, SCRATCH / MEMBERS[1], SCRATCH / MEMBERS[2]]
    position = 0
    for record, img, prefix in zip(records, images, EXPECTED_PREFIXES):
        record.update(apfs(img))
        record.update({'prepared_path': str(img), 'sha256': digest(img), 'offset_bytes': position,
                       'offset_blocks': position // 4096})
        if not record['sha256'].startswith(prefix):
            raise RuntimeError(f'Published checksum prefix does not match: {img}')
        position += record['bytes']
        print(f'Validated {img.name}: {record["bytes"]:,} bytes at {record["offset_blocks"]}, {record["sha256"]}', flush=True)
    if position != TOTAL:
        raise RuntimeError(f'Total differs from published layout: {position} != {TOTAL}')
    dest = OUT / 'a51-ios16.5-system.apfs'
    if dest.exists():
        raise RuntimeError(f'Refusing to overwrite {dest}')
    print(f'Assembling system region: {TOTAL:,} bytes...', flush=True)
    partial = dest.with_suffix('.apfs.partial')
    merged = hashlib.sha256()
    with partial.open('xb') as output:
        for img in images:
            with img.open('rb') as source:
                while chunk := source.read(4 * 1024 * 1024):
                    output.write(chunk)
                    merged.update(chunk)
    if partial.stat().st_size != TOTAL or digest(partial) != merged.hexdigest():
        raise RuntimeError('Assembled system image failed independent read-back verification')
    partial.rename(dest)
    manifest = {'ipsw': str(IPSW), 'components': records, 'system': {'file': dest.name, 'bytes': TOTAL,
                'blocks': TOTAL // 4096, 'sha256': merged.hexdigest()}, 'phone_partition_bytes': 10739494912,
                'fits_partition': TOTAL <= 10739494912, 'phone_writes': False}
    (OUT / 'system-layout-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest['system']), flush=True)
    print('System image complete; no phone partitions written.', flush=True)


if __name__ == '__main__':
    main()
