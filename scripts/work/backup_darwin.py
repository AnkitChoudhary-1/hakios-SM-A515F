"""Read and verify the entire existing darwin partition. No phone writes."""
import json
import shutil
import subprocess
import shlex
from backup_a51 import adb_read, remote_hash, DEST, ADB, SERIAL

size = 10739494912
dest = DEST / 'darwin-before.img'
if shutil.disk_usage(DEST).free < size + 9 * 1024**3:
    raise RuntimeError('Insufficient local space for darwin backup and prepared system image')
command = 'readlink -f /dev/block/by-name/darwin; blockdev --getsize64 /dev/block/by-name/darwin'
result = subprocess.run([ADB, '-s', SERIAL, 'shell', 'su -c ' + shlex.quote(command)],
                        capture_output=True, text=True)
if result.returncode:
    raise RuntimeError(f'Partition check failed: {result.stdout!r} {result.stderr!r}')
node = result.stdout.split()
if node != ['/dev/block/sda33', str(size)]:
    raise RuntimeError(f'Partition differs from verified geometry: {node}')
print(f'Backing up all {size:,} bytes of darwin...', flush=True)
record = adb_read('dd if=/dev/block/by-name/darwin bs=1048576 2>/dev/null', dest, size)
print('Verifying checksum independently on the phone...', flush=True)
record['phone_sha256'] = remote_hash('darwin')
if record['sha256'] != record['phone_sha256']:
    raise RuntimeError('Darwin backup checksum differs from phone')
(DEST / 'darwin-backup-manifest.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record), flush=True)
