"""Read this phone's Wi-Fi firmware; stage checked copies in the existing WSL repo."""
import hashlib
import json
import pathlib
import re
import shlex
import struct
import subprocess

OUT = pathlib.Path(__file__).resolve().parents[1]
STAGE = OUT / 'gpu-wifi' / 'firmware'
ADB = r'C:\Android\platform-tools\adb.exe'
SERIAL = 'RZ8N2032ZXE'
REPO = '/opt/a51-hakios/upstream-a51/hakios'
KA_SOURCE = '/opt/a51-hakios/experimental/early-entry/20261111T163522918342Z/src/drivers/misc/samsung/scsc/platform_mif_9610.c'


def main():
    STAGE.mkdir(parents=True, exist_ok=True)
    records = []
    for name, size in [('mx140.bin', 1835952), ('mx140_wlan.hcf', 4326),
                       ('mx140_wlan_sw.hcf', 284), ('mx140_bt.hcf', 252)]:
        source = '/vendor/etc/wifi/' + name
        data = subprocess.run([ADB, '-s', SERIAL, 'exec-out', 'cat', source],
                              capture_output=True, check=True, timeout=30).stdout
        remote_hash = subprocess.run([ADB, '-s', SERIAL, 'shell', 'sha256sum', source],
                                     capture_output=True, check=True, timeout=30).stdout.decode().split()[0]
        sha = hashlib.sha256(data).hexdigest()
        assert len(data) == size and sha == remote_hash, name
        (STAGE / name).write_bytes(data)
        records.append({'file': name, 'bytes': size, 'sha256': sha, 'source': source,
                        'phone_hash_verified': True})
    source = subprocess.run(['wsl.exe', '-d', 'A51-KernelBuilder', '--', 'cat', KA_SOURCE],
                            capture_output=True, check=True).stdout.decode('utf-8')
    source = re.sub(r'/\*.*?\*/|//[^\n]*', '', source, flags=re.S)
    body = re.search(r'uint32_t\s+ka_patch\[\]\s*=\s*\{(.*?)\}', source, re.S).group(1)
    words = [int(v.strip(), 0) for v in body.split(',') if v.strip()]
    assert len(words) == 58
    data = struct.pack('<58I', *words)
    (STAGE / 'wlbt_ka_patch.bin').write_bytes(data)
    records.append({'file': 'wlbt_ka_patch.bin', 'bytes': len(data),
                    'sha256': hashlib.sha256(data).hexdigest(), 'source': KA_SOURCE,
                    'words': len(words), 'encoding': 'little-endian uint32'})
    manifest = {'serial': SERIAL, 'files': records}
    (STAGE.parent / 'firmware-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    # Use argument arrays and a quoted Linux script; no shell reads of binary firmware.
    linux_stage = '/mnt/' + str(STAGE).replace('\\', '/')[0].lower() + str(STAGE).replace('\\', '/')[2:]
    command = ('set -eu\nmkdir -p ' + shlex.quote(REPO + '/fw-wifi-a51') + '\n' +
               '\n'.join('cp ' + shlex.quote(linux_stage + '/' + r['file']) + ' ' +
                         shlex.quote(REPO + '/fw-wifi-a51/' + r['file']) for r in records))
    subprocess.run(['wsl.exe', '-d', 'A51-KernelBuilder', '--', 'bash', '-c', command], check=True)
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
