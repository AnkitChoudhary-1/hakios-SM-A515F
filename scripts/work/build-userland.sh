#!/bin/bash
set -euo pipefail
umask 022
cd /opt/a51-hakios/upstream-a51/hakios
old=/opt/a51-hakios/experimental/phase4-port/20261114T150320411427Z/sysimage
# Independent directory entries; retain prior extraction and don't change shared file modes.
for item in rootfs cryptex cryptex-app 20F66__iPhone10,3_6; do
    test ! -e "sysimage/$item"
    cp -al "$old/$item" "sysimage/$item"
done
for item in rootfs.slt var.skel system.files cryptex-app.dmg; do
    test ! -e "sysimage/$item"
    cp -a "$old/$item" "sysimage/$item"
done
test -d /opt/a51-hakios/theos/sdks/iPhoneOS16.5.sdk
# Omit system.manifest: this recipe uses Apple's raw flash root and needs no generated RAM system image.
export THEOS=/opt/a51-hakios/theos
export QUIET=1 FLASHBOOT=1 CRYPTEXES=flash REST=1 CHECK=1 SHARE=1
unset GL TURNIP M2V PREBUILT SYSTEM
userland/build.sh > userland/a51-flashboot-build.log 2>&1
tail -30 userland/a51-flashboot-build.log
sha256sum userland/root.apfs userland/flashboot.apfs
