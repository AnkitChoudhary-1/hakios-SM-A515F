"""Independent read-only checks of the full-quality package and saved rollback."""
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import struct
import tarfile
import argparse
from boot_line_budget import validate_boot_line

OUT = Path(__file__).resolve().parents[1]
FOLDER = OUT / 'full-quality'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def payload_entries(payload):
    require(payload[:4] == b'XNUP' and len(payload) >= 8 and
            len(payload) == struct.unpack_from('<I', payload, 4)[0] + 8,
            'Payload header/length')
    require(len(payload) < 0x03f00000, 'Payload RAM bounds')
    at, entries = 8, {}
    while at + 24 <= len(payload):
        raw, size, reserved = struct.unpack_from('<16sII', payload, at)
        at += 24
        require(reserved == 0, 'Reserved payload field')
        if raw == bytes(16):
            require(size == 0 and at == len(payload), 'Payload terminator')
            return entries
        name = raw.split(b'\0')[0].decode()
        require(name not in entries and at + size <= len(payload),
                'Payload entry bounds/duplicate')
        entries[name] = payload[at:at + size]
        at += (size + 15) & ~15
    raise RuntimeError('Unterminated payload')


def verify_archive(record, expected_image):
    archive = (FOLDER / record['file']).read_bytes()
    require(len(archive) == record['bytes'] and sha(archive) == record['sha256'],
            'Odin archive checksum')
    suffix = f"{record['tar_md5']}  {Path(record['file']).name[:-4]}\n".encode()
    require(archive.endswith(suffix), 'Odin MD5 trailer')
    tar = archive[:-len(suffix)]
    require(hashlib.md5(tar).hexdigest() == record['tar_md5'], 'Odin tar MD5')
    with tarfile.open(fileobj=io.BytesIO(tar)) as opened:
        require(opened.getnames() == ['recovery.img'], 'Odin archive members')
        require(opened.extractfile('recovery.img').read() == expected_image,
                'Archived recovery image')


def main():
    global FOLDER
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=('full-quality', 'full-quality-recovery'), default='full-quality')
    profile = parser.parse_args().profile
    FOLDER = OUT / profile
    manifest = json.loads((FOLDER / 'boot-package-manifest.json').read_text())
    require(manifest['profile'] == profile, 'Unexpected profile')
    require(manifest['serial'] == 'RZ8N2032ZXE' and manifest['model'] == 'SM-A515F' and
            manifest['recovery_partition_bytes'] == 71106560, 'Device/partition identity')
    for name, record in manifest['components'].items():
        data = (FOLDER / 'boot-components' / name).read_bytes()
        require(len(data) == record['bytes'] and sha(data) == record['sha256'], name)
    expected = dict(loader_return_after='0', touch_lat='1', root_apfs='ufs_darwin',
                    ufs='2', ufs_write='0', var_store='0', bootcpu='4', cpus='7',
                    small_cores_after='0', touchscreen='1', a51gpu='8', a51gpu_keep='1',
                    a51gpu_clock='3', a51cpu0_khz='1638000', a51cpu1_khz='2080000',
                    a51gpu_mhz='683', a51mif_khz='0', a51int_khz='0', a51gpu_report='10',
                    a51wifi='8', fb_threads='1', fb_decon_trig='1', fb_decon_double='1',
                    fb_decon_second='0xcaa00000', fb_decon_third='0xcb400000',
                    fb_ca_hz='120', sb_delay='8')
    if profile == 'full-quality-recovery':
        expected.update(fb_cpu='0', gl_cpu='1', enable_skstb='1')
    require({p['mode'] for p in manifest['packages']} == {'diagnostic', 'timed-boot'} and
            len(manifest['packages']) == 2, 'Package modes')
    budgets = []
    for package in manifest['packages']:
        pairs = [word.split('=', 1) for word in package['cmdline'].split()]
        require(all(len(pair) == 2 for pair in pairs), 'Malformed arguments')
        args = dict(pairs)
        require(len(args) == len(pairs), 'Duplicate arguments')
        require(set(args) == set(expected) | {'epoch'}, 'Unexpected boot settings')
        require(all(args[name] == value for name, value in expected.items()),
                'Full-quality profile changed')
        require(args['epoch'].isdigit(), 'Invalid epoch')
        require(package['cmdline'].startswith('loader_return_after=0 touch_lat=1 '),
                'Essential controls must precede other arguments')
        payload = (FOLDER / package['payload']['file']).read_bytes()
        entries = payload_entries(payload)
        require(set(entries) == set(package['payload']['entries']), 'Payload entry set')
        for name, record in package['payload']['entries'].items():
            require(len(entries[name]) == record['bytes'] and
                    sha(entries[name]) == record['sha256'], f'Payload checksum: {name}')
        require(entries['cmdline'] == package['cmdline'].encode() + b'\0', 'Payload arguments')
        version = entries['kernel.ver'].removesuffix(b'\0').decode()
        budget = validate_boot_line(package['cmdline'], version)
        require(budget == package['boot_line_budget'], 'Effective boot-line budget')
        budgets.append(budget)
        require(('usb' in entries) == (package['mode'] == 'diagnostic'), 'Diagnostic USB setting')
        for name, component in [('kernel', 'kernel'), ('loader.efi', 'loader.efi'),
                                ('ramdisk', 'root.apfs'), ('resident', 'flashboot.apfs')]:
            require(sha(entries[name]) == manifest['components'][component]['sha256'], component)
        image = (FOLDER / package['image']).read_bytes()
        require(len(image) == package['bytes'] <= 71106560 and
                sha(image) == package['sha256'] and image[:8] == b'ANDROID!', 'Recovery image')
        kernel_size, ramdisk_size, page, version = (struct.unpack_from('<I', image, off)[0]
                                                  for off in (8, 16, 36, 40))
        require(page == 2048 and version == 2, 'Android boot header')
        body = image[page:page + kernel_size]
        firmware = (FOLDER / 'boot-components/SILICIUM_UEFI.fd').read_bytes()
        require(body[176:176 + len(firmware)] == firmware, 'Embedded UEFI')
        payload_at = 176 + len(firmware)
        require(body[payload_at:payload_at + len(payload)] == payload, 'Embedded payload')
        align = lambda n: (n + page - 1) // page * page
        dtb_at = page + align(kernel_size) + align(ramdisk_size)
        dtb = (FOLDER / 'boot-components/a51.dtb').read_bytes()
        require(image[dtb_at:dtb_at + len(dtb)] == dtb, 'Embedded DTB')
        verify_archive(package['odin'], image)
    original = (OUT / 'backups/RZ8N2032ZXE/recovery-before.img').read_bytes()
    require(sha(original) == '12412e2008d950260cda627ac7a6b8eac954b49ef9db5573a297f67e4fc85999',
            'Original recovery backup changed')
    verify_archive(manifest['rollback'], original)
    require(sha((OUT / 'restore-current-recovery-RZ8N2032ZXE.tar.md5').read_bytes()) ==
            'b19b680469b04d82622c22e27f29e4ede226256418cceab1c1934740b84274e5', 'Saved rollback changed')
    tests = json.loads((FOLDER / 'correctness-tests.json').read_text())
    sources = json.loads((FOLDER / 'source-changes.json').read_text())
    for rel, item in sources['files'].items():
        if item['before_sha256'] is not None:
            require(sha((FOLDER / 'source-before' / rel).read_bytes()) == item['before_sha256'],
                    f'Parent source snapshot changed: {rel}')
    if profile == 'full-quality-recovery':
        recovery = json.loads((FOLDER / 'recovery-tests.json').read_text())
        require(recovery['passed'] and recovery['policy_sha256'] ==
                sources['files']['userland/src/net-recovery-policy.h']['after_sha256'], 'DHCP recovery policy tests')
        binding = json.loads((FOLDER / 'binding-tests.json').read_text())
        require(binding['passed'], 'Self-binding handler tests')
        for rel, digest in binding['source_sha256'].items():
            require(digest == sources['files'][rel]['after_sha256'], 'Binding/source provenance mismatch')
    require(tests['passed'], 'Host correctness tests failed')
    for key, rel in [('eagl', 'userland/src/eagl.c'),
                     ('framebuffer', 'xnu/files/iokit/Kernel/MiniIOMobileFramebuffer.cpp'),
                     ('clock', 'devices/a51/drivers/gpu/hakios.a51gpu.c')]:
        require(tests['sources'][key] == sources['files'][rel]['after_sha256'],
                'Test/source provenance mismatch')
        require(sha((FOLDER / 'source-before' / rel).read_bytes()) ==
                sources['files'][rel]['before_sha256'], 'Pre-edit snapshot changed')
    record = dict(verified_at_utc=datetime.now(timezone.utc).isoformat(),
                  payload_image_archive_checks_passed=True, rollback_verified=True,
                  host_correctness_tests_passed=True, boot_line_budgets=budgets,
                  render_pixels=[1125, 2436], logical_points=[375, 812], render_scale=3,
                  resolution_blur_animation_wallpaper_overrides_absent=True,
                  kernel_timed_return_disabled=True, phone_commands_issued=False,
                  sustained_50_60_fps_verified=False)
    (FOLDER / 'static-verification.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
