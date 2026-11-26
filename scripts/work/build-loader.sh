#!/usr/bin/env bash
set -euo pipefail
umask 022
cd /opt/a51-hakios/upstream-a51/hakios
test ! -e xnuloader/identity.h
test ! -e xnuloader/loader.efi
xnuloader/mkidentity.sh /mnt/d/iPhone10,3,iPhone10,6_16.5_20F66_Restore.ipsw
make loader
sha256sum xnuloader/loader.efi
