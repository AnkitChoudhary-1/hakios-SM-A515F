#!/usr/bin/env python3
import subprocess

def main():
    cmds = [
        "which insmod",
        "ls -l /system/bin/insmod",
        "toybox which insmod",
        "toybox insmod --help",
        "insmod /data/local/tmp/early_probe.ko"
    ]
    for c in cmds:
        res = subprocess.run(["adb", "shell", "su", "-c", c], capture_output=True, text=True)
        print(f"[{c}] rc={res.returncode}")
        print("  stdout:", res.stdout.strip())
        print("  stderr:", res.stderr.strip())

if __name__ == "__main__":
    main()
