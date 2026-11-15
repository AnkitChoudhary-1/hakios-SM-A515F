> Publication note: this is a historical workspace document. Current completion decisions are in [PUBLIC-STATUS.md](PUBLIC-STATUS.md); raw local evidence is described in [PUBLICATION.md](PUBLICATION.md).

# Host/QEMU stackless fault envelope prototype (P2-020)

Date: 12 November 2026. Status: implemented and verified on Windows and native WSL as an isolated host/QEMU prototype. No phone operation, device write or A51 execution occurred.

This milestone satisfies the host-only architectural exception vector and fault-handling component of Phase 2. It implements a stackless AArch64 exception envelope that captures complete CPU state (registers, vector offsets, ESR_ELx, ELR_ELx, FAR_ELx, SPSR_ELx) into a dedicated 512-byte hardware record without relying on a stack, heap or runtime memory allocations.

## Selected evidence and exact inputs

The selected evidence directory is `evidence/phase-2/fault-envelope-host/20261112T161948964366Z/`.
Its result artifact is `result.json` with SHA-256 `70e6a79858bcde7db56867c8b38735480633851f95b107216011982cd28c2f7a`.

| File | Role | Meaning |
|---|---|---|
| `envelope.S` | Payload assembly | Stackless vector setup, state preservation, fault-interception and clean resumption |
| `envelope.h` | Offsets header | 512-byte record offset constants, magic signature `0x31464c45494b4148` (`HAKIKELF1`) |
| `harness.S` | QEMU entry shim | Exception level entry, register fixture initialization, continuation capture |
| `harness.c` | Bare-metal driver | Test vector harness, UART serial output, continuation validation |
| `harness.ld` | Linker script | 64 MB QEMU virt memory layout, vector alignment (2048 bytes) and 512-byte record |
| `host_test.py` | Test suite / verifier | Automated QEMU matrix runner via QMP and independent binary memory validator |

## Architectural test matrix

The test suite executes 34 distinct architectural cases across isolated QEMU instances:

- **Exception Levels**: EL1 (OS kernel mode) and EL2 (Hypervisor mode).
- **Stack Configurations**: SP_EL0 and SP_ELx.
- **Entry Guards**:
  - `guard 0`: Normal safe entry.
  - `guard 1`: Unsafe DAIF interrupt state.
  - `guard 2`: Unsafe data/instruction cache state.
  - `guard 3`: Unsafe MMU / alignment state.
- **Fault Scenarios**:
  - `fault 0`: Normal successful execution (XOR-folded register state returned via continuation).
  - `fault 1`: Non-fatal handled synchronous exception (state captured, ELR resumed).
  - `fault 2`: Non-fatal instruction abort.
  - `fault 3`: Fatal data abort (record committed to memory, vCPU parked at `hkf_park`).
  - `fault 4`: Fatal unhandled exception site.
  - `fault 5`: Fatal stack/register corruption.

## Verification results

All 34 test cases passed with 538 verified architectural assertions:
- **Build and execution run**: `20261112T161937876601Z-fault-envelope-host-test` (exit 0).
- **Windows offline replay**: `20261112T162512024268Z-fault-envelope-verify-windows` passed 34 cases, 538 checks, 536 files (exit 0).
- **WSL offline replay**: `20261112T162652754513Z-fault-envelope-verify-wsl` passed 34 cases, 538 checks, 536 files (exit 0).

## Scope and Phase 2 boundaries

This prototype proves stackless exception vectors and fault-state capture in QEMU. It does not establish:
1. Physical Samsung Exynos 9611 watchdog timer registers or reboot hardware.
2. RAM retention across a hardware warm reset on the A51.
3. Standalone A51 execution, phone flashing or physical device logging.

Phase 2 remains `in_progress`.

