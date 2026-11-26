"""Verify source copies used by the completed WSL build and packaged artifacts."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import os

REPO = Path('/opt/a51-hakios/upstream-a51/hakios')
profile = os.environ.get('A51_PROFILE', 'full-quality')
assert profile in ('full-quality', 'full-quality-recovery')
OUT = Path(__file__).resolve().parents[1] / profile


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    source_record = json.loads((OUT / 'source-changes.json').read_text())
    for rel, record in source_record['files'].items():
        assert digest(REPO / rel) == record['after_sha256'], f'Source changed: {rel}'
    for src, dst in [
        ('xnu/files/iokit/Kernel/MiniIOMobileFramebuffer.cpp',
         'xnu-src/xnu-8796.121.2/iokit/Kernel/MiniIOMobileFramebuffer.cpp'),
        ('devices/a51/drivers/gpu/hakios.a51gpu.c',
         'xnu-src/xnu-8796.121.2/bsd/dev/hakios.a51gpu.c'),
        ('devices/a51/drivers/wifi/hakios.a51wifi.c',
         'xnu-src/xnu-8796.121.2/bsd/dev/hakios.a51wifi.c'),
        ('drivers/input/hakios.input.c',
         'xnu-src/xnu-8796.121.2/bsd/dev/hakios.input.c')]:
        assert digest(REPO / src) == digest(REPO / dst), f'Unsynchronized source: {src}'
    build = (OUT / 'kernel-build-console-synced.txt').read_text()
    assert 'C++ MiniIOMobileFramebuffer.cpo' in build
    assert 'LD mach.development.bcm2837.unstripped' in build
    assert 'make-kernel: built: hakios-kernel' in build
    firmware = {}
    for name in ('exynos9610_acpm_fvp.fw', 'exynos9610_acpm_tmu.fw'):
        src, dst = REPO / 'fw-acpm' / name, REPO / 'userland/root/fw' / name
        assert digest(src) == digest(dst), f'Firmware mismatch: {name}'
        firmware[name] = digest(src)
    manifest = json.loads((OUT / 'boot-package-manifest.json').read_text())
    for name, record in manifest['components'].items():
        assert digest(Path(record['source'])) == record['sha256'], f'Stale packaged component: {name}'
    result = dict(verified_at_utc=datetime.now(timezone.utc).isoformat(),
                  source_copies_match=True, framebuffer_recompiled_and_kernel_linked=True,
                  packaged_components_match_built_files=True, firmware_sha256=firmware,
                  source_sha256={rel: item['after_sha256']
                                 for rel, item in source_record['files'].items()},
                  kernel_build_log_sha256=digest(OUT / 'kernel-build-console-synced.txt'),
                  on_device_performance_verified=False)
    (OUT / 'build-verification.json').write_text(json.dumps(result, indent=2) + '\n')
    print('Source copies, framebuffer compilation, kernel link, firmware and packaged artifacts verified.')


if __name__ == '__main__':
    main()
