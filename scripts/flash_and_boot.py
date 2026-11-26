"""Wait for ADB, flash recovery with updated audio kernel, and boot iOS."""
import subprocess
import time
import sys
import pathlib

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent.parent

def main():
    print("1. Waiting for device in ADB...", flush=True)
    start = time.time()
    while time.time() - start < 120:
        res = subprocess.run(['adb', 'devices'], capture_output=True, text=True)
        if any('RZ8N2032ZXE' in l and 'device' in l for l in res.stdout.splitlines()):
            print("Device connected in Android ADB!", flush=True)
            break
        time.sleep(2)
        if int(time.time() - start) % 10 == 0:
            print(f"Waiting for Android ({int(time.time() - start)}s elapsed)...", flush=True)
    else:
        print("Device did not appear in ADB within 120s.", flush=True)
        sys.exit(1)

    print("2. Flashing updated recovery image...", flush=True)
    cmd_flash = [sys.executable, str(SCRIPT_DIR / 'install_a51.py'), '--install-recovery', '--package-dir', str(PROJECT_DIR / 'outputs' / 'high-fps-visuals')]
    p = subprocess.run(cmd_flash)
    if p.returncode != 0:
        print("Flashing failed!", flush=True)
        sys.exit(p.returncode)

    print("3. Rebooting into recovery and booting iOS...", flush=True)
    subprocess.run(['adb', '-s', 'RZ8N2032ZXE', 'reboot', 'recovery'])
    cmd_boot = [sys.executable, str(SCRIPT_DIR / 'boot_when_ready.py')]
    p_boot = subprocess.run(cmd_boot)
    sys.exit(p_boot.returncode)

if __name__ == '__main__':
    main()
