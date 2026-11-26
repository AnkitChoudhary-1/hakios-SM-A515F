"""Independent host verification of the component-preserving Wi-Fi package (Windows/WSL)."""
from pathlib import Path
import argparse
import hashlib, io, json, re, struct, tarfile
from prepare_boot import android_sections, payload_entries
from boot_line_budget import validate_boot_line

OUT = Path(__file__).resolve().parents[1]
BASE = OUT / 'full-quality-recovery'
DEST = OUT / 'wifi-stability-recovery'
sha = lambda data: hashlib.sha256(data).hexdigest()
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--base-dir', type=Path, default=BASE)
parser.add_argument('--package-dir', type=Path, default=DEST)
args = parser.parse_args()
BASE, DEST = args.base_dir.resolve(), args.package_dir.resolve()
assert BASE != DEST

parent = json.loads((BASE / 'boot-package-manifest.json').read_text())
current = json.loads((DEST / 'boot-package-manifest.json').read_text())
assert current['serial'] == parent['serial'] == 'RZ8N2032ZXE'
assert current['model'] == 'SM-A515F' and not current['phone_boot_tested']
assert not current['phone_partitions_written']
for name, record in current['components'].items():
    data = (DEST / 'boot-components' / name).read_bytes()
    assert len(data) == record['bytes'] and sha(data) == record['sha256']
    if name != 'kernel':
        assert data == (BASE / 'boot-components' / name).read_bytes(), name
assert current['components']['kernel']['sha256'] != parent['components']['kernel']['sha256']
cp = current['packages'][0]
pp = next(p for p in parent['packages'] if p['mode'] == cp['mode'])
payload = (DEST / cp['payload']['file']).read_bytes()
ce = payload_entries(payload)
pe = payload_entries((BASE / pp['payload']['file']).read_bytes())
assert ce == cp['payload']['entries'] and ce.keys() == pe.keys()
for name in ce:
    if name not in ('kernel', 'cmdline'):
        assert ce[name] == pe[name], name
normalize = lambda text: re.sub(r'\bepoch=\d+\b', 'epoch=REGENERATED', text)
assert normalize(ce['cmdline']['text']) == normalize(pe['cmdline']['text'])
assert ce['cmdline']['text'] == cp['cmdline']
assert re.search(r'\bloader_return_after=0\b', cp['cmdline'])
assert ce['kernel']['sha256'] == current['components']['kernel']['sha256']
assert validate_boot_line(cp['cmdline'], ce['kernel.ver']['text']) == cp['boot_line_budget']
image = (DEST / cp['image']).read_bytes()
oldimage = (BASE / pp['image']).read_bytes()
assert len(image) == cp['bytes'] <= current['recovery_partition_bytes'] == 71106560
assert sha(image) == cp['sha256']
ch, cb, cd = android_sections(image)
ph, pb, pd = android_sections(oldimage)
assert cd == pd == (DEST / 'boot-components/a51.dtb').read_bytes()
masked = []
for data in (image, oldimage):
    h = bytearray(data[:2048]); h[8:12] = bytes(4); h[576:608] = bytes(32); masked.append(h)
assert masked[0] == masked[1], 'Unexpected Android header change'
prefix = (DEST / 'boot-components/BootShim.bin').read_bytes() + (DEST / 'boot-components/SILICIUM_UEFI.fd').read_bytes()
assert cb == prefix + payload + bytes(-len(prefix + payload) % 16)
assert pb.startswith(prefix)
align = lambda n: (n + 2047) & ~2047
assert image[2048 + align(len(cb)):] == oldimage[2048 + align(len(pb)):], 'Ramdisk/DTB changed'
# Independently verify the Android v2 boot ID over kernel, ramdisk, second, recovery DTBO, DTB.
ramdisk = image[2048 + align(len(cb)):2048 + align(len(cb)) + ch['ramdisk_bytes']]
identity = hashlib.sha1()
for component in (cb, ramdisk, b'', b'', cd):
    identity.update(component); identity.update(struct.pack('<I', len(component)))
assert image[576:608] == identity.digest() + bytes(12)
archive = (DEST / cp['odin']['file']).read_bytes()
assert len(archive) == cp['odin']['bytes'] and sha(archive) == cp['odin']['sha256']
name = cp['odin']['file'].removesuffix('.md5')
suffix = f"{cp['odin']['tar_md5']}  {name}\n".encode()
assert archive.endswith(suffix)
tar = archive[:-len(suffix)]
assert hashlib.md5(tar).hexdigest() == cp['odin']['tar_md5']
with tarfile.open(fileobj=io.BytesIO(tar)) as tf:
    assert tf.getnames() == ['recovery.img'] and tf.extractfile('recovery.img').read() == image
with tarfile.open(DEST / 'restore-current-recovery-RZ8N2032ZXE.tar.md5') as tf:
    assert tf.getnames() == ['recovery.img']
    assert sha(tf.extractfile('recovery.img').read()) == '12412e2008d950260cda627ac7a6b8eac954b49ef9db5573a297f67e4fc85999'
tests = json.loads((DEST / 'host-tests/results.json').read_text())
assert not tests['hardware_tested']
changes = json.loads((DEST / 'source-changes.json').read_text())
for name, record in changes.items():
    assert sha((DEST / 'source-before' / name).read_bytes()) == record['before_sha256']
    assert sha((DEST / 'source-after' / name).read_bytes()) == record['after_sha256']
assert tests['sources']['wifi'] == changes['devices/a51/drivers/wifi/hakios.a51wifi.c']['after_sha256']
assert tests['sources']['station'] == changes['drivers/wifi/hakios.sta.c']['after_sha256']
ordering = None
wifi_source = (DEST / 'source-after/devices/a51/drivers/wifi/hakios.a51wifi.c').read_text()
if 'wifi_trace_fault(void)' in wifi_source:
    ordering = json.loads((DEST / 'host-tests/ordering-results.json').read_text())
    assert ordering['passed'] and not ordering['hardware_tested']
    assert ordering['wifi_sha256'] == tests['sources']['wifi']
kernel = (DEST / 'boot-components/kernel').read_bytes()
for marker in (b'radio recovery:', b'outstanding HIP queues stalled for 15 seconds', b'radio reset confirmed:', b'radio recovery exhausted'):
    assert marker in kernel, marker
if ordering:
    for marker in (b'r4-panic', b'r4-stack', b'tl: wifi fault queues host'):
        assert marker in kernel, marker
result = {'passed': True, 'phone_modified': False, 'hardware_tested': False,
          'kernel_sha256': sha(kernel), 'image_sha256': sha(image),
          'odin_sha256': sha(archive), 'recovery_bytes': len(image),
          'non_kernel_components_identical': True, 'userland_and_visual_settings_identical': True,
          'manual_return': True, 'boot_line_budget': cp['boot_line_budget'],
          'checks': ['component hashes', 'parent payload comparison', 'Android v2 header/body/ID',
                     'recovery capacity', 'Odin member/checksum', 'saved rollback', 'linked recovery strings']}
if ordering:
    result['checks'].extend(['bounded panic/stack diagnostics under ASan/UBSan', 'optimized ARM64 compiler barriers'])
(DEST / 'static-verification.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
