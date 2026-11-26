"""Build and statically validate A51 recovery packages in the existing WSL checkout.

Run with: wsl -d A51-KernelBuilder -- python3 /mnt/c/.../outputs/scripts/prepare_boot.py
This script only writes host files. It never calls adb, fastboot, or a flasher.
"""
import argparse
import hashlib
import io
import json
import pathlib
import re
import shutil
import struct
import subprocess
import tarfile
import time
from boot_line_budget import validate_boot_line

REPO = pathlib.Path('/opt/a51-hakios/upstream-a51/hakios')
OUT = pathlib.Path(__file__).resolve().parents[1]
BASE_OUT = OUT
COMP = OUT / 'boot-components'
RECOVERY_SIZE = 71106560
CMDLINE = ('root_apfs=ufs_darwin ufs=2 ufs_write=0 var_store=0 '
           'bootcpu=4 cpus=7 small_cores_after=0 touchscreen=1 '
           'a51gpu=0 wifi=0 fb_threads=1 fb_decon_trig=1 fb_decon_double=1 '
           'fb_decon_second=0xcaa00000 fb_decon_third=0xcb400000 '
           'loader_return_after=300 sb_delay=8')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def run(args, cwd=REPO):
    subprocess.run([str(x) for x in args], cwd=cwd, check=True)


def payload_entries(data):
    assert data[:4] == b'XNUP' and len(data) == 8 + struct.unpack_from('<I', data, 4)[0]
    assert len(data) < 0x03f00000
    pos, result = 8, {}
    while pos + 24 <= len(data):
        raw, size, reserved = struct.unpack_from('<16sII', data, pos)
        pos += 24
        if raw == bytes(16):
            assert size == reserved == 0 and pos == len(data)
            return result
        assert reserved == 0 and pos + size <= len(data)
        name = raw.split(b'\0')[0].decode()
        assert name not in result
        value = data[pos:pos+size]
        result[name] = {'bytes': size, 'sha256': sha(value)}
        if name in ('cmdline', 'kernel.ver', 'usb'):
            assert value.endswith(b'\0')
            result[name]['text'] = value[:-1].decode()
        pos += (size + 15) & ~15
    raise ValueError('Payload has no complete terminator')


def android_sections(data):
    assert data[:8] == b'ANDROID!'
    k, ka, r, ra, s, sa, tags, page, version, osver = struct.unpack_from('<10I', data, 8)
    assert (ka, ra, tags, page, version) == (0x10008000, 0x11000000, 0x10000100, 2048, 2)
    rec, rec_off, header = struct.unpack_from('<IQI', data, 1632)
    dtb_size, dtb_addr = struct.unpack_from('<IQ', data, 1648)
    assert rec == 0 and s == 0 and header == 1660 and dtb_addr == 0x10000000
    align = lambda n: (n + page - 1) // page * page
    dtb_off = page + align(k) + align(r)
    assert dtb_off + dtb_size <= len(data)
    return ({'kernel_bytes': k, 'kernel_address': ka, 'ramdisk_bytes': r,
             'page_size': page, 'header_version': version, 'dtb_bytes': dtb_size,
             'dtb_address': dtb_addr, 'os_version_encoded': osver},
            data[page:page+k], data[dtb_off:dtb_off+dtb_size])


def odin(source, name):
    """Make a recovery-only ustar with the conventional appended md5sum line."""
    data = source.read_bytes()
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w', format=tarfile.USTAR_FORMAT) as archive:
        info = tarfile.TarInfo('recovery.img')
        info.size, info.mode, info.mtime = len(data), 0o644, 0
        archive.addfile(info, io.BytesIO(data))
    body = buf.getvalue()
    md5 = hashlib.md5(body).hexdigest()
    result = OUT / (name + '.tar.md5')
    result.write_bytes(body + f'{md5}  {name}.tar\n'.encode())
    with tarfile.open(fileobj=io.BytesIO(body)) as archive:
        assert archive.getnames() == ['recovery.img']
        assert archive.extractfile('recovery.img').read() == data
    assert result.read_bytes()[len(body):].decode().split()[0] == hashlib.md5(body).hexdigest()
    return {'file': result.name, 'bytes': result.stat().st_size,
            'sha256': sha(result.read_bytes()), 'tar_md5': md5, 'members': ['recovery.img']}


def main():
    global OUT, COMP, CMDLINE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=('baseline', 'gpu-wifi', 'audio-performance', 'device-services', 'device-services-layout-fix', 'render-fix', 'smooth-ui', 'ui-performance', 'full-quality', 'full-quality-recovery', 'high-fps-visuals'), default='baseline')
    options = parser.parse_args()
    if options.profile == 'high-fps-visuals':
        OUT = BASE_OUT / options.profile
        # Full visual fidelity: real frosted glass blurs, full spring zoom animations,
        # dynamic wallpaper, iPhone X geometry rendered at scale 2 (2.25x fewer pixels)
        # with balanced multi-core scheduling (no 85C core saturation/throttling).
        CMDLINE = ('loader_return_after=0 touch_lat=0 '
                   'root_apfs=ufs_darwin ufs=2 ufs_write=0 var_store=0 '
                   'bootcpu=4 cpus=7 small_cores_after=0 touchscreen=1 '
                   'a51gpu=8 a51gpu_keep=1 a51gpu_clock=3 '
                   'a51cpu0_khz=1638000 a51cpu1_khz=2080000 a51gpu_mhz=683 '
                   'a51mif_khz=2093000 a51gpu_report=10 a51wifi=8 a51audio=4 '
                   'fb_threads=1 fb_decon_trig=1 fb_decon_double=1 '
                   'fb_decon_second=0xcaa00000 fb_decon_third=0xcb400000 '
                   'fb_ca_hz=120 sb_delay=8 a51battery=2 fbscale=2')
    elif options.profile in ('full-quality', 'full-quality-recovery'):
        OUT = BASE_OUT / options.profile
        # Clean cmdline within 607-byte boot budget. Full performance clocks, audio, clean var memory fs, battery.
        CMDLINE = ('loader_return_after=0 touch_lat=0 '
                   'root_apfs=ufs_darwin ufs=2 ufs_write=1 var_store=1 '
                   'bootcpu=4 cpus=7 small_cores_after=0 touchscreen=1 '
                   'a51gpu=8 a51gpu_keep=1 a51gpu_clock=3 '
                   'a51cpu0_khz=1742000 a51cpu1_khz=2314000 a51gpu_mhz=1053 '
                   'a51mif_khz=2093000 a51int_khz=667000 a51wifi=8 a51audio=4 '
                   'fb_threads=1 fb_decon_trig=1 fb_decon_double=1 '
                   'fb_decon_second=0xcaa00000 fb_decon_third=0xcb400000 '
                   'fb_ca_hz=120 sb_delay=8 enable_skstb=1 a51battery=2 fbscale=2')
    elif options.profile == 'gpu-wifi':
        OUT = BASE_OUT / 'gpu-wifi'
        CMDLINE = CMDLINE.replace('a51gpu=0 wifi=0',
                                 'a51gpu=8 a51gpu_keep=1 a51gpu_clock=0 a51wifi=8 wifi=0')
    elif options.profile in ('audio-performance', 'device-services', 'device-services-layout-fix', 'render-fix', 'smooth-ui', 'ui-performance'):
        OUT = BASE_OUT / options.profile
        # Owner requests runs until a manual return; zero disables the XNU timer.
        CMDLINE = CMDLINE.replace('loader_return_after=300', 'loader_return_after=0')
        CMDLINE = CMDLINE.replace('a51gpu=0 wifi=0',
                                 'a51gpu=8 a51gpu_keep=1 a51gpu_clock=3 '
                                 'a51cpu0_khz=1638000 a51cpu1_khz=2080000 '
                                 'a51gpu_mhz=572 a51mif_khz=0 a51int_khz=0 '
                                 'a51gpu_report=10 a51wifi=8 wifi=0 a51audio=1')
        if options.profile == 'device-services':
            CMDLINE = CMDLINE.replace('a51audio=1', 'a51audio=3')
            CMDLINE += ' fbwidth=828 fbheight=1792 fbscale=2 fbsubtype=1792 fb_ca_hz=120 a51battery=2'
        elif options.profile == 'device-services-layout-fix':
            # Restore the tested iPhone X defaults; the XR overrides changed
            # navigation/status-bar behavior with this iPhone X userland.
            CMDLINE = CMDLINE.replace('a51audio=1', 'a51audio=3')
            CMDLINE += ' a51battery=2'
        elif options.profile == 'render-fix':
            CMDLINE = CMDLINE.replace('a51audio=1', 'a51audio=3')
            # Preserve iPhone X geometry/artwork; change only CA pacing.
            # The port reports CA drawing at half the advertised refresh rate.
            CMDLINE += ' a51battery=2 fb_ca_hz=120'
        elif options.profile == 'smooth-ui':
            CMDLINE = CMDLINE.replace('a51audio=1', 'a51audio=3')
            # Eliminate multi-pass backdrop blurs, scale zooms, and redundant wallpaper redraws
            CMDLINE += ' a51battery=2 fb_ca_hz=120 ui_lite=1 vblur=0 wallpaper_freeze=1 cc_fade=150'
        elif options.profile == 'ui-performance':
            CMDLINE = CMDLINE.replace('a51audio=1', 'a51audio=3')
            # Keep the iPhone X's 375x812 points and artwork subtype. Only the
            # render scale changes; no XR dimensions/subtype overrides.
            # Freeze=1 needs a persisted scale-3 wallpaper capture at scale 2,
            # unavailable with var_store=0. Freeze=2 removes that redraw cost.
            # Retain the A51's one framebuffer worker and guarded clock policy.
            CMDLINE += ' a51battery=2 fb_ca_hz=120 ui_lite=1 vblur=0 wallpaper_freeze=2 cc_fade=150 fbscale=2'
    COMP = OUT / 'boot-components'
    COMP.mkdir(parents=True, exist_ok=True)
    sources = {
        'kernel': 'hakios-kernel',
        'loader.efi': 'xnuloader/loader.efi',
        'root.apfs': 'userland/root.apfs',
        'flashboot.apfs': 'userland/flashboot.apfs',
        'SILICIUM_UEFI.fd': 'Mu-Silicium/Build/a51Pkg/RELEASE_CLANGPDB/FV/SILICIUM_UEFI.fd',
        'a51.dtb': 'Mu-Silicium/Resources/DTBs/a51.dtb',
    }
    records = {}
    for name, rel in sources.items():
        shutil.copy2(REPO / rel, COMP / name)
        data = (COMP / name).read_bytes()
        records[name] = {'bytes': len(data), 'sha256': sha(data), 'source': str(REPO / rel)}
    kernel = (COMP / 'kernel').read_bytes()
    assert struct.unpack_from('<III', kernel) == (0xfeedfacf, 0x100000c, 0)
    loader = (COMP / 'loader.efi').read_bytes()
    assert loader[:2] == b'MZ'
    pe = struct.unpack_from('<I', loader, 0x3c)[0]
    assert loader[pe:pe+4] == b'PE\0\0' and struct.unpack_from('<H', loader, pe+4)[0] == 0xaa64
    obj = REPO / 'Mu-Silicium/Build/a51Pkg/RELEASE_CLANGPDB/AARCH64/a51Pkg/Library/MemoryMapLib/MemoryMapLib/OUTPUT/MemoryMapLib.obj'
    ir = subprocess.run(['llvm-dis', str(obj), '-o', '-'], capture_output=True, text=True, check=True).stdout
    descriptors = re.findall(r'c"([^"\\]+).*?", i64 (\d+), i64 (\d+)', ir)
    mm = [{'name': n, 'address': int(a), 'bytes': int(s)} for n, a, s in descriptors]
    for n, a, s in [('Display Reserved', 0xca000000, 0x1e00000),
                    ('XNU Payload', 0xc1000000, 0x4000000)]:
        assert {'name': n, 'address': a, 'bytes': s} in mm
    dtb = (COMP / 'a51.dtb').read_bytes()
    magic, total, hs, es, count, eo, pg, ver = struct.unpack_from('>8I', dtb)
    assert (magic, total, hs, es, count, eo, pg, ver) == (0xd7b7ab1e, len(dtb), 32, 32, 1, 32, 2048, 0)
    dt_size, dt_off = struct.unpack_from('>II', dtb, eo)
    assert dt_off + dt_size == len(dtb) and dtb[dt_off:dt_off+4] == b'\xd0\x0d\xfe\xed'
    packages = []
    for mode, usb in [('diagnostic', True), ('timed-boot', False)]:
        # Time is accurate for this preparation. For a later diagnostic boot, regenerate
        # a run payload using the current epoch; the firmware RTC is unvalidated.
        cmdline = CMDLINE + f' epoch={int(time.time())}'
        assert len(cmdline.encode()) <= 607, 'Command line exceeds XNU boot_args capacity'
        payload = OUT / f'a51-ios16.5-{mode}.xnup'
        args = ['python3', 'xnuloader/mkpayload.py', '-o', payload,
                f'loader.efi={COMP / "loader.efi"}', f'kernel={COMP / "kernel"}',
                f'ramdisk={COMP / "root.apfs"}', f'resident={COMP / "flashboot.apfs"}',
                '--cmdline', cmdline]
        if usb:
            args += ['--usb']
        run(args)
        entries = payload_entries(payload.read_bytes())
        budget = validate_boot_line(cmdline, entries['kernel.ver']['text'],
                                    reserve=0 if 'touch_lat=' in cmdline else len(' touch_lat=0'))
        for name, component in [('loader.efi', 'loader.efi'), ('kernel', 'kernel'),
                                ('ramdisk', 'root.apfs'), ('resident', 'flashboot.apfs')]:
            assert entries[name]['sha256'] == records[component]['sha256']
        assert ('usb' in entries) == usb
        image = OUT / f'a51-ios16.5-{mode}-recovery.img'
        run(['python3', 'mkxnuimg.py', '--device', 'a51', '-p', payload, '-o', image])
        data = image.read_bytes()
        assert len(data) <= RECOVERY_SIZE
        header, body, actual_dtb = android_sections(data)
        shim = (REPO / 'Mu-Silicium/BootShim/BootShim.bin').read_bytes()
        expected = shim + (COMP / 'SILICIUM_UEFI.fd').read_bytes() + payload.read_bytes()
        expected += bytes(-len(expected) % 16)
        assert body == expected and actual_dtb == dtb
        package = odin(image, f'hakios-a51-ios16.5-{mode}-RECOVERY')
        packages.append({'mode': mode, 'image': image.name, 'bytes': len(data),
                         'sha256': sha(data), 'cmdline': cmdline, 'boot_line_budget': budget, 'header': header,
                         'payload': {'file': payload.name, 'entries': entries}, 'odin': package})
    rollback = BASE_OUT / 'backups/RZ8N2032ZXE/recovery-before.img'
    assert sha(rollback.read_bytes()) == '12412e2008d950260cda627ac7a6b8eac954b49ef9db5573a297f67e4fc85999'
    restore = odin(rollback, 'restore-current-recovery-RZ8N2032ZXE')
    shutil.copy2(REPO / '.config', COMP / 'a51-kernel.config')
    (OUT / 'boot-package-manifest.json').write_text(json.dumps({
        'serial': 'RZ8N2032ZXE', 'model': 'SM-A515F', 'bootloader': 'A515FXXU8HWI5',
        'recovery_partition_bytes': RECOVERY_SIZE, 'components': records,
        'compiled_memory_regions': mm, 'packages': packages,
        'rollback': restore, 'static_validation_passed': True, 'phone_boot_tested': False,
        'profile': options.profile,
        'phone_partitions_written': False,
    }, indent=2) + '\n', encoding='utf-8')
    print('Recovery images, Odin packages, rollback package, and static checks completed.')


if __name__ == '__main__':
    main()
