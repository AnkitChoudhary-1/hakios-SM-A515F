"""Wait for device in Android (ADB), TWRP (recovery), or xnuloader (Fastboot), then boot iOS."""
import subprocess
import time
import sys
import pathlib

FASTBOOT = r'C:\Android\platform-tools\fastboot.exe'
ADB = r'C:\Android\platform-tools\adb.exe'
USB_SERIAL = 'xnuloader'
ADB_SERIAL = 'RZ8N2032ZXE'
SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent.parent

def check_fastboot():
    try:
        res = subprocess.run([FASTBOOT, 'devices'], capture_output=True, text=True, timeout=5)
        for line in res.stdout.splitlines():
            parts = line.strip().split()
            if parts and parts[0] == USB_SERIAL:
                return True
    except Exception:
        pass
    return False

def get_adb_state():
    try:
        res = subprocess.run([ADB, 'devices'], capture_output=True, text=True, timeout=5)
        for line in res.stdout.splitlines():
            parts = line.strip().split()
            if parts and parts[0] == ADB_SERIAL:
                return parts[1]
    except Exception:
        pass
    return None

def get_loader_result():
    try:
        res = subprocess.run([FASTBOOT, '-s', USB_SERIAL, 'getvar', 'result'],
                             capture_output=True, text=True, timeout=5)
        out = res.stdout + res.stderr
        for line in out.splitlines():
            if 'result:' in line:
                return line.split('result:')[1].strip()
    except Exception:
        pass
    return None

def main():
    print("Monitoring for device (Android ADB, TWRP recovery, or fresh xnuloader)...", flush=True)
    last_state = None
    while True:
        adb_state = get_adb_state()
        if adb_state == 'device':
            print(f"Device found in Android via ADB ({ADB_SERIAL})! Rebooting to recovery...", flush=True)
            subprocess.run([ADB, '-s', ADB_SERIAL, 'reboot', 'recovery'])
            time.sleep(5)
            continue
        elif adb_state == 'recovery':
            print(f"Device found in TWRP recovery ({ADB_SERIAL}). Idle, ready to flash.", flush=True)
            time.sleep(3)
            continue

        if check_fastboot():
            state = get_loader_result()
            if state != last_state:
                print(f"xnuloader detected with state: {state}", flush=True)
                last_state = state

            if state == 'idle':
                print(">>> xnuloader is IDLE! Launching run_diagnostic.py to stage and boot perfect iOS build...", flush=True)
                cmd = [
                    sys.executable,
                    str(SCRIPT_DIR / 'run_diagnostic.py'),
                    '--run',
                    '--package-dir', str(PROJECT_DIR / 'outputs' / 'full-quality-recovery'),
                    '--manual-return',
                    '--seconds', '180'
                ]
                p = subprocess.Popen(cmd)
                p.wait()
                sys.exit(p.returncode)
            elif state and ('no-such-core' in state or 'returned' in state):
                print(f"xnuloader in state '{state}'. Performing cold reboot to reset secondary cores...", flush=True)
                subprocess.run([FASTBOOT, '-s', USB_SERIAL, 'reboot'])
                time.sleep(5)
                continue

        time.sleep(1)

if __name__ == '__main__':
    main()
