#!/usr/bin/env python3
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
PROTO = PROJECT / "prototype" / "xnu-loader"
sys.path.insert(0, str(PROTO))

from hakios_devicetree import build_exynos9611_device_tree


def main():
    dt = build_exynos9611_device_tree()
    bin_path = "/tmp/test_devicetree.bin"
    with open(bin_path, "wb") as f:
        f.write(dt)
    print(f"Generated {bin_path}: {len(dt)} bytes")

    c_src = PROTO / "test_secure_dt.c"
    exe = "/tmp/test_secure_dt"
    subprocess.run(["gcc", "-O2", str(c_src), "-o", exe], check=True)
    res = subprocess.run([exe, bin_path], capture_output=True, text=True, check=True)
    print(res.stdout)


if __name__ == "__main__":
    main()

