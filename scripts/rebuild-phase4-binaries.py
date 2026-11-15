#!/usr/bin/env python3
"""Rebuild hakios-kernel and userland/hello inside WSL environment."""
import subprocess
import sys

def main():
    script = """#!/bin/bash
set -e
cd /opt/a51-hakios/experimental/phase4-port/20261114T150320411427Z
export THEOS=/opt/a51-hakios/theos
export PATH="/usr/lib/llvm-18/bin:$PATH"

echo "=== [1/2] Building hakios-kernel ==="
bash tools/make-kernel.sh -j4

echo "=== [2/2] Building userland/hello ==="
make hello SHELL=/bin/bash

echo "=== BUILT ARTIFACTS ==="
ls -lh hakios-kernel userland/hello
sha256sum hakios-kernel userland/hello
"""
    cmd = ["wsl", "-d", "A51-KernelBuilder", "bash", "-c", script]
    res = subprocess.run(cmd, capture_output=True, text=True)
    print(res.stdout)
    if res.returncode != 0:
        print(res.stderr, file=sys.stderr)
        sys.exit(res.returncode)

if __name__ == "__main__":
    main()
