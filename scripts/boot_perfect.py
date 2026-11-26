"""Reboot from TWRP to xnuloader and run the perfect iOS build diagnostic."""
import subprocess
import time
import sys
import pathlib
import shutil

FASTBOOT = r'C:\Android\platform-tools\fastboot.exe'
ADB = r'C:\Android\platform-tools\adb.exe'
USB_SERIAL = 'xnuloader'
ADB_SERIAL = 'RZ8N2032ZXE'
SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent.parent
ARTIFACT_DIR = pathlib.Path(r'C:\Users\Ankit\.gemini\antigravity\brain\266e5754-252f-4c13-b53a-a4ee6f21917c')

def is_fastboot_ready():
    try:
        res = subprocess.run([FASTBOOT, 'devices'], capture_output=True, text=True, timeout=5)
        for line in res.stdout.splitlines():
            parts = line.strip().split()
            if parts and parts[0] == USB_SERIAL:
                return True
    except Exception:
        pass
    return False

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
    print("Step 1: Checking device / triggering reboot to recovery...", flush=True)
    try:
        subprocess.run([ADB, '-s', ADB_SERIAL, 'reboot', 'recovery'], timeout=10, capture_output=True)
    except Exception as e:
        print(f"adb reboot: {e}", flush=True)

    print("Step 2: Waiting for xnuloader USB Fastboot interface...", flush=True)
    start = time.time()
    while time.time() - start < 120:
        if is_fastboot_ready():
            state = get_loader_result()
            print(f"Detected xnuloader! State: {state}", flush=True)
            if state == 'idle' or (state and state.startswith('returned')):
                print("xnuloader is ready to stage and boot!", flush=True)
                break
        time.sleep(2)
        elapsed = int(time.time() - start)
        if elapsed % 10 == 0:
            print(f"Waiting for xnuloader ({elapsed}s elapsed)...", flush=True)
    else:
        print("Timeout waiting for xnuloader!", flush=True)
        sys.exit(1)

    print("Step 3: Staging and launching full-quality iOS payload...", flush=True)
    cmd = [
        sys.executable,
        str(SCRIPT_DIR / 'run_diagnostic.py'),
        '--run',
        '--package-dir', str(PROJECT_DIR / 'outputs' / 'full-quality-recovery'),
        '--manual-return',
        '--seconds', '180'
    ]
    proc = subprocess.Popen(cmd)
    ret = proc.wait()
    print(f"Diagnostic run finished with exit code {ret}", flush=True)

    # Copy latest screenshots to artifacts
    test_dirs = sorted((PROJECT_DIR / 'outputs' / 'full-quality-recovery' / 'boot-tests').glob('*'),
                       key=lambda p: p.stat().st_mtime, reverse=True)
    if test_dirs:
        latest = test_dirs[0]
        print(f"Latest test directory: {latest}", flush=True)
        for img in sorted(latest.glob('screen-*.png')):
            dst = ARTIFACT_DIR / img.name
            shutil.copy2(img, dst)
            print(f"Copied {img.name} to {dst}", flush=True)
        for log_f in latest.glob('log-*.txt'):
            dst = ARTIFACT_DIR / 'current_log.txt'
            shutil.copy2(log_f, dst)

    sys.exit(ret)

if __name__ == '__main__':
    main()
