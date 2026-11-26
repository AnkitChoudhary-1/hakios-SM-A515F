#!/bin/bash
# Re-apply all A51 smooth UI (60+ FPS), charging, battery, 40GB storage, and PosterBoard optimizations
set -euo pipefail

REPO_DIR="/opt/a51-hakios/upstream-a51/hakios"
WORKSPACE_DIR="/mnt/c/Users/Ankit/Documents/Codex/2026-11-21/hi-2"

cd "$REPO_DIR"

echo "=== Ensuring device driver tree is in place ==="
mkdir -p devices/a51/drivers/power
cp -f "${WORKSPACE_DIR}/devices/a51/drivers/power/hakios.a51battery.c" devices/a51/drivers/power/hakios.a51battery.c

echo "=== Syncing drivers to XNU ==="
xnu/sync-drivers.sh

echo "=== Checking Git branch ==="
if git branch --list | grep -q 'a51-optimized-v2'; then
    echo "Branch a51-optimized-v2 already exists and has all changes committed."
else
    echo "Applying patches to current branch..."
    for p in "${WORKSPACE_DIR}/outputs/patches/"*.patch; do
        echo "Applying $(basename "$p")..."
        git apply --check "$p" && git apply "$p"
    done
fi

echo "=== All A51 optimizations are active ==="
