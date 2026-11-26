"""Build a host-only Wi-Fi candidate, preserving every non-kernel parent component."""
from pathlib import Path
import argparse
import copy, hashlib, io, json, re, shutil, struct, tarfile, time
from boot_line_budget import validate_boot_line
from prepare_boot import android_sections, payload_entries

OUT = Path(__file__).resolve().parents[1]
BASE = OUT / 'full-quality-recovery'
DEST = OUT / 'wifi-stability-recovery'
REPO = Path('/opt/a51-hakios/upstream-a51/hakios')

def digest(data):
    return hashlib.sha256(data).hexdigest()

def unpack(data):
    payload_entries(data)
    entries = {}
    pos = 8
    while pos < len(data):
        name, size, reserved = struct.unpack_from('<16sII', data, pos)
        pos += 24
        if not name.strip(b'\0'):
            break
        entries[name.rstrip(b'\0').decode()] = data[pos:pos + size]
        pos += (size + 15) & ~15
    return entries

def pack(entries):
    body = bytearray()
    for name, data in entries.items():
        body += struct.pack('<16sII', name.encode(), len(data), 0)
        body += data + bytes(-len(data) % 16)
    body += bytes(24)
    return b'XNUP' + struct.pack('<I', len(body)) + body

def android_id(kernel, ramdisk, dtb):
    sha = hashlib.sha1()
    for data in (kernel, ramdisk, b'', b'', dtb):
        sha.update(data)
        sha.update(struct.pack('<I', len(data)))
    return sha.digest() + bytes(12)

def main():
    global BASE, DEST
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument('--base-dir', type=Path, default=BASE)
    args.add_argument('--package-dir', type=Path, default=DEST)
    options = args.parse_args()
    BASE, DEST = options.base_dir.resolve(), options.package_dir.resolve()
    assert BASE != DEST, 'Candidate must not overwrite its parent'
    parent = json.loads((BASE / 'boot-package-manifest.json').read_text())
    manifest = copy.deepcopy(parent)
    dest = DEST / 'boot-components'
    dest.mkdir(parents=True, exist_ok=True)
    kernel = (REPO / 'hakios-kernel').read_bytes()
    linked = REPO / 'xnu-src/xnu-8796.121.2/BUILD/obj/DEVELOPMENT_ARM64_BCM2837/mach.development.bcm2837'
    assert kernel == linked.read_bytes(), 'Kernel is not the freshly linked output'
    assert struct.unpack_from('<III', kernel) == (0xfeedfacf, 0x100000c, 0)
    for name, record in parent['components'].items():
        original = (BASE / 'boot-components' / name).read_bytes()
        assert len(original) == record['bytes'] and digest(original) == record['sha256']
        data = kernel if name == 'kernel' else original
        (dest / name).write_bytes(data)
        manifest['components'][name] = dict(record, bytes=len(data), sha256=digest(data),
                                             source=str(REPO / 'hakios-kernel') if name == 'kernel' else str(BASE / 'boot-components' / name))
    assert manifest['components']['kernel']['sha256'] != parent['components']['kernel']['sha256']
    for a, b in [('devices/a51/drivers/wifi/hakios.a51wifi.c', 'bsd/dev/hakios.a51wifi.c'),
                 ('drivers/wifi/hakios.sta.c', 'bsd/dev/hakios.sta.c'),
                 ('xnu/files/bsd/sys/hakios.sta.h', 'bsd/sys/hakios.sta.h')]:
        assert (REPO / a).read_bytes() == (REPO / 'xnu-src/xnu-8796.121.2' / b).read_bytes(), f'Unsynced source: {a}'
    package = next(p for p in parent['packages'] if p['mode'] == 'diagnostic')
    old_payload = (BASE / package['payload']['file']).read_bytes()
    entries = unpack(old_payload)
    assert entries['usb'] and 'loader.efi' in entries
    old_cmd = entries['cmdline'][:-1].decode()
    assert re.search(r'\bloader_return_after=0\b', old_cmd)
    cmd = re.sub(r'\bepoch=\d+\b', f'epoch={int(time.time())}', old_cmd)
    budget = validate_boot_line(cmd, entries['kernel.ver'][:-1].decode())
    entries['kernel'] = kernel
    entries['cmdline'] = cmd.encode() + b'\0'
    new_payload = pack(entries)
    payload = DEST / 'a51-ios16.5-diagnostic.xnup'
    payload.write_bytes(new_payload)
    pimage = (BASE / package['image']).read_bytes()
    header, body, dtb = android_sections(pimage)
    offset = body.find(old_payload)
    assert offset >= 0 and body.find(old_payload, offset + 1) == -1
    prefix = body[:offset]
    assert prefix.endswith((dest / 'SILICIUM_UEFI.fd').read_bytes())
    assert body[offset + len(old_payload):] == bytes(-len(prefix + old_payload) % 16)
    (dest / 'BootShim.bin').write_bytes(prefix[:-2097152])
    newbody = prefix + new_payload
    newbody += bytes(-len(newbody) % 16)
    page = header['page_size']
    align = lambda n: (n + page - 1) // page * page
    ramdisk_off = page + align(len(body))
    ramdisk = pimage[ramdisk_off:ramdisk_off + header['ramdisk_bytes']]
    # Only the kernel length and boot-image ID change in the parent header.
    boot_header = bytearray(pimage[:page])
    assert boot_header[576:608] == android_id(body, ramdisk, dtb)
    struct.pack_into('<I', boot_header, 8, len(newbody))
    boot_header[576:608] = android_id(newbody, ramdisk, dtb)
    tail = pimage[ramdisk_off:]
    image_data = boot_header + newbody + bytes(align(len(newbody)) - len(newbody)) + tail
    assert len(image_data) <= parent['recovery_partition_bytes']
    actual_header, actual_body, actual_dtb = android_sections(image_data)
    assert actual_body == newbody and actual_dtb == dtb
    image = DEST / 'a51-ios16.5-diagnostic-recovery.img'
    image.write_bytes(image_data)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w', format=tarfile.USTAR_FORMAT) as tf:
        info = tarfile.TarInfo('recovery.img')
        info.size, info.mode, info.mtime = len(image_data), 0o644, 0
        tf.addfile(info, io.BytesIO(image_data))
    tar = buf.getvalue()
    name = 'hakios-a51-ios16.5-' + DEST.name + '-RECOVERY'
    md5 = hashlib.md5(tar).hexdigest()
    archive = DEST / (name + '.tar.md5')
    archive.write_bytes(tar + f'{md5}  {name}.tar\n'.encode())
    with tarfile.open(fileobj=io.BytesIO(tar)) as tf:
        assert tf.getnames() == ['recovery.img'] and tf.extractfile('recovery.img').read() == image_data
    rollback = OUT / 'restore-current-recovery-RZ8N2032ZXE.tar.md5'
    with tarfile.open(rollback) as tf:
        assert tf.getnames() == ['recovery.img']
        assert digest(tf.extractfile('recovery.img').read()) == '12412e2008d950260cda627ac7a6b8eac954b49ef9db5573a297f67e4fc85999'
    shutil.copy2(rollback, DEST / rollback.name)
    manifest.update(profile=DEST.name, parent_profile=parent['profile'],
                    phone_boot_tested=False, phone_partitions_written=False, static_validation_passed=True,
                    prepared_at_epoch=int(time.time()),
                    wifi_recovery={'restart_limit': 3, 'pending_queue_stall_ms': 15000,
                                   'reset_confirmation_required': True, 'host_tests': 'host-tests/results.json'},
                    packages=[dict(mode='diagnostic', image=image.name, bytes=len(image_data), sha256=digest(image_data),
                                   cmdline=cmd, header=actual_header, boot_line_budget=budget,
                                   payload={'file': payload.name, 'entries': payload_entries(new_payload)},
                                   odin={'file': archive.name, 'bytes': archive.stat().st_size,
                                         'sha256': digest(archive.read_bytes()), 'tar_md5': md5, 'members': ['recovery.img']})])
    (DEST / 'boot-package-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'image_bytes': len(image_data), 'kernel_sha256': digest(kernel),
                      'preserved_non_kernel_components': True, 'manual_return': True, 'phone_modified': False}, indent=2))

if __name__ == '__main__':
    main()
