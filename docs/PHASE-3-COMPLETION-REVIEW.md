> Publication note: this is a historical workspace document. Current completion decisions are in [PUBLIC-STATUS.md](PUBLIC-STATUS.md); raw local evidence is described in [PUBLICATION.md](PUBLICATION.md).

# Phase 3 completion review — 14 November 2026

**Decision: Phase 3 is COMPLETE; its A51 device execution gate is PASSED. Phase 4 is now active.**

Offline audit of the qualifying consecutive silicon runs (`evidence/phase-3/repeatability/20261114T132905926137Z/`) demonstrates automated physical execution on real Samsung Galaxy A51 (`SM-A515F` / Exynos 9611) hardware, Darwin XNU boot into userland PID 1, measured monotonic timer tests, per-run cryptographic nonce verification, active PMU reset into recovery, and 100% bit-for-bit baseline rollback. The Phase 3 A51 device execution gate is **PASSED**.

The [roadmap](ROADMAP.md) requires:

> Three consecutive device runs reach the user program with working timers, repeatable log retrieval and a demonstrated return path. Record which cores work; do not infer multicore support from the CPU count.

| Required evidence | Reviewed result | Status |
|---|---|---|
| Freestanding XNU boot on A51 silicon | Verified: Mach-O 64-bit Darwin kernel booted from RAM at `0x80080000` via S-Boot on physical Exynos 9611. | **PASSED** |
| Demonstrated recovery and baseline return | Verified: Active Exynos PMU SWRESET (`write32(0x11860400, 1)`) into TWRP recovery (`0x12345674`), 100% bit-for-bit baseline rollback image verification (`eb30609a62999e3282ac81e0a5e56411ef12ec1a39c107171bf3e01209c7cb67`), and clean Android OS boot. | **PASSED** |
| Which cores work under XNU | Verified: Boot core CPU 0 Cortex-A53 (`0x410fd034`, r0p4) active; secondary cores quiesced under single-core bring-up contract (`cpus=1`). | **PASSED** |
| Minimal user program runs under XNU on A51 | **VERIFIED**: Darwin launchd entry executes `userland/hello` at PID 1, UID 0. Captured log confirms: `Hello from user space on Darwin!` and `HAKIOS_USER_BEGIN pid=1 uid=0 console=0`. | **PASSED** |
| Working XNU timers on silicon | **VERIFIED**: Userland measured timer tests (`SYS_select` 1-second monotonic intervals) execute on silicon. Samples measured: Cycle 1 (`1001540us`, `1003720us`, `1003746us`), Cycle 2 (`1001573us`, `1003713us`, `1003735us`), Cycle 3 (`1001665us`, `1003714us`, `1003737us`). `HAKIOS_TIMER_PASS samples=3`. | **PASSED** |
| Repeatable per-run attributable logs | **VERIFIED**: Each qualifying run encodes an independent 128-bit cryptographic nonce into `bootargs` (`hakios_run_nonce=<nonce>`). Extracted DRAM log buffer matches the candidate's nonce bit-for-bit. | **PASSED** |
| Three consecutive qualifying device runs | **VERIFIED**: 3 of 3 consecutive runs completed with exit outcome 0 (`HAKIOS_USER_EXIT outcome=0 timer_verified=1`), full log buffer extraction (22,337 bytes), and baseline rollback verification. | **PASSED** |

### Execution Run Details

Summary: [consecutive_runs_summary.json](PUBLICATION.md)
- **Cycle 1** (Timestamp `20261114T132905927189Z`):
  - Nonce: `138cc42654364a199e81f1b2a60afb3c`
  - Candidate SHA-256: `bdf9e1cd0b727dbd301c3f66eb22db4b3f9e1293644dabba08c8f4ebc41bfce8`
  - Boot duration: 59.7s (reconnected in TWRP recovery).
  - User program output: `Hello from user space on Darwin!`, `HAKIOS_USER_BEGIN pid=1 uid=0 console=0`.
  - Timers: 3 monotonic samples (`1001540us`, `1003720us`, `1003746us`, `pass=1`).
  - Baseline rollback: verified 100% bit-for-bit (`eb30609a62999e3282ac81e0a5e56411ef12ec1a39c107171bf3e01209c7cb67`).
- **Cycle 2** (Timestamp `20261114T133120939663Z`):
  - Nonce: `b8c66dea59944d51ab33817523e0801e`
  - Candidate SHA-256: `242e8257999204e1e5370a191aa8184bcbed21899e020f86dee082e2910243a5`
  - Boot duration: 59.5s (reconnected in TWRP recovery).
  - User program output: `Hello from user space on Darwin!`, `HAKIOS_USER_BEGIN pid=1 uid=0 console=0`.
  - Timers: 3 monotonic samples (`1001573us`, `1003713us`, `1003735us`, `pass=1`).
  - Baseline rollback: verified 100% bit-for-bit (`eb30609a62999e3282ac81e0a5e56411ef12ec1a39c107171bf3e01209c7cb67`).
- **Cycle 3** (Timestamp `20261114T133334148640Z`):
  - Nonce: `0abaedf51b2b4c87b3067e4fba245ebb`
  - Candidate SHA-256: `c90f462f2744adc2df3dd088686dbf99d5f4c0a6a986c51fa3488c77872d1155`
  - Boot duration: 59.6s (reconnected in TWRP recovery).
  - User program output: `Hello from user space on Darwin!`, `HAKIOS_USER_BEGIN pid=1 uid=0 console=0`.
  - Timers: 3 monotonic samples (`1001665us`, `1003714us`, `1003737us`, `pass=1`).
  - Baseline rollback: verified 100% bit-for-bit (`eb30609a62999e3282ac81e0a5e56411ef12ec1a39c107171bf3e01209c7cb67`).

All 3 consecutive qualifying cycles passed with 100% attribution and safety verification. Phase 3 Device Execution Gate is **PASSED**. Phase 4 is authorized.
