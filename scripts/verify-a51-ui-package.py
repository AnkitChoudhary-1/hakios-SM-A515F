"""Read-only Windows verification of the isolated UI candidate and its rollback."""
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import struct
import tarfile

OUT = Path(__file__).resolve().parents[1]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def main():
    folder = OUT / 'ui-performance'
    manifest = json.loads((folder / 'boot-package-manifest.json').read_text())
    previous = json.loads((OUT / 'smooth-ui/boot-package-manifest.json').read_text())
    require(manifest['profile'] == 'ui-performance', 'Unexpected profile')
    for name, record in manifest['components'].items():
        data = (folder / 'boot-components' / name).read_bytes()
        require(len(data) == record['bytes'] and sha(data) == record['sha256'], name)
        require(record['sha256'] == previous['components'][name]['sha256'],
                f'Binary differs from the installed smooth-ui package: {name}')
    for package in manifest['packages']:
        arguments = package['cmdline'].split()
        pairs = [x.split('=', 1) for x in arguments]
        require(all(len(x) == 2 for x in pairs), 'Malformed arguments')
        args = dict(pairs)
        require(len(args) == len(pairs), 'Duplicate arguments')
        require(len(package['cmdline'].encode()) + len(' touch_lat=1') <= 607,
                'No room for frame tracing')
        for name, value in dict(fbscale='2', fb_threads='1', fb_ca_hz='120',
                                ui_lite='1', vblur='0', wallpaper_freeze='2',
                                loader_return_after='0', ufs_write='0', var_store='0',
                                a51mif_khz='0', a51int_khz='0').items():
            require(args.get(name) == value, f'Wrong {name}')
        require(not {'fbsubtype', 'fbwidth', 'fbheight'} & args.keys(), 'Screen class override')
        old_args = dict(x.split('=', 1) for x in previous['packages'][0]['cmdline'].split())
        delta = {k for k in args.keys() | old_args.keys() if args.get(k) != old_args.get(k)}
        require(delta <= {'epoch', 'fbscale', 'wallpaper_freeze'}, 'Unrelated argument change')
        payload = (folder / package['payload']['file']).read_bytes()
        require(payload[:4] == b'XNUP' and len(payload) == struct.unpack_from('<I', payload, 4)[0] + 8,
                'Payload header/length')
        require(len(payload) < 0x03f00000, 'Payload RAM bounds')
        at, entries, terminated = 8, {}, False
        while at + 24 <= len(payload):
            name, size, reserved = struct.unpack_from('<16sII', payload, at)
            at += 24
            require(reserved == 0, 'Reserved payload field')
            if name == bytes(16):
                require(size == 0 and at == len(payload), 'Payload terminator')
                terminated = True
                break
            name = name.split(b'\0')[0].decode()
            require(name not in entries and at + size <= len(payload), 'Payload entry bounds/duplicate')
            entries[name] = payload[at:at + size]
            at += (size + 15) & ~15
        require(terminated, 'Unterminated payload')
        require(set(entries) == set(package['payload']['entries']), 'Payload entry set')
        for name, record in package['payload']['entries'].items():
            require(len(entries[name]) == record['bytes'] and sha(entries[name]) == record['sha256'],
                    f'Payload checksum: {name}')
        require(entries['cmdline'] == package['cmdline'].encode() + b'\0', 'Payload arguments')
        for name, component in [('kernel', 'kernel'), ('loader.efi', 'loader.efi'),
                                ('ramdisk', 'root.apfs'), ('resident', 'flashboot.apfs')]:
            require(sha(entries[name]) == manifest['components'][component]['sha256'], component)
        image = (folder / package['image']).read_bytes()
        require(len(image) == package['bytes'] <= manifest['recovery_partition_bytes'] and
                sha(image) == package['sha256'] and image[:8] == b'ANDROID!', 'Recovery image')
        kernel_size = struct.unpack_from('<I', image, 8)[0]
        page = struct.unpack_from('<I', image, 36)[0]
        require(page == 2048 and struct.unpack_from('<I', image, 40)[0] == 2, 'Android header')
        body = image[page:page + kernel_size]
        firmware = (folder / 'boot-components/SILICIUM_UEFI.fd').read_bytes()
        require(body[176:176 + len(firmware)] == firmware, 'Embedded UEFI')
        payload_at = 176 + len(firmware)
        require(body[payload_at:payload_at + len(payload)] == payload, 'Embedded payload')
        ramdisk_size = struct.unpack_from('<I', image, 16)[0]
        dtb_at = (page + ((kernel_size + page - 1) // page) * page +
                  ((ramdisk_size + page - 1) // page) * page)
        dtb = (folder / 'boot-components/a51.dtb').read_bytes()
        require(image[dtb_at:dtb_at + len(dtb)] == dtb, 'Embedded DTB')
        archive_record = package['odin']
        archive = (folder / archive_record['file']).read_bytes()
        require(len(archive) == archive_record['bytes'] and sha(archive) == archive_record['sha256'],
                'Odin archive checksum')
        suffix = f"{archive_record['tar_md5']}  {Path(archive_record['file']).name[:-4]}\n".encode()
        require(archive.endswith(suffix), 'Odin MD5 trailer')
        tar = archive[:-len(suffix)]
        require(hashlib.md5(tar).hexdigest() == archive_record['tar_md5'], 'Odin tar MD5')
        with tarfile.open(fileobj=io.BytesIO(tar)) as opened:
            require(opened.getnames() == ['recovery.img'], 'Odin archive members')
            require(opened.extractfile('recovery.img').read() == image, 'Archived image')
    rollback = OUT / 'restore-current-recovery-RZ8N2032ZXE.tar.md5'
    require(sha(rollback.read_bytes()) ==
            'b19b680469b04d82622c22e27f29e4ede226256418cceab1c1934740b84274e5', 'Rollback changed')
    record = dict(verified_at_utc=datetime.now(timezone.utc).isoformat(),
                  components_match_installed_smooth_ui=True,
                  only_configuration_changes=['fbscale=2', 'wallpaper_freeze=2'],
                  render_pixels=750 * 1624, logical_points=[375, 812],
                  unchanged_artwork_subtype=True, frame_trace_fits=True,
                  payload_image_archive_checks_passed=True, rollback_verified=True,
                  phone_commands_issued=False, sustained_50_60_fps_verified=False)
    (folder / 'static-verification.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
