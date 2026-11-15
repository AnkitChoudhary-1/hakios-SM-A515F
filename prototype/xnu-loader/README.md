# XNU Mach-O Loader and Trampoline Prototype

## Overview
This prototype implements Milestone P3-002: Standalone Mach-O segment loader & `boot_args` generator.

## Components
1. `hakios_macho.py`:
   - 64-bit ARM64 Mach-O parser for XNU kernels (`hakios-kernel`).
   - Validates headers, segment bounds, protection flags, entry point (`LC_UNIXTHREAD`).
   - Locates and patches the `XNULDRST` loader stub slot in the kernel image.
   - Serializes byte-accurate 736-byte Darwin `struct boot_args` (Revision 2, Version 2).
2. `xnu_trampoline.h` / `xnu_trampoline.S`:
   - Freestanding ARM64 assembly trampoline bridging from firmware/early boot to XNU entry (`start_first_cpu`).
   - Sets up architectural preconditions: EL1, MMU off, caches off, DAIF = 0x3c0, x0 = boot_args PA.
   - Installs `xnu_loader_return_stub` into `loader_stub_slot` to catch early checkpoints or exceptions.
   - Records all execution metrics into persistent 256-byte `struct xnu_boot_record`.
3. `harness.S`, `harness.c`, `harness.ld`:
   - Synthetic QEMU test harness validating register passing, return stub invocation, and real XNU entry code execution.
4. `host_test.py`:
   - Automated test runner verifying:
     - Case 0: Mock XNU entry verifying register contracts.
     - Case 1: Real compiled `hakios-kernel` entry slice executing to `LOADER_CHECKPOINT 1` and returning cleanly to the stub.
     - Case 2: Real compiled `hakios-kernel` entry slice executing to `LOADER_CHECKPOINT 2` (VBAR + OSLAR) and returning cleanly to the stub.

