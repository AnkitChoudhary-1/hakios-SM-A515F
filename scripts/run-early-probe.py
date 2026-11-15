import subprocess
import sys

def main():
    print("Pushing early_probe.ko...")
    subprocess.run(["adb", "push", "artifacts/early_probe.ko", "/data/local/tmp/early_probe.ko"], check=True)
    
    print("Loading module...")
    # remove old if loaded
    subprocess.run(["adb", "shell", "su", "-c", "rmmod early_probe 2>/dev/null || true"])
    res = subprocess.run(["adb", "shell", "su", "-c", "insmod /data/local/tmp/early_probe.ko"], capture_output=True, text=True)
    print("insmod stdout:", res.stdout)
    print("insmod stderr:", res.stderr)
    
    print("Dmesg output:")
    res_dmesg = subprocess.run(["adb", "shell", "su", "-c", "dmesg"], capture_output=True, text=True, errors="replace")
    if res_dmesg.stdout:
        for line in res_dmesg.stdout.splitlines():
            if any(k in line for k in ["HAKIOS", "F9_LOG", "FB_LOG", "8F_LOG"]):
                print(line)

if __name__ == "__main__":
    main()
