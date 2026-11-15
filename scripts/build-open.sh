#!/usr/bin/env bash
set -euo pipefail
export THEOS=/opt/a51-hakios/theos
export JOBS=${JOBS:-2}
# XNU otherwise replaces the recursive job count with nproc+1.
export MAKEFLAGS="MAKEJOBS=--jobs=$JOBS SHELL=/bin/bash"
cd /opt/a51-hakios/src/hakios-xnu-kernel
trap 'phase_exit=$?; python3 /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/capture-build.py --build-exit "$phase_exit"; exit "$phase_exit"' EXIT
test "$(git rev-parse HEAD)" = 63fc2b4633bac3af8e57dadab9f5a8d4cb940438
make defconfig
test -d xnu-src/xnu-8796.121.2 || xnu/apply.sh
if [ "${1:-}" = --rebuild-libs ]; then
    xnu-deps/setup.sh --rebuild-libs
else
    xnu-deps/setup.sh
fi
python3 /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/verify-sources.py
make kernel JOBS="$JOBS" MAKEJOBS="--jobs=$JOBS"
make loader-open
make hello
xnuloader/mkpayload.py -o qemu/payload.bin kernel=hakios-kernel ramdisk=userland/hello --cmdline "$(tools/hakios-config.py args --defconfig defconfig)"
sha256sum hakios-kernel xnuloader/loader.efi userland/hello qemu/payload.bin
