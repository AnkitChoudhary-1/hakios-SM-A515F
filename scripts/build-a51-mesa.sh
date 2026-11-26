#!/bin/bash
set -euo pipefail
umask 022
cd /opt/a51-hakios/upstream-a51/hakios
export THEOS=/opt/a51-hakios/theos
export DRIVERS=softpipe,panfrost
# The Panfrost build must be selected explicitly: the common default is Adreno.
tools/mk-mesa.sh
