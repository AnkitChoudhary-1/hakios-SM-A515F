#!/bin/bash
set -euo pipefail
umask 022
cd /opt/a51-hakios/upstream-a51/hakios
export THEOS=/opt/a51-hakios/theos
export QUIET=1 FLASHBOOT=1 CRYPTEXES=flash REST=1 CHECK=1 SHARE=1
export GL=1 DRIVERS=softpipe,panfrost
export RC_JOBS=/mnt/c/Users/Ankit/Documents/Codex/2026-11-21/hi-2/outputs/scripts/rc.jobs.a51-gpu-wifi
unset TURNIP M2V PREBUILT SYSTEM
printf 'ssid=OPPO K13 5G B93C\nsecurity=open\n' > fw-wifi-a51/wifi.conf
userland/build.sh > userland/a51-gpu-wifi-build.log 2>&1
tail -30 userland/a51-gpu-wifi-build.log
sha256sum userland/root.apfs userland/flashboot.apfs
