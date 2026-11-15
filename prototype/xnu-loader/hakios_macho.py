#!/usr/bin/env python3
"""HakiOS Mach-O parser, segment extractor, and Darwin boot_args serializer.

Supports 64-bit ARM64 Mach-O binaries (specifically XNU hakios-kernel).
Emits byte-accurate struct boot_args matching Apple pexpert/arm64/boot.h.
"""
import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

MH_MAGIC_64 = 0xFEEDFACF
CPU_TYPE_ARM64 = 0x0100000C
LC_SEGMENT_64 = 0x19
LC_UNIXTHREAD = 0x05

XNU_LDR_MAGIC = b"XNULDRST"
BOOT_LINE_LENGTH = 608
BOOT_ARGS_SIZE = 736


@dataclass
class BootVideo:
    v_baseAddr: int = 0
    v_display: int = 0
    v_rowBytes: int = 0
    v_width: int = 0
    v_height: int = 0
    v_depth: int = 0

    def pack(self) -> bytes:
        return struct.pack(
            "<6Q",
            self.v_baseAddr,
            self.v_display,
            self.v_rowBytes,
            self.v_width,
            self.v_height,
            self.v_depth,
        )

    @classmethod
    def unpack(cls, data: bytes) -> "BootVideo":
        vals = struct.unpack("<6Q", data[:48])
        return cls(*vals)


@dataclass
class BootArgs:
    revision: int = 2
    version: int = 2
    virtBase: int = 0xFFFFFFF004000000
    physBase: int = 0x80000000
    memSize: int = 0x40000000  # 1 GB
    topOfKernelData: int = 0x85000000
    video: BootVideo = field(default_factory=BootVideo)
    machineType: int = 0
    deviceTreeP: int = 0x80210000
    deviceTreeLength: int = 0
    commandLine: str = "-v serial=3 cpus=1 rd=md0 debug=0x144"
    bootFlags: int = 0
    memSizeActual: int = 0x40000000

    def pack(self) -> bytes:
        # Layout according to pexpert/arm64/boot.h and genassym.c:
        # uint16_t Revision (0)
        # uint16_t Version (2)
        # 4 bytes padding (4..7)
        # uint64_t virtBase (8)
        # uint64_t physBase (16)
        # uint64_t memSize (24)
        # uint64_t topOfKernelData (32)
        # Boot_Video Video (40..87: 6 * 8 = 48 bytes)
        # uint32_t machineType (88..91)
        # 4 bytes padding (92..95)
        # uint64_t deviceTreeP (96..103)
        # uint32_t deviceTreeLength (104..107)
        # char CommandLine[608] (108..715)
        # 4 bytes padding (716..719)
        # uint64_t bootFlags (720..727)
        # uint64_t memSizeActual (728..735)
        # Total: 736 bytes
        cmd_bytes = self.commandLine.encode("utf-8")[: BOOT_LINE_LENGTH - 1]
        cmd_padded = cmd_bytes + b"\x00" * (BOOT_LINE_LENGTH - len(cmd_bytes))

        hdr = struct.pack(
            "<HH4xQQQQ",
            self.revision,
            self.version,
            self.virtBase,
            self.physBase,
            self.memSize,
            self.topOfKernelData,
        )
        vid = self.video.pack()
        mid = struct.pack(
            "<I4xQI",
            self.machineType,
            self.deviceTreeP,
            self.deviceTreeLength,
        )
        tail = struct.pack(
            "<4xQQ",
            self.bootFlags,
            self.memSizeActual,
        )
        out = hdr + vid + mid + cmd_padded + tail
        assert len(out) == BOOT_ARGS_SIZE, f"boot_args size {len(out)} != {BOOT_ARGS_SIZE}"
        return out

    @classmethod
    def unpack(cls, data: bytes) -> "BootArgs":
        assert len(data) >= BOOT_ARGS_SIZE, f"buffer {len(data)} < {BOOT_ARGS_SIZE}"
        rev, ver, virt, phys, mem, top = struct.unpack("<HH4xQQQQ", data[:40])
        vid = BootVideo.unpack(data[40:88])
        mach, dt_p, dt_len = struct.unpack("<I4xQI", data[88:108])
        cmd_raw = data[108:716]
        cmd = cmd_raw.split(b"\x00")[0].decode("utf-8", errors="replace")
        flags, mem_act = struct.unpack("<4xQQ", data[716:736])
        return cls(
            revision=rev,
            version=ver,
            virtBase=virt,
            physBase=phys,
            memSize=mem,
            topOfKernelData=top,
            video=vid,
            machineType=mach,
            deviceTreeP=dt_p,
            deviceTreeLength=dt_len,
            commandLine=cmd,
            bootFlags=flags,
            memSizeActual=mem_act,
        )


@dataclass
class MachOSegment:
    name: str
    vmaddr: int
    vmsize: int
    fileoff: int
    filesize: int
    maxprot: int
    initprot: int
    nsects: int
    flags: int
    data: bytes = b""


class MachOFile:
    def __init__(self, raw_data: bytes):
        self.raw = raw_data
        self.magic = 0
        self.cputype = 0
        self.cpusubtype = 0
        self.filetype = 0
        self.ncmds = 0
        self.sizeofcmds = 0
        self.flags = 0
        self.segments: List[MachOSegment] = []
        self.entry_point_va: int = 0
        self._parse()

    def _parse(self):
        assert len(self.raw) >= 32, "Mach-O header truncated"
        (
            self.magic,
            self.cputype,
            self.cpusubtype,
            self.filetype,
            self.ncmds,
            self.sizeofcmds,
            self.flags,
            reserved,
        ) = struct.unpack("<IIIIIIII", self.raw[:32])

        if self.magic != MH_MAGIC_64:
            raise ValueError(f"Invalid Mach-O magic 0x{self.magic:x}, expected 0x{MH_MAGIC_64:x}")
        if self.cputype != CPU_TYPE_ARM64:
            raise ValueError(f"Invalid cputype 0x{self.cputype:x}, expected ARM64 (0x{CPU_TYPE_ARM64:x})")

        offset = 32
        for _ in range(self.ncmds):
            if offset + 8 > len(self.raw):
                break
            cmd, cmdsize = struct.unpack("<II", self.raw[offset : offset + 8])
            cmd_data = self.raw[offset : offset + cmdsize]

            if cmd == LC_SEGMENT_64:
                segname_b, vmaddr, vmsize, fileoff, filesize, maxp, initp, nsects, sflags = (
                    struct.unpack("<16sQQQQiiii", cmd_data[8:72])
                )
                segname = segname_b.split(b"\x00")[0].decode("ascii", errors="replace")
                data = self.raw[fileoff : fileoff + filesize] if filesize > 0 else b""
                self.segments.append(
                    MachOSegment(
                        name=segname,
                        vmaddr=vmaddr,
                        vmsize=vmsize,
                        fileoff=fileoff,
                        filesize=filesize,
                        maxprot=maxp,
                        initprot=initp,
                        nsects=nsects,
                        flags=sflags,
                        data=data,
                    )
                )
            elif cmd == LC_UNIXTHREAD:
                # ARM64 thread state: flavor, count, followed by 34 64-bit registers:
                # x0..x28 (29), fp (30), lr (31), sp (32), pc (33), cpsr (34)
                if cmdsize >= 16 + 33 * 8:
                    regs = struct.unpack("<34Q", cmd_data[16 : 16 + 34 * 8])
                    self.entry_point_va = regs[32]  # pc is register 32 in arm64 thread state

            offset += cmdsize

    def get_segment(self, name: str) -> Optional[MachOSegment]:
        for s in self.segments:
            if s.name == name:
                return s
        return None

    def find_loader_stub_slot(self) -> Optional[Tuple[int, int]]:
        """Returns (file_offset, virtual_address) of XNULDRST magic."""
        off = self.raw.find(XNU_LDR_MAGIC)
        if off == -1:
            return None
        # Locate corresponding segment
        for s in self.segments:
            if s.fileoff <= off < s.fileoff + s.filesize:
                va = s.vmaddr + (off - s.fileoff)
                return off, va
        return off, 0

    def get_load_extents(self) -> Tuple[int, int]:
        """Returns (vm_lo, vm_hi) across all loadable segments."""
        vm_lo = 0xFFFFFFFFFFFFFFFF
        vm_hi = 0
        for s in self.segments:
            if s.vmsize == 0:
                continue
            if s.vmaddr < vm_lo:
                vm_lo = s.vmaddr
            if s.vmaddr + s.vmsize > vm_hi:
                vm_hi = s.vmaddr + s.vmsize
        return vm_lo, vm_hi


def patch_loader_stub(
    raw_data: bytearray,
    stub_pa: int,
    checkpoint: int = 0,
    slide: int = 0,
) -> bool:
    """Patches XNULDRST slot in-place in raw kernel binary."""
    off = raw_data.find(XNU_LDR_MAGIC)
    if off == -1:
        return False
    # Format of loader_stub_slot:
    # 0: .ascii "XNULDRST" (8 bytes)
    # 8: .quad stub_pa (8 bytes)
    # 16: .quad checkpoint (8 bytes)
    # 24: .quad slide (8 bytes)
    patch = struct.pack("<8sQQQ", XNU_LDR_MAGIC, stub_pa, checkpoint, slide)
    raw_data[off : off + 32] = patch
    return True

