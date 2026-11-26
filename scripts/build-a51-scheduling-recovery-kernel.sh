#!/bin/bash
set -euo pipefail
cd /opt/a51-hakios/upstream-a51/hakios
task_out=/mnt/c/Users/Ankit/Documents/Codex/2026-11-21/hi-2/outputs/full-quality-recovery
fb_source=xnu/files/iokit/Kernel/MiniIOMobileFramebuffer.cpp
fb_target=xnu-src/xnu-8796.121.2/iokit/Kernel/MiniIOMobileFramebuffer.cpp
if ! cmp -s "$fb_source" "$fb_target"; then
    cmp "$task_out/source-before/$fb_source" "$fb_target"
    cp -p "$fb_source" "$fb_target"
fi
# Record compilation of the exact framebuffer source in this build's log,
# even when the only incremental changes were in device drivers.
touch "$fb_target"
KERNEL_LOG=a51-scheduling-recovery-kernel.log tools/make-kernel.sh -j8 \
    > "$task_out/kernel-build-console-synced.txt" 2>&1
cmp "$fb_source" "$fb_target"
cmp devices/a51/drivers/gpu/hakios.a51gpu.c xnu-src/xnu-8796.121.2/bsd/dev/hakios.a51gpu.c
cmp devices/a51/drivers/wifi/hakios.a51wifi.c xnu-src/xnu-8796.121.2/bsd/dev/hakios.a51wifi.c
cmp drivers/input/hakios.input.c xnu-src/xnu-8796.121.2/bsd/dev/hakios.input.c
tail -3 "$task_out/kernel-build-console-synced.txt"
