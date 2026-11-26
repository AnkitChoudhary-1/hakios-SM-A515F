# A51 Wi-Fi ordering and live fault records — 23 November 2026

Status: **installed; sustained device test pending**. The guarded recovery-only installer completed on 23 November 2026 at 01:43:08 UTC (07:13:08 IST), after the owner returned to TWRP. Readback matched recovery SHA-256 `17273191c2e2c2ae4cb3882388369d12371c4290e467a6c5148f27e3015d9372`. Installation evidence: `wifi-ordering-recovery/device-installation.json` and the root installation history. Only recovery was written; live identity/GPT/Android boot checks passed. Host preparation flags retain their historical no-write meaning.

The preceding `wifi-stability-recovery` session disconnected from the unchanged open hotspot. Its sustained capture showed four validated firmware panics, three confirmed resets with resumed RX, then recovery exhaustion. See `A51-WiFi-firmware-recovery.md` for timelines/evidence. Sustained stability has not been achieved.

## Implementation

Two `dc civac` sites and four `dsb sy` sites in the Wi-Fi driver lacked compiler memory clobbers. Hardware barriers and `asm volatile` alone do not constrain ordinary memory accesses around the assembly. This candidate adds the compiler barriers. This is a source correctness correction; the current evidence does not prove it caused the firmware panics or that this correction stops them.

Before reset, the quiesced driver now writes bounded numeric panic/stack and queue diagnostics through `hakios_tl`. The loader's live log does not include ordinary kernel msgbuf until kernel return, so the existing printf panic dump is unavailable during continuous iOS operation. The original dump is retained.

The new parser checks R4 version-2 offset alignment, mapping bounds, length and Samsung XOR checksum. Invalid records emit only four header words. A validated record can reference a version-1 stack at field 52 only when that field precedes the checksum; stack offset/version/length/alignment/bounds are checked separately. Records are capped at 256 words, lines at eight words, tags at 16 characters; every line fits the timeline's 192-byte limit. Queue indices are captured before reset. No packet payloads are logged. Samsung reference: `/opt/a51/src/drivers/misc/samsung/scsc/fw_panic_record.c`. Version-1 register definitions do not decode the full version-2 layout; raw words are not a known fault reason or string pointer.

Only `devices/a51/drivers/wifi/hakios.a51wifi.c` changes from the installed candidate. Canonical and active XNU source match. Station source/header are unchanged. All non-kernel payload components and boot settings compare identical with the parent, apart from regenerated epoch and enclosing lengths/checksum. APFS userland and original app hooks/account data are preserved. Resolution, blur and animations retain the parent's settings. `loader_return_after=0` and the three-reset limit remain set.

## Host verification

- Actual recovery functions and actual station source pass Clang ASan/UBSan fixtures covering queue wrap/full preservation, stall detection versus idle/progress, panic validation, auxiliary ring indices, PMU reset order/timeout, request preservation and pthread quiescence.
- Actual new tracing functions pass ASan/UBSan fixtures for valid/invalid checksums and lengths, missing/unaligned/out-of-range offsets, mapping-end records, malformed/maximal stack records, field 52 being the checksum in a short record, output count/tag/line bounds and byte preservation of shared memory.
- Actual extracted `cache_out` compiled for ARM64 at `-O2`. Optimized LLVM IR retains memory clobbers, the store before maintenance and a fresh load after `dsb`; generated assembly retains this order. Source checks cover all six corrected sites.
- Kernel build recompiles the Wi-Fi object and links successfully. No C compile/link error was accepted. The project's existing unsupported kext symbol-set checks fail and are accepted by its build judge after the successful kernel build.
- Independent package verification passes source/test/component hashes, parent payload comparison, Android v2 header/body/boot ID, recovery capacity, Odin recovery-only member/MD5, saved rollback, linked diagnostics and 590/607-byte boot-line budget.

Host fixtures do not reproduce noncoherent electrical behavior or establish firmware compatibility, internet stability or Instagram feed loading.

## Artifacts

Folder: `outputs/wifi-ordering-recovery`. Recovery image: 29,671,424 bytes; verified partition capacity: 71,106,560 bytes.

| Artifact | SHA-256 |
| --- | --- |
| Kernel | `56a13889829a99b86abdcd6c05894b709af63ebfb9554a6ff8fc1eea16a4de10` |
| Recovery image | `17273191c2e2c2ae4cb3882388369d12371c4290e467a6c5148f27e3015d9372` |
| Odin archive | `530869d19949aba7f7450fd566ddd3bf81484355dcff3c5e73509d6febc984ea` |
| Wi-Fi source | `8a9614df5085165ff1f94136e0046c7834a5bd76b39714d3dd1c3b89c8a035c5` |
| Saved Android recovery | `12412e2008d950260cda627ac7a6b8eac954b49ef9db5573a297f67e4fc85999` |

Evidence: `static-verification.json`, `build-verification.json`, `kernel-build-console.txt`, `host-tests/results.json`, `host-tests/ordering-results.json`, ARM64 `.ll`/`.s`, source snapshots, `source-changes.json`, `wifi-ordering.patch` and manifest. Preparation flags describe host preparation; device installation/testing must be recorded separately.

## Reproduce

Do not rerun the hash-guarded one-time implementation script. Exact sources are in `source-after/`. Sync canonical files into XNU, build with `outputs/scripts/build-a51-wifi-kernel.sh` under WSL, then run both `test-a51-wifi-recovery.py` and `test-a51-wifi-ordering.py` with this candidate's `--package-dir`. Package using `package-a51-wifi-recovery.py --base-dir outputs/wifi-stability-recovery --package-dir outputs/wifi-ordering-recovery` under WSL with absolute `/mnt/c/...` paths. Independently verify with `verify-a51-wifi-recovery.py` and the same directories on Windows or WSL. Repackaging regenerates epoch and changes payload/image/archive hashes.

## Device test and transition

The owner deliberately returned to TWRP and the candidate was installed as recorded above. ADB is unavailable during iOS; future recovery replacement still requires an Android/TWRP transition.

Restore saved recovery in Samsung Download Mode with `D:\Odin3_v3.14.4\Odin3_v3.14.4\Odin3_v3.14.4.exe`: AP only `C:\Users\Ankit\Documents\Codex\2026-11-21\hi-2\outputs\restore-current-recovery-RZ8N2032ZXE.tar.md5`; BL/CP/CSC empty; Re-Partition OFF; no PIT; Auto Reboot ON. If TWRP opens, choose Reboot → System without wiping. Keep USB connected. The guarded `install_a51.py --install-recovery --package-dir outputs/wifi-ordering-recovery` must pass live device/rollback checks, then write/read-back-verify only recovery. It does not reboot automatically. Do not reinstall the APFS system or app data.

The next run must verify private DHCP address/router/DNS and repeated Safari HTTPS access, then sustain traffic beyond the previous failure interval. Collect at least 20 minutes without a kernel stop. If another panic occurs, retain complete live panic/stack/queue records, reset confirmation, rejoin, RX progress and browser results. Host collection ending must never reboot iOS. Initial Safari success, association or RX resuming after reset alone does not establish stability.

Retest Instagram once Safari remains usable during the post-login loading-circle hang. A separate app/runtime issue remains possible. Preserve account/app data and original injection hooks; further app diagnostics should be bounded and avoid credentials/request bodies.
