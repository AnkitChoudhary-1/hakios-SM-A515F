"""Prepare a fresh-epoch RAM payload, or explicitly run/collect one USB boot test.

Default/--prepare writes host files only. --run stages RAM and starts one kernel;
--collect only reads the running loader. No flash or reboot commands are issued.
Requires the prepared diagnostic recovery to be installed and entered separately.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import pathlib
import re
import struct
import subprocess
import time
import zlib
from boot_line_budget import validate_boot_line

OUT = pathlib.Path(__file__).resolve().parents[1]
FASTBOOT = r'C:\Android\platform-tools\fastboot.exe'
USB_SERIAL = 'xnuloader'


def require(value, reason):
    if not value:
        raise RuntimeError(reason)


def prepare(folder, trace_frames=False, manual_return=False):
    manifest_text = (OUT / 'boot-package-manifest.json').read_text(encoding='utf-8')
    manifest = json.loads(manifest_text)
    (folder / 'package-manifest.json').write_text(manifest_text, encoding='utf-8')
    package = next(p for p in manifest['packages'] if p['mode'] == 'diagnostic')
    cmdline = re.sub(r'\bepoch=\d+\b', f'epoch={int(time.time())}', package['cmdline'])
    if manual_return:
        cmdline = re.sub(r'\bloader_return_after=\d+\b', '', cmdline).strip()
        cmdline = 'loader_return_after=0 ' + cmdline
    if trace_frames:
        existing = re.search(r'\btouch_lat=(\d+)\b', cmdline)
        require(not existing or existing.group(1) == '1', 'Conflicting frame-trace setting')
        if not existing:
            cmdline = 'touch_lat=1 ' + cmdline
    budget = validate_boot_line(cmdline, package['payload']['entries']['kernel.ver']['text'])
    entries = {}
    for name, filename in [('kernel', 'kernel'), ('ramdisk', 'root.apfs'),
                           ('resident', 'flashboot.apfs')]:
        data = (OUT / 'boot-components' / filename).read_bytes()
        record = manifest['components'][filename]
        require(len(data) == record['bytes'] and hashlib.sha256(data).hexdigest() == record['sha256'],
                f'Boot component changed: {filename}')
        entries[name] = data
    entries['cmdline'] = cmdline.encode() + b'\0'
    entries['kernel.ver'] = package['payload']['entries']['kernel.ver']['text'].encode() + b'\0'
    body = bytearray()
    for name, data in entries.items():
        body.extend(struct.pack('<16sII', name.encode(), len(data), 0))
        body.extend(data)
        body.extend(bytes(-len(data) % 16))
    body.extend(bytes(24))
    payload = struct.pack('<II', 0x50554e58, len(body)) + body
    require(len(payload) < 0x03f00000, 'Payload exceeds loader RAM download capacity')
    target = folder / 'run-payload.xnup'
    target.write_bytes(payload)
    record = {'prepared_at_utc': datetime.now(timezone.utc).isoformat(),
              'payload': target.name, 'bytes': len(payload),
              'sha256': hashlib.sha256(payload).hexdigest(), 'cmdline': cmdline,
              'entries': {name: {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                          for name, data in entries.items()},
              'phone_partition_writes': False, 'kernel_start_requested': False,
              'ios_home_screen_verified': False}
    record['frame_tracing'] = trace_frames
    record['boot_line_budget'] = budget
    match = re.search(r'\bloader_return_after=(\d+)\b', cmdline)
    record['kernel_return_after_seconds'] = int(match.group(1)) if match else 0
    record['manual_return'] = record['kernel_return_after_seconds'] == 0
    (folder / 'test-manifest.json').write_text(json.dumps(record, indent=2) + '\n')
    return target, record


class Loader:
    def __init__(self, folder):
        self.folder = folder

    def command(self, *args, timeout=20):
        command = [FASTBOOT, '-s', USB_SERIAL, *map(str, args)]
        try:
            result = subprocess.run(command, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired as error:
            with (self.folder / 'fastboot-transcript.txt').open('a', encoding='utf-8') as f:
                f.write(f'{datetime.now(timezone.utc).isoformat()} {args!r}: TIMEOUT\n')
            raise RuntimeError(f'Fastboot timed out: {args[0]} (no automatic retry)') from error
        output = (result.stdout + result.stderr).decode(errors='replace')
        with (self.folder / 'fastboot-transcript.txt').open('a', encoding='utf-8') as f:
            f.write(f'{datetime.now(timezone.utc).isoformat()} {args!r}: exit {result.returncode}\n{output}\n')
        require(result.returncode == 0, f'Fastboot failed: {output.strip()}')
        return output

    def variable(self, name):
        output = self.command('getvar', name)
        match = re.search(r'(?:\(bootloader\)[ \t]*)?' + re.escape(name) + r':[ \t]*([^\r\n]*)', output)
        require(match, f'Loader did not return {name}: {output.strip()}')
        return match.group(1).strip()

    def verify(self):
        devices = self.command('devices')
        require(any(line.split() and line.split()[0] == USB_SERIAL for line in devices.splitlines()),
                'The xnuloader USB device is unavailable; check recovery and Windows USB driver')
        require(self.variable('product') == 'xnuloader', 'Unexpected fastboot product')
        require(self.variable('version') == '0.5', 'Unexpected loader version')

    def log(self, name):
        self.command('oem', 'log')
        self.command('get_staged', self.folder / (name + '.txt'))

    def screenshot(self, name):
        geometry = self.variable('screen').split()
        require(len(geometry) == 3, 'Invalid screen geometry')
        width, height, stride = map(int, geometry)
        require(0 < width <= 4096 and 0 < height <= 4096 and width * 4 <= stride <= 65536,
                'Screen dimensions outside expected limits')
        self.command('oem', 'screenshot')
        path = self.folder / (name + '.bgrx')
        self.command('get_staged', path)
        raw = path.read_bytes()
        require(len(raw) == stride * height, 'Screenshot length differs from loader geometry')
        # The project's xl screenshot uses BGRX for the A51 panel. Keep the raw
        # capture and geometry as well as a standard-library PNG conversion.
        rows = bytearray()
        for y in range(height):
            line = raw[y*stride:y*stride+width*4]
            rgb = bytearray(width * 3)
            rgb[0::3], rgb[1::3], rgb[2::3] = line[2::4], line[1::4], line[0::4]
            rows.extend(b'\0' + rgb)
        def chunk(kind, data):
            return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
        png = b'\x89PNG\r\n\x1a\n'
        png += chunk(b'IHDR', struct.pack('>2I5B', width, height, 8, 2, 0, 0, 0))
        png += chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b'')
        path.with_suffix('.png').write_bytes(png)
        path.with_suffix('.json').write_text(json.dumps({'width': width, 'height': height,
                                                       'stride': stride, 'format': 'BGRX'}) + '\n')


def main():
    global OUT
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--prepare', action='store_true')
    actions.add_argument('--run', action='store_true')
    actions.add_argument('--collect', action='store_true')
    parser.add_argument('--seconds', type=int, default=330, help='Host collection window, 1..360 seconds')
    parser.add_argument('--package-dir', type=pathlib.Path, default=OUT,
                        help='Directory with boot-package-manifest.json and boot-components')
    parser.add_argument('--trace-frames', action='store_true', help='Enable touch_lat=1 in the RAM test payload')
    parser.add_argument('--manual-return', action='store_true',
                        help='Disable the kernel timed return; host collection ends without stopping iOS')
    args = parser.parse_args()
    OUT = args.package_dir.resolve()
    require(1 <= args.seconds <= 360, '--seconds must be 1..360')
    folder = OUT / 'boot-tests' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S-%fZ')
    folder.mkdir(parents=True)
    target, record = prepare(folder, args.trace_frames, args.manual_return)
    record['host_collection_seconds'] = args.seconds
    print(f'Prepared verified RAM payload: {target}', flush=True)
    if not (args.run or args.collect):
        print('Host preparation complete; no phone commands issued.', flush=True)
        return
    loader = Loader(folder)
    try:
        loader.verify()
        initial = loader.variable('result')
        record['initial_result'] = initial
        if args.run:
            require(initial == 'idle' or initial.startswith('returned'), 'This firmware session has already run a kernel; enter recovery freshly before another run')
            loader.log('before-run')
            loader.command('stage', target)
            # Record the intent before issuing the start: even a host timeout may
            # have started the kernel, so the script never retries automatically.
            record['kernel_start_requested'] = True
            (folder / 'test-manifest.json').write_text(json.dumps(record, indent=2) + '\n')
            loader.command('oem', 'run')
            time.sleep(2)
        start, next_screen, count = time.monotonic(), 0, 0
        while time.monotonic() - start < args.seconds:
            state = loader.variable('result')
            if not state and time.monotonic() - start < 10:
                time.sleep(1)
                continue
            record['last_loader_result'] = state
            elapsed = int(time.monotonic() - start)
            record['last_observed_elapsed_seconds'] = elapsed
            print(f'{elapsed:3}s: {state}', flush=True)
            loader.log(f'log-{count:03}')
            # The loader clears screen geometry after the kernel returns.
            # Save its final log, but capture frames only while XNU is running.
            if state.startswith('running') and elapsed >= next_screen:
                try:
                    loader.screenshot(f'screen-{count:03}')
                except RuntimeError as error:
                    record.setdefault('screenshot_errors', []).append(str(error))
                    print(f'Screenshot unavailable: {error}', flush=True)
                next_screen = elapsed + 20
            if not state.startswith('running'):
                break
            count += 1
            remaining = args.seconds - (time.monotonic() - start)
            if remaining > 0:
                time.sleep(min(15, remaining))
        record['collection_completed'] = True
        print(f'Logs saved: {folder}. No stop or reboot was sent.', flush=True)
    except Exception as error:
        record['error'] = str(error)
        raise
    finally:
        record['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
        (folder / 'test-manifest.json').write_text(json.dumps(record, indent=2) + '\n')


if __name__ == '__main__':
    main()
