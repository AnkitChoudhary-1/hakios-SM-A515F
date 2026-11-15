#!/usr/bin/env bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends build-essential clang lld llvm python-is-python3 flex bison m4 perl autoconf automake libtool-bin libncurses-dev uuid-dev zlib1g-dev libxml2 libtinfo6 cmake ninja-build qemu-system-arm qemu-efi-aarch64 ipxe-qemu dosfstools mtools ripgrep curl xz-utils ca-certificates
phase_docs=/mnt/c/Users/Ankit/Desktop/A51/hakios-a51
dpkg-query -W > "$phase_docs/manifests/ubuntu-packages.tsv"
clang --version
ld.lld --version
dsymutil --version
qemu-system-aarch64 --version
