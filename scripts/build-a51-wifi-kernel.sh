#!/bin/bash
set -euo pipefail
cd /opt/a51-hakios/upstream-a51/hakios
export KERNEL_LOG=xnu-a51-open-wifi-build.log
tools/make-kernel.sh -j8 > a51-open-wifi-build-summary.log 2>&1
tail -20 a51-open-wifi-build-summary.log
sha256sum hakios-kernel
