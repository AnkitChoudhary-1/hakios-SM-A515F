#!/usr/bin/env python3
"""Build in an isolated WSL copy; retain ABI inputs and check every imported CRC.

Run through run.py in A51-KernelBuilder. Never builds in /opt/a51-everline.
No device commands. The result certifies a host candidate, not load acceptance.
"""
import datetime as dt
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import arena_probe as arena

PROJECT = Path(__file__).resolve().parents[1]
ORIGINAL = Path('/opt/a51-everline')
ISOLATED = Path('/opt/a51-hakios/diagnostics/ownership-probe')
INPUTS = ['.config', 'Module.symvers', 'include/generated/utsrelease.h',
          'include/generated/compile.h', 'include/generated/autoconf.h',
          'include/config/auto.conf', 'include/config/kernel.release',
          'arch/arm64/boot/Image', 'vmlinux', 'System.map']


def pin(path):
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'bytes': path.stat().st_size, 'sha256': digest}


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def inventory(root):
    # Metadata inventories supplement the explicit content pins above.
    records = {}
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            path = Path(directory) / name
            st = path.lstat()
            records[path.relative_to(root).as_posix()] = [st.st_mode, st.st_size,
                st.st_mtime_ns, os.readlink(path) if path.is_symlink() else None]
    return records


def elf_sections(blob):
    require(blob[:6] == b'\x7fELF\x02\x01', 'expected ELF64 little endian')
    require(struct.unpack_from('<HH', blob, 16) == (1, 183), 'expected AArch64 relocatable')
    offset = struct.unpack_from('<Q', blob, 40)[0]
    stride, count, names = struct.unpack_from('<HHH', blob, 58)
    require(stride == 64 and 0 < names < count and offset + stride * count <= len(blob), 'ELF section bounds')
    headers = [struct.unpack_from('<IIQQQQIIQQ', blob, offset + n * stride) for n in range(count)]
    def data(header):
        pos, size = header[4:6]
        require(pos + size <= len(blob), 'section exceeds file')
        return blob[pos:pos + size]
    strings = data(headers[names])
    return {strings[h[0]:].split(b'\0', 1)[0].decode(): (h, data(h))
            for h in headers if h[1] != 8}  # NOBITS has no file bytes.


def main():
    require(os.name == 'posix' and ORIGINAL.is_dir(), 'run in A51-KernelBuilder')
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    evidence = PROJECT / 'evidence/phase-2/ownership-probe-build' / stamp
    evidence.mkdir(parents=True)
    build = ISOLATED / stamp
    build.mkdir(parents=True, exist_ok=False)
    record = {'schema_version': 1, 'status': 'running', 'scope': 'android_ownership_probe_host_build',
              'build_directory': str(build), 'created_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
              'phone_queries': False, 'phone_writes': False, 'module_load_verified': False,
              'a51_loader_execution_verified': False, 'phase_2_device_gate_passed': False}
    write(evidence / 'result.json', record)
    budget_path = PROJECT / 'manifests/arena-probe-budget.json'
    budget = arena.validate_budget(arena.read_json(budget_path))
    require((PROJECT / 'diagnostics/ownership-probe/arena_budget.h').read_text(encoding='utf-8') == arena.header(budget) + '#define OP_PLAN_SHA \"' + arena.pin(budget_path)['sha256'] + '\"\n', 'budget header drift')
    shutil.copy2(budget_path, evidence / 'arena-probe-budget.json')
    record['budget'] = pin(evidence / 'arena-probe-budget.json')
    before = inventory(ORIGINAL)
    write(evidence / 'original-metadata-before.json', before)
    original_pins = {rel: pin(ORIGINAL / 'out' / rel) for rel in INPUTS}
    record['original_input_pins'] = original_pins
    installed = PROJECT.parent / 'everline-ksu/artifacts'
    config = (ORIGINAL / 'out/.config').read_bytes()
    require(config == (installed / 'kernel.config').read_bytes(), 'artifact configuration mismatch')
    prior = PROJECT / 'evidence/phase-2/device-prerequisites/20261111T121643948118Z'
    live_config = gzip.decompress((prior / 'queries/05-config_begin.stdout').read_bytes())
    require(config == live_config, 'observed installed configuration mismatch')
    require(pin(installed / 'Image') == original_pins['arch/arm64/boot/Image'], 'installed Image artifact mismatch')
    # Pin the retained boot association as well as the independently captured config.
    live = PROJECT / 'evidence/phase-2/live-loader/20261111T071559056361Z'
    report = json.loads((live / 'report.json').read_text())
    boot = next(q for q in report['queries'] if q['id'] == 'boot_sha256')
    require(boot['exit_code'] == 0, 'no retained successful boot readback')
    observed_boot = (live / boot['stdout']).read_text().split()[0]
    require(pin(installed / 'A51-PixelOS-Everline-KernelSU-Next-boot.img')['sha256'] == observed_boot, 'installed boot association mismatch')
    record['installed_association'] = {'config_packet': str(prior.relative_to(PROJECT)),
        'config_sha256': hashlib.sha256(live_config).hexdigest(), 'boot_sha256': observed_boot,
        'live_report_sha256': pin(live / 'report.json')['sha256']}
    def command(argv, name, timeout=180):
        print('COMMAND ' + name, flush=True)
        result = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                env=env, timeout=timeout)
        (evidence / (name + '.log')).write_bytes(result.stdout)
        record.setdefault('commands', []).append({'argv': argv, 'exit_code': result.returncode,
                                                 'log': name + '.log'})
        if result.returncode != 0:
            record.update(status='failed', original_metadata_unchanged=before == inventory(ORIGINAL),
                          original_input_bytes_unchanged=original_pins == {rel: pin(ORIGINAL / 'out' / rel) for rel in INPUTS})
        write(evidence / 'result.json', record)
        require(result.returncode == 0, name + ' failed; see retained log')
        return result.stdout
    env = dict(os.environ, PATH='/usr/lib/llvm-18/bin:' + os.environ['PATH'])
    compiler = command(['clang', '--version'], 'compiler').decode()
    linker = command(['ld.lld', '--version'], 'linker').decode()
    require('18.1.3 (1ubuntu1)' in compiler and '18.1.3' in linker, 'toolchain changed')
    print('Copying kernel sources into the isolated HakiOS directory', flush=True)
    command(['cp', '-a', '--reflink=auto', str(ORIGINAL / 'src'), str(build / 'src')], 'copy-source', 240)
    # Detach the copied KernelSU metadata pointer; no HakiOS build can write shared Git metadata.
    for path in (build / 'src').rglob('.git'):
        require(path.is_file() and not path.is_symlink(), 'unexpected copied git metadata')
        path.unlink()
    out = build / 'out'
    out.mkdir()
    for directory in ['include', 'scripts']:
        command(['cp', '-a', '--reflink=auto', str(ORIGINAL / 'out' / directory), str(out / directory)], 'copy-' + directory)
    (out / 'arch/arm64/include').mkdir(parents=True)
    command(['cp', '-a', '--reflink=auto', str(ORIGINAL / 'out/arch/arm64/include/generated'),
             str(out / 'arch/arm64/include/generated')], 'copy-arch-headers')
    for name in ['.config', 'Module.symvers']:
        shutil.copy2(ORIGINAL / 'out' / name, out / name)
    module = build / 'module'
    shutil.copytree(PROJECT / 'diagnostics/ownership-probe', module)
    native = build / 'ownership-native'
    command(['clang', '-std=c99', '-Wall', '-Wextra', '-Werror', '-pedantic', '-O1', '-g',
             '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
             str(module / 'test_ownership.c'), '-o', str(native)], 'native-compile')
    command([str(native)], 'native-tests', 30)
    for path in build.rglob('*'):
        if path.is_symlink():
            require(path.resolve().is_relative_to(build.resolve()), 'isolated symlink escapes build: ' + str(path))
    abi_headers = ['.config', 'Module.symvers', 'include/generated/utsrelease.h',
                   'include/generated/autoconf.h', 'include/config/auto.conf',
                   'include/config/kernel.release']
    require(all(pin(out / rel) == original_pins[rel] for rel in abi_headers), 'copied ABI inputs changed')
    argv = ['make', '-C', str(build / 'src'), 'O=' + str(out), 'M=' + str(module),
            'ARCH=arm64', 'LLVM=1', 'LLVM_IAS=1', 'CC=clang', 'LD=ld.lld',
            'AR=llvm-ar', 'NM=llvm-nm', 'OBJCOPY=llvm-objcopy', 'OBJDUMP=llvm-objdump',
            'READELF=llvm-readelf', 'CROSS_COMPILE=aarch64-linux-gnu-',
            'CROSS_COMPILE_ARM32=arm-linux-gnueabi-', 'CLANG_TRIPLE=aarch64-linux-gnu-',
            'V=1', '-j2', 'modules']
    command(argv, 'build')
    require(all(pin(out / rel) == original_pins[rel] for rel in abi_headers), 'build changed copied ABI inputs')
    ko = module / 'hakios_ownership_probe.ko'
    sections = elf_sections(ko.read_bytes())
    info = sections['.modinfo'][1].decode().split('\0')
    vermagic = next(x.split('=', 1)[1] for x in info if x.startswith('vermagic='))
    require(vermagic == '4.14.357-Everline-KSUN-A51 SMP preempt mod_unload modversions aarch64', 'unexpected vermagic: ' + vermagic)
    symvers = {line.split()[1]: int(line.split()[0], 16)
               for line in (ORIGINAL / 'out/Module.symvers').read_text().splitlines()}
    versions = sections['__versions'][1]
    require(versions and len(versions) % 64 == 0, 'missing/invalid symbol versions')
    imports = {}
    for offset in range(0, len(versions), 64):
        crc = struct.unpack_from('<Q', versions, offset)[0]
        name = versions[offset + 8:offset + 64].split(b'\0', 1)[0].decode()
        require(name not in imports and symvers.get(name) == crc, 'import CRC mismatch: ' + name)
        imports[name] = hex(crc)
    symbols = command(['llvm-nm', '--undefined-only', str(ko)], 'undefined-symbols').decode()
    undefined = {line.split()[-1] for line in symbols.splitlines() if line.strip()}
    require(undefined <= set(imports) and 'module_layout' in imports, 'unversioned imported symbol')
    after = inventory(ORIGINAL)
    write(evidence / 'original-metadata-after.json', after)
    require(before == after, 'original Android source/output metadata changed')
    require(original_pins == {rel: pin(ORIGINAL / 'out' / rel) for rel in INPUTS}, 'original build content changed')
    target = evidence / 'hakios_ownership_probe.ko'
    shutil.copy2(ko, target)
    shutil.copytree(module, evidence / 'module', ignore=shutil.ignore_patterns('.tmp_versions'))
    (evidence / 'Module.symvers').write_bytes((out / 'Module.symvers').read_bytes())
    for rel in ['.config', 'include/generated/compile.h', 'include/generated/utsrelease.h']:
        shutil.copy2(ORIGINAL / 'out' / rel, evidence / Path(rel).name)
    record.update(status='passed', vermagic=vermagic, imported_crcs=imports,
        module=pin(target), original_metadata_unchanged=True, original_input_bytes_unchanged=True,
        host_abi_candidate_verified=True, source_lineage='468ab8343364e4d3a267e670fa6a22fd4197a805 (recorded; no Git HEAD)')
    record['finished_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
    write(evidence / 'result.json', record)
    write(evidence / 'index.json', {'files': {p.relative_to(evidence).as_posix(): pin(p)
          for p in sorted(evidence.rglob('*')) if p.is_file() and p.name != 'index.json'}})
    print('OWNERSHIP_PROBE_BUILD ' + str(evidence.relative_to(PROJECT)), flush=True)
    print('ABI_CANDIDATE_VERIFIED imports=' + str(len(imports)) + ' module_load=false phase2_gate=false', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
