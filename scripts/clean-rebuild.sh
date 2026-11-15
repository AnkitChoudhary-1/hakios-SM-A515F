#!/usr/bin/env bash
# Clean generated outputs only, retain source, logs, downloads and Android work.
set -euo pipefail
phase_repo=/opt/a51-hakios/src/hakios-xnu-kernel
phase_scripts=/mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts
test "$(realpath "$phase_repo")" = "$phase_repo"
test "$(git -C "$phase_repo" rev-parse HEAD)" = 63fc2b4633bac3af8e57dadab9f5a8d4cb940438
python3 "$phase_scripts/capture-build.py"
for phase_output in xnu-src/xnu-8796.121.2/BUILD xnuloader/loader.obj xnuloader/loader.efi xnuloader/identity.h userland/hello hakios-kernel qemu/payload.bin qemu/esp qemu/vars.fd; do
    phase_target=$(realpath -m "$phase_repo/$phase_output")
    case "$phase_target" in "$phase_repo"/*) ;; *) echo "Target escaped project: $phase_target" >&2; exit 1;; esac
    printf 'Remove generated output: %s\n' "$phase_target"
    rm -rf -- "$phase_target"
done
bash "$phase_scripts/build-open.sh" --rebuild-libs
