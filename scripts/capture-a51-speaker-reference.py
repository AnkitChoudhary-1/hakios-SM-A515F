"""Capture Android audio reference through existing interfaces, without changing settings."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

ADB = r'C:\Android\platform-tools\adb.exe'
SERIAL = 'RZ8N2032ZXE'
OUT = Path(__file__).resolve().parents[1] / 'speaker-apps' / 'android-reference'

COMMANDS = {
    'identity': 'id; getprop ro.product.model; getprop ro.board.platform; getprop sys.boot_completed; cat /proc/uptime',
    'pcm': 'cat /proc/asound/cards /proc/asound/pcm; for f in /proc/asound/card*/pcm*p/sub*/status /proc/asound/card*/pcm*p/sub*/hw_params; do if [ -f "$f" ]; then echo "$f"; cat "$f"; fi; done',
    'mixer': 'if command -v tinymix >/dev/null 2>&1; then tinymix; elif [ -x /vendor/bin/tinymix ]; then /vendor/bin/tinymix; else echo "tinymix unavailable"; fi',
    'audio-server': 'dumpsys media.audio_flinger',
    'clock-gpio': 'for f in /sys/kernel/debug/clk/clk_summary /sys/kernel/debug/gpio /sys/kernel/debug/asoc/codecs; do if [ -f "$f" ]; then echo "$f"; cat "$f"; fi; done',
    'abox': 'ls -la /sys/devices/platform/14a50000.abox/; for f in /sys/devices/platform/14a50000.abox/calliope_version /sys/devices/platform/14a50000.abox/*/gpr /sys/devices/platform/14a50000.abox/power/runtime_status; do if [ -f "$f" ]; then echo "$f"; cat "$f"; fi; done; ls -la /sys/kernel/debug/abox /sys/kernel/debug/regmap /dev/tas2562 /dev/tas_calib 2>/dev/null',
    'firmware': 'find /vendor/firmware /vendor/etc/firmware /odm/firmware -type f -name "*calliope*" -exec ls -l {} \; -exec sha256sum {} \; 2>/dev/null',
    'tas-log': 'dmesg | grep -iE "tas2562|abox|uaif|rdma|iommu|sysmmu" | tail -900',
    'battery': 'dumpsys battery; for f in /sys/class/power_supply/battery/uevent /sys/class/power_supply/battery/batt_temp /sys/class/power_supply/battery/batt_current_ua_now; do if [ -f "$f" ]; then echo "$f"; cat "$f"; fi; done',
}


def adb_shell(command, timeout=35):
    return subprocess.run([ADB, '-s', SERIAL, 'shell', 'su -c ' + shlex.quote(command)],
                          capture_output=True, timeout=timeout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', choices=['idle', 'playing'], required=True,
                        help='Owner-observed state; this tool never starts/stops playback')
    args = parser.parse_args()
    check = adb_shell('id; getprop ro.product.model; getprop sys.boot_completed')
    identity = check.stdout.decode(errors='replace')
    if check.returncode or 'uid=0(root)' not in identity or 'SM-A515F' not in identity or '1' not in identity.splitlines():
        raise SystemExit('Android/root identity check failed; nothing captured or changed.')
    folder = OUT / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S-%fZ') + '-' + args.state)
    folder.mkdir(parents=True, exist_ok=False)
    records = []
    for name, command in COMMANDS.items():
        record = dict(name=name, command=command, started_at_utc=datetime.now(timezone.utc).isoformat())
        try:
            result = adb_shell(command)
            blob = result.stdout + b'\n--- stderr ---\n' + result.stderr
            record['exit_code'] = result.returncode
        except subprocess.TimeoutExpired as error:
            blob = (error.stdout or b'') + b'\n--- TIMEOUT ---\n' + (error.stderr or b'')
            record['timeout_seconds'] = 35
        target = folder / (name + '.txt')
        target.write_bytes(blob)
        record.update(file=target.name, bytes=len(blob), sha256=hashlib.sha256(blob).hexdigest(),
                      finished_at_utc=datetime.now(timezone.utc).isoformat())
        records.append(record)
        (folder / 'manifest.json').write_text(json.dumps(dict(serial=SERIAL, state=args.state,
             owner_observed_playback=args.state == 'playing', phone_settings_changed=False,
             phone_partition_writes=False, captures=records), indent=2) + '\n', encoding='utf-8')
        print(name, record.get('exit_code', 'timeout'), len(blob), flush=True)
    print(folder)


if __name__ == '__main__':
    main()
