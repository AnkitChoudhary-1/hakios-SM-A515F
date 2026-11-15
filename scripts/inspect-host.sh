#!/usr/bin/env bash
set -euo pipefail
uname -a
cat /etc/os-release
df -h / /mnt/c
free -h
for phase_tool in git python3 clang clang-18 ld.lld lld-link qemu-system-aarch64 make ninja cmake curl; do
    printf '%s: ' "$phase_tool"
    command -v "$phase_tool" || true
done
dpkg-query -W git python3 clang-18 lld-18 qemu-system-arm qemu-efi-aarch64 make ninja-build cmake 2>/dev/null || true
