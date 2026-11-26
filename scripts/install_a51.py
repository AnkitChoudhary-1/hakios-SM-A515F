"""Owner-specific A51 installer. The default --check action is read-only.

Partition writes occur ONLY with an explicit --install-* or --restore-* action.
No repartitioning, disk-wide writes, Android boot writes, or automatic reboot.
Run under Windows Python from the prepared outputs directory.
"""
import argparse
import hashlib
import json
import pathlib
import re
import shlex
import subprocess
from datetime import datetime, timezone
from backup_a51 import ADB, SERIAL, DISK_BYTES, verify_gpt

OUT = pathlib.Path(__file__).resolve().parents[1]
BACKUPS = OUT / 'backups' / SERIAL
SYSTEM_HASH = '9efb156f417e32b6f92d709af33c0e8e584693c3fbd29eaf139b57eee3735560'
SYSTEM_BYTES = 8365539328
DARWIN_BYTES = 10739494912
DARWIN_GUID = '61c92daa-7d57-4a37-8f71-17964f2ddebd'


def event(name, **details):
    record = {'at_utc': datetime.now(timezone.utc).isoformat(), 'event': name, **details}
    with (OUT / 'installation-events.jsonl').open('a', encoding='utf-8') as f:
        f.write(json.dumps(record) + '\n')


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        while b := f.read(8 * 1024 * 1024):
            h.update(b)
    return h.hexdigest()


def shell(command, binary=False, timeout=180):
    if not hasattr(shell, 'needs_su'):
        check_root = subprocess.run([ADB, '-s', SERIAL, 'exec-out', 'id'],
                                    stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=10)
        shell.needs_su = not check_root.stdout.startswith('uid=0(')
    adb_cmd = ('su -c ' + shlex.quote(command)) if shell.needs_su else command
    result = subprocess.run([ADB, '-s', SERIAL, 'exec-out' if binary else 'shell', adb_cmd],
                            stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f'ADB command failed: {result.stderr.decode(errors="replace")}')
    return result.stdout if binary else result.stdout.decode().strip()


def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)


def remote_digest(path, size=None):
    if size is None:
        command = 'sha256sum ' + shlex.quote(path)
    else:
        # dd's exit code is checked independently by exact byte read-back during
        # writes; the expected SHA also rejects truncated reads here.
        command = f'dd if={shlex.quote(path)} bs=1048576 count={size} iflag=count_bytes 2>/dev/null | sha256sum'
    value = shell(command, timeout=1200).split()[0]
    require(re.fullmatch('[0-9a-f]{64}', value), 'Invalid phone checksum response')
    return value


def backup_checks():
    manifest = json.loads((BACKUPS / 'backup-manifest.json').read_text())
    require(manifest['serial'] == SERIAL and manifest['gpt_verified'], 'Backup identity is invalid')
    for item in manifest['backups']:
        path = BACKUPS / pathlib.Path(item['file']).name
        require(path.stat().st_size == item['bytes'] and digest(path) == item['sha256'],
                f'Local backup is damaged: {path.name}')
    darwin = json.loads((BACKUPS / 'darwin-backup-manifest.json').read_text())
    path = BACKUPS / 'darwin-before.img'
    require(path.stat().st_size == DARWIN_BYTES == darwin['bytes'], 'Darwin backup is incomplete')
    require(darwin['phone_sha256'] == darwin['sha256'] == digest(path), 'Darwin backup checksum mismatch')


def phone_checks():
    require(shell('id').startswith('uid=0('), 'Root is unavailable')
    for prop, expected in [('ro.product.model', ('SM-A515F',)),
                           ('ro.board.platform', ('universal9611', 'exynos9611')),
                           ('ro.boot.bootloader', ('A515FXXU8HWI5',))]:
        val = shell('getprop ' + prop)
        require(val in expected, f'Phone identity differs: {prop} (got {val})')
    head = shell('dd if=/dev/block/sda bs=4096 count=256 2>/dev/null', binary=True)
    tail = shell(f'dd if=/dev/block/sda bs=4096 skip={DISK_BYTES//4096-256} count=256 2>/dev/null', binary=True)
    require(head == (BACKUPS / 'gpt-head-before.bin').read_bytes() and
            tail == (BACKUPS / 'gpt-tail-before.bin').read_bytes(), 'GPT differs from the verified backup')
    gpt = verify_gpt(head, tail)
    part = {x['name']: x for x in gpt['partitions']}
    require((part['darwin']['guid'], part['darwin']['first_lba'], part['darwin']['last_lba'], part['darwin']['bytes']) ==
            (DARWIN_GUID, 28614144, 31236090, DARWIN_BYTES), 'Darwin partition identity differs')
    require(part['recovery']['bytes'] == 71106560, 'Recovery partition capacity differs')
    require(shell('readlink -f /dev/block/by-name/darwin') == '/dev/block/sda33', 'Darwin alias differs')
    require(shell('readlink -f /dev/block/by-name/recovery') == '/dev/block/sda13', 'Recovery alias differs')
    require(shell('blockdev --getsize64 /dev/block/by-name/darwin') == str(DARWIN_BYTES), 'Darwin size differs')
    mounts = shell('cat /proc/mounts')
    require(not any('/dev/block/sda33' in x or '/dev/block/by-name/darwin' in x or
                    '/dev/block/sda13' in x or '/dev/block/by-name/recovery' in x for x in mounts.splitlines()),
            'A target partition is mounted')
    require(remote_digest('/dev/block/by-name/boot') ==
            'eb30609a62999e3282ac81e0a5e56411ef12ec1a39c107171bf3e01209c7cb67',
            'Android boot partition differs from its original verified backup')


def write_partition(source, target, expected_hash, expected_size):
    require(source.stat().st_size == expected_size and digest(source) == expected_hash,
            'Source image size or checksum is invalid')
    require(target in ('darwin', 'recovery'), 'Unsupported partition')
    require(expected_size <= (DARWIN_BYTES if target == 'darwin' else 71106560), 'Image exceeds partition')
    # Fixed directory and partition aliases; caller-controlled shell text is never accepted.
    staging_dir = '/tmp' if shell('test -d /tmp && echo yes') == 'yes' else '/data/local/tmp'
    remote = f'{staging_dir}/hakios-a51-{target}.img'
    space = shell(f'df -k {staging_dir}').splitlines()[-1].split()
    require(int(space[3]) * 1024 >= expected_size + 1024**3, 'Insufficient phone staging space')
    print(f'Staging {source.name} in phone userdata...', flush=True)
    subprocess.run([ADB, '-s', SERIAL, 'push', str(source), remote], check=True)
    print('Verifying the staged image checksum before writing...', flush=True)
    require(shell('stat -c %s ' + remote) == str(expected_size), 'Staged file size differs')
    require(remote_digest(remote) == expected_hash, 'Staged checksum mismatch; no partition write performed')
    phone_checks()  # Recheck device and GPT immediately before the write.
    event('partition-write-started', serial=SERIAL, partition=target,
          source=source.name, bytes=expected_size, sha256=expected_hash)
    print(f'Writing {expected_size:,} bytes to {target} on {SERIAL}...', flush=True)
    result = shell(f'set -e; dd if={remote} of=/dev/block/by-name/{target} '
                   'bs=1048576 conv=fsync,notrunc; sync', timeout=1200)
    print(result, flush=True)
    print('Verifying partition read-back...', flush=True)
    require(remote_digest('/dev/block/by-name/' + target, expected_size) == expected_hash,
            'Partition read-back mismatch; stop and restore using the saved backup')
    event('partition-readback-verified', serial=SERIAL, partition=target,
          bytes=expected_size, sha256=expected_hash)
    # Changes to recovery or darwin do not affect the GPT and Android boot checksum.
    phone_checks()
    shell('rm -f ' + remote)
    return {'serial': SERIAL, 'partition': target, 'bytes_written': expected_size,
            'source': source.name, 'sha256': expected_hash, 'readback_verified': True}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    group = ap.add_mutually_exclusive_group()
    group.add_argument('--check', action='store_true')
    group.add_argument('--install-system', action='store_true')
    group.add_argument('--install-recovery', action='store_true')
    group.add_argument('--restore-recovery', action='store_true')
    group.add_argument('--restore-darwin', action='store_true')
    ap.add_argument('--package-dir', type=pathlib.Path, default=OUT,
                    help='Recovery package directory; backups and system remain in original outputs')
    args = ap.parse_args()
    package_dir = args.package_dir.resolve()
    print('Verifying host backups and connected phone. No partition writes yet.', flush=True)
    backup_checks()
    print('Local backups verified; checking live phone identity and GPT...', flush=True)
    phone_checks()
    report = {'serial': SERIAL, 'backups_verified': True, 'live_gpt_verified': True,
              'phone_partitions_written': False}
    if args.install_system:
        report = write_partition(OUT / 'a51-ios16.5-system.apfs', 'darwin', SYSTEM_HASH, SYSTEM_BYTES)
    elif args.install_recovery:
        # If loader USB startup succeeds, this image waits for fastboot oem run.
        # USB startup failure falls through to the embedded timed kernel attempt.
        packages = json.loads((package_dir / 'boot-package-manifest.json').read_text(encoding='utf-8'))
        image = next(x for x in packages['packages'] if x['mode'] == 'diagnostic')
        require(remote_digest('/dev/block/by-name/recovery') ==
                '12412e2008d950260cda627ac7a6b8eac954b49ef9db5573a297f67e4fc85999',
                'Current recovery differs from its saved backup; review before replacing it')
        require(remote_digest('/dev/block/by-name/darwin', SYSTEM_BYTES) == SYSTEM_HASH,
                'Install and verify the prepared system region before recovery')
        report = write_partition(package_dir / image['image'], 'recovery', image['sha256'], image['bytes'])
    elif args.restore_recovery:
        report = write_partition(BACKUPS / 'recovery-before.img', 'recovery',
                                 '12412e2008d950260cda627ac7a6b8eac954b49ef9db5573a297f67e4fc85999', 71106560)
    elif args.restore_darwin:
        saved = json.loads((BACKUPS / 'darwin-backup-manifest.json').read_text())
        report = write_partition(BACKUPS / 'darwin-before.img', 'darwin', saved['sha256'], DARWIN_BYTES)
    else:
        system = OUT / 'a51-ios16.5-system.apfs'
        require(system.stat().st_size == SYSTEM_BYTES and digest(system) == SYSTEM_HASH,
                'Prepared system image differs')
        packages = json.loads((package_dir / 'boot-package-manifest.json').read_text(encoding='utf-8'))
        for package in packages['packages']:
            image = package_dir / package['image']
            require(image.stat().st_size == package['bytes'] and digest(image) == package['sha256'],
                    'Prepared recovery image differs')
        require(remote_digest('/dev/block/by-name/recovery') ==
                '12412e2008d950260cda627ac7a6b8eac954b49ef9db5573a297f67e4fc85999',
                'Current recovery differs from its saved backup')
        print('Read-only checks passed. Installation requires an explicit --install-* action.', flush=True)
    report['completed_at_utc'] = datetime.now(timezone.utc).isoformat()
    report['action'] = next((name for name, value in vars(args).items()
                             if name != 'package_dir' and value), 'check')
    report['package_directory'] = str(package_dir)
    report['phone_partitions_written'] = report.get('readback_verified', False)
    with (OUT / 'device-action-history.jsonl').open('a', encoding='utf-8') as f:
        f.write(json.dumps(report) + '\n')
    (OUT / 'last-device-check.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
