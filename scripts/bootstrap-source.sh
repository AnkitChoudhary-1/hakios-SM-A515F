#!/usr/bin/env bash
set -euo pipefail
phase_root=/opt/a51-hakios
phase_repo="$phase_root/src/hakios-xnu-kernel"
phase_commit=63fc2b4633bac3af8e57dadab9f5a8d4cb940438
mkdir -p "$phase_root/src" "$phase_root/build" "$phase_root/downloads"
if [ ! -d "$phase_repo/.git" ]; then
    git init "$phase_repo"
    git -C "$phase_repo" remote add origin https://github.com/oosexgang/hakios-xnu-kernel.git
    git -C "$phase_repo" fetch --depth=1 origin "$phase_commit"
    git -C "$phase_repo" checkout --detach "$phase_commit"
fi
test "$(git -C "$phase_repo" rev-parse HEAD)" = "$phase_commit"
git -C "$phase_repo" status --short
git -C "$phase_repo" log -1 --format='%H %cI %s'
printf 'Source root: %s\n' "$phase_repo"
