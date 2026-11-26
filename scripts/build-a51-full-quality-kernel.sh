#!/bin/bash
set -euo pipefail
cd /opt/a51-hakios/upstream-a51/hakios
task_out=/mnt/c/Users/Ankit/Documents/Codex/2026-11-21/hi-2/outputs/full-quality
fb_source=xnu/files/iokit/Kernel/MiniIOMobileFramebuffer.cpp
fb_target=xnu-src/xnu-8796.121.2/iokit/Kernel/MiniIOMobileFramebuffer.cpp
# The standard incremental build synchronizes drivers, but not xnu/files.
# Refuse to overwrite an active-tree edit absent from our saved source snapshot.
if ! cmp -s "$fb_source" "$fb_target"; then
    cmp "$task_out/source-before/$fb_source" "$fb_target"
    cp -p "$fb_source" "$fb_target"
fi
KERNEL_LOG=a51-full-quality-kernel-synced.log tools/make-kernel.sh -j8 \
    > "$task_out/kernel-build-console-synced.txt" 2>&1
cmp "$fb_source" "$fb_target"
cmp devices/a51/drivers/gpu/hakios.a51gpu.c xnu-src/xnu-8796.121.2/bsd/dev/hakios.a51gpu.c
tail -3 "$task_out/kernel-build-console-synced.txt"
