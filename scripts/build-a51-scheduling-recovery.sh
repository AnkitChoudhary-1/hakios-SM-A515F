#!/bin/bash
set -euo pipefail
umask 022
cd /opt/a51-hakios/upstream-a51/hakios
export THEOS=/opt/a51-hakios/theos
export QUIET=1 FLASHBOOT=1 CRYPTEXES=flash REST=1 CHECK=1 SHARE=1
export GL=1 DRIVERS=softpipe,panfrost
export RC_JOBS=/mnt/c/Users/Ankit/Documents/Codex/2026-11-21/hi-2/outputs/scripts/rc.jobs.a51-scheduling-recovery
unset TURNIP M2V PREBUILT SYSTEM
userland/build.sh > userland/a51-scheduling-recovery-build.log 2>&1
for name in exynos9610_acpm_fvp.fw exynos9610_acpm_tmu.fw; do
    cmp "fw-acpm/$name" "userland/root/fw/$name"
done
tail -15 userland/a51-scheduling-recovery-build.log
sha256sum userland/root.apfs userland/flashboot.apfs
