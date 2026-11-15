#!/usr/bin/env python3
"""Reboot device and verify baseline Android stability and root."""
import subprocess
import time

def main():
    print("Issuing reboot command...")
    subprocess.run(["adb", "reboot"], check=True)
    time.sleep(5)

    print("Waiting for device to reconnect...")
    start = time.time()
    reconnected = False
    while time.time() - start < 180:
        res = subprocess.run(["adb", "devices"], capture_output=True, text=True)
        if "A51_SERIAL_HERE\tdevice" in res.stdout:
            print(f"Device reconnected in {time.time() - start:.1f}s")
            reconnected = True
            break
        time.sleep(2)
    assert reconnected, "Device failed to reconnect"

    print("Waiting for boot completed...")
    boot_ok = False
    for poll in range(60):
        res = subprocess.run(["adb", "shell", "getprop", "sys.boot_completed"], capture_output=True, text=True)
        if res.stdout.strip() == "1":
            print(f"Boot completed on poll {poll + 1}")
            boot_ok = True
            break
        time.sleep(2)
    assert boot_ok, "sys.boot_completed was not set"

    print("Checking root status...")
    res = subprocess.run(["adb", "shell", "su", "-c", "id"], capture_output=True, text=True)
    print("Root id:", res.stdout.strip())
    assert "uid=0(root)" in res.stdout, "Lost root access"

    print("Checking boot partition SHA-256...")
    res = subprocess.run(["adb", "shell", "su", "-c", "cat /dev/block/by-name/boot | sha256sum"], capture_output=True, text=True)
    current_sha = res.stdout.split()[0]
    print("Boot SHA-256:", current_sha)
    assert current_sha == "eb30609a62999e3282ac81e0a5e56411ef12ec1a39c107171bf3e01209c7cb67"

    print("BASELINE REBOOT AND STABILITY VERIFIED SUCCESSFULLY!")
    return 0

if __name__ == "__main__":
    main()

