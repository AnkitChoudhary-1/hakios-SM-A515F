#!/usr/bin/env python3
"""Pack the complete standalone XNU loader and payload for Samsung Galaxy A51."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import struct
import subprocess
import sys

from hakios_devicetree import build_exynos9611_device_tree
from hakios_macho import BootArgs, BootVideo, MachOFile

KERNEL_VIRT_BASE = 0xFFFFFFF004000000
PHYS_BASE        = 0x80000000
MEM_SIZE         = 0x40000000   # 1 GB
SLIDE            = PHYS_BASE - KERNEL_VIRT_BASE


def build_a51_xnu_loader(
    kernel_path: Path,
    hello_path: Path,
    output_bin: Path,
    work_dir: Path,
    checkpoint: int = 0,
    cmdline: str = "rd=md0 -v cpus=1 serial=3 debug=0x8 hello_wait=3 loader_return_after=20 hakios_kver=p3-a53-gicv2",
    pad_to: int = 36334080
) -> dict:
    work_dir.mkdir(parents=True, exist_ok=True)

    # 1. Parse Mach-O kernel
    kernel_raw = kernel_path.read_bytes()
    mf = MachOFile(kernel_raw)
    entry_pa = mf.entry_point_va + SLIDE

    stub_slot = mf.find_loader_stub_slot()
    stub_slot_pa = 0
    if stub_slot:
        slot_fileoff, slot_va = stub_slot
        stub_slot_pa = slot_va + SLIDE

    # 2. Determine highest kernel segment address to avoid collisions
    seg_ends = [s.vmaddr + SLIDE + s.vmsize for s in mf.segments if s.vmsize]
    max_seg_end = (max(seg_ends) + 0xFFFF) & ~0xFFFF  # e.g., 0x84210000

    # Prepare Ramdisk safely above all kernel segments
    hello_raw = hello_path.read_bytes()
    ramdisk_pa = max_seg_end + 0x10000                 # 0x84220000
    ramdisk_size = (len(hello_raw) + 4095) & ~4095

    # Prepare BootArgs above Ramdisk
    ba_pa = (ramdisk_pa + ramdisk_size + 0xFFFF) & ~0xFFFF # 0x84240000

    # 3. Build Apple Device Tree above BootArgs
    dt_pa = ba_pa + 0x10000                            # 0x84250000
    dt_va = dt_pa - SLIDE

    dt_blob = build_exynos9611_device_tree(
        dram_base=PHYS_BASE,
        dram_size=MEM_SIZE,
        ramdisk_pa=ramdisk_pa,
        ramdisk_size=ramdisk_size,
        uart_pa=0x13820000,
        gic_dist_pa=0x12301000,
        gic_cpu_pa=0x12302000,
        timebase_hz=26000000,
    )

    top_of_kernel = (dt_pa + len(dt_blob) + 0xFFFF) & ~0xFFFF # 0x84270000

    # 4. Build boot_args
    ba = BootArgs(
        revision=2,
        version=2,
        virtBase=KERNEL_VIRT_BASE,
        physBase=PHYS_BASE,
        memSize=MEM_SIZE,
        topOfKernelData=top_of_kernel,
        video=BootVideo(
            v_baseAddr=0xCA000000,
            v_display=1,
            v_rowBytes=4320,
            v_width=1080,
            v_height=2400,
            v_depth=32
        ),
        machineType=0,
        deviceTreeP=dt_va,
        deviceTreeLength=len(dt_blob),
        commandLine=cmdline,
        bootFlags=0,
        memSizeActual=MEM_SIZE
    )
    ba_bytes = ba.pack()

    # 5. Build Chunks and TOC
    # Each TOC entry: (src_offset, dest_pa, copy_bytes, zero_bytes)
    chunks = []
    toc = []

    def add_chunk(dest_pa: int, data: bytes, total_vmsize: int):
        nonlocal chunks, toc
        offset = len(b"".join(chunks))
        # 16-byte align each chunk in payload
        pad_len = (-offset) % 16
        if pad_len > 0:
            chunks.append(b"\x00" * pad_len)
            offset += pad_len

        chunks.append(data)
        copy_bytes = len(data)
        zero_bytes = max(0, total_vmsize - copy_bytes)
        toc.append((offset, dest_pa, copy_bytes, zero_bytes))

    # Chunk 0: boot_args
    add_chunk(ba_pa, ba_bytes, len(ba_bytes))

    # Chunk 1: device tree
    add_chunk(dt_pa, dt_blob, len(dt_blob))

    # Chunk 2: Ramdisk
    add_chunk(ramdisk_pa, hello_raw, ramdisk_size)

    # Chunks 3..N: Mach-O segments
    for s in mf.segments:
        if s.vmsize == 0:
            continue
        seg_dest_pa = s.vmaddr + SLIDE
        seg_data = kernel_raw[s.fileoff : s.fileoff + s.filesize]
        add_chunk(seg_dest_pa, seg_data, s.vmsize)

    payload_blob = b"".join(chunks)
    payload_bin_path = work_dir / "payload_blob.bin"
    payload_bin_path.write_bytes(payload_blob)

    # 6. Generate TOC assembly
    toc_s_path = work_dir / "a51_toc.S"
    with toc_s_path.open("w") as f:
        f.write('/* Generated A51 Payload TOC & Config */\n')
        f.write('#define __ASSEMBLY__ 1\n')
        f.write('#include "xnu_trampoline.h"\n\n')

        # Override xnu_trampoline_config
        f.write('.section .data.config, "aw", %progbits\n')
        f.write('.align 3\n')
        f.write('.global xnu_trampoline_config\n')
        f.write('xnu_trampoline_config:\n')
        f.write(f'    .quad 0x{entry_pa:016x}           // target_entry_pc\n')
        f.write(f'    .quad 0x{ba_pa:016x}              // boot_args_pa\n')
        f.write(f'    .quad 0x{stub_slot_pa:016x}       // loader_stub_slot_pa\n')
        f.write(f'    .quad {checkpoint}                // checkpoint\n')
        f.write(f'    .quad 0x{SLIDE & 0xFFFFFFFFFFFFFFFF:016x} // slide\n')
        f.write(f'    .quad 0                           // continue_pc (0 = return)\n\n')

        f.write('.section .data.toc, "aw", %progbits\n')
        f.write('.align 4\n')
        f.write('.global _payload_toc\n')
        f.write('_payload_toc:\n')
        for src_off, dst_pa, c_bytes, z_bytes in toc:
            f.write(f'    .quad 0x{src_off:x}, 0x{dst_pa:016x}, 0x{c_bytes:x}, 0x{z_bytes:x}\n')
        # Sentinel
        f.write('    .quad 0xFFFFFFFFFFFFFFFF, 0, 0, 0\n\n')

        f.write('.section .data.payload, "aw", %progbits\n')
        f.write('.align 12\n')
        f.write('.global _payload_base\n')
        f.write('_payload_base:\n')
        f.write(f'    .incbin "{payload_bin_path.as_posix()}"\n')

    # 7. Compile and link
    loader_src = Path(__file__).parent / "a51_loader.S"
    linker_script = Path(__file__).parent / "a51_loader.ld"
    include_dir = Path(__file__).parent

    cmd_compile = [
        "clang",
        "--target=aarch64-none-elf",
        "-mcpu=cortex-a53",
        "-ffreestanding",
        "-fno-builtin",
        "-fno-stack-protector",
        "-mgeneral-regs-only",
        "-O2",
        f"-I{include_dir.as_posix()}",
        "-c",
        loader_src.as_posix(),
        "-o",
        (work_dir / "a51_loader.o").as_posix()
    ]
    subprocess.run(cmd_compile, check=True)

    cmd_compile_toc = [
        "clang",
        "--target=aarch64-none-elf",
        "-mcpu=cortex-a53",
        "-ffreestanding",
        "-fno-builtin",
        "-fno-stack-protector",
        "-mgeneral-regs-only",
        "-O2",
        f"-I{include_dir.as_posix()}",
        "-c",
        toc_s_path.as_posix(),
        "-o",
        (work_dir / "a51_toc.o").as_posix()
    ]
    subprocess.run(cmd_compile_toc, check=True)

    elf_path = work_dir / "a51_loader.elf"
    cmd_link = [
        "ld.lld",
        f"-T{linker_script.as_posix()}",
        "--build-id=none",
        (work_dir / "a51_loader.o").as_posix(),
        (work_dir / "a51_toc.o").as_posix(),
        "-o",
        elf_path.as_posix()
    ]
    subprocess.run(cmd_link, check=True)

    cmd_objcopy = [
        "llvm-objcopy",
        "-O",
        "binary",
        elf_path.as_posix(),
        output_bin.as_posix()
    ]
    subprocess.run(cmd_objcopy, check=True)

    out_size = output_bin.stat().st_size
    if pad_to > 0 and out_size < pad_to:
        with output_bin.open("ab") as f:
            f.write(b"\x00" * (pad_to - out_size))
        out_size = output_bin.stat().st_size
        print(f"Padded {output_bin.name} to {out_size} bytes ({out_size / 1024 / 1024:.2f} MB)")
    else:
        print(f"Built {output_bin.name}: {out_size} bytes ({out_size / 1024 / 1024:.2f} MB)")

    return {
        "output_bin": str(output_bin),
        "size_bytes": out_size,
        "entry_pa": entry_pa,
        "ba_pa": ba_pa,
        "dt_pa": dt_pa,
        "ramdisk_pa": ramdisk_pa,
        "stub_slot_pa": stub_slot_pa,
        "checkpoint": checkpoint,
        "toc_entries": len(toc),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kernel", default="/opt/a51-hakios/experimental/phase3-port/20261114T013656044425Z/hakios-kernel")
    parser.add_argument("--hello", default="/opt/a51-hakios/experimental/phase3-port/20261114T013656044425Z/userland/hello")
    parser.add_argument("--output", default="a51_xnu_loader.bin")
    parser.add_argument("--work-dir", default="/opt/a51-hakios/experimental/a51-xnu-loader")
    parser.add_argument("--checkpoint", type=int, default=0, help="Checkpoint to stop at (default 0 for userland)")
    parser.add_argument("--cmdline", default="rd=md0 -v cpus=1 serial=3 debug=0x8 hello_wait=3 loader_return_after=20 hakios_kver=p3-a53-gicv2")
    parser.add_argument("--pad-to", type=int, default=36334080, help="Pad image to exact bytes")
    args = parser.parse_args()

    info = build_a51_xnu_loader(
        Path(args.kernel),
        Path(args.hello),
        Path(args.output),
        Path(args.work_dir),
        checkpoint=args.checkpoint,
        cmdline=args.cmdline,
        pad_to=args.pad_to
    )
    print("Success:", info)


if __name__ == "__main__":
    main()
