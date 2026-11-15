# HakiOS for Samsung Galaxy A51 (SM-A515F)

Experimental Exynos 9611 port and research work package, maintained by [AnkitChoudhary-1](https://github.com/AnkitChoudhary-1). Based on the pinned [HakiOS common repository](https://github.com/oosexgang/hakios-xnu-kernel).

The A51 has executed a minimal XNU kernel and an open Darwin PID 1 test program on one Cortex-A53 CPU, with timer checks and three qualifying recovery/restore cycles. **Phase 4 is incomplete. This is a development source snapshot; a usable iOS interface has not booted.**

| Phase | Current evidence |
| --- | --- |
| 1 — Host build and audit | Pinned build and minimal open user program verified in QEMU |
| 2 — Experimental loader | Tiny payload execution and baseline return verified on the A51 |
| 3 — Minimal XNU | Single-core PID 1, timers and three recovery/restore cycles verified |
| 4 — Display, input, UFS | In progress; actual display/brightness, physical input and UFS reads remain unpassed |
| 5–10 | Planned: power/thermal, Mali graphics, Wi-Fi, audio, Bluetooth and full user-space integration |

The latest retained Phase 4 hardware trial failed both UFS reads with `rc=-4`, `OCS=7` and zero hashes. Older display/input success strings were withdrawn after source review. Native protocol models and platform QEMU results establish software behavior; they do not establish that the A51 peripherals work.

Start with [current status](docs/PUBLIC-STATUS.md), the [public build guide](docs/PUBLIC-BUILD.md), [publication scope](docs/PUBLICATION.md) and [roadmap](docs/ROADMAP.md). The [implementation log](docs/IMPLEMENTATION-LOG.md) preserves changes and failed attempts, with its historical status statements clearly marked.

The repository contains loader and platform sources, prototype drivers, Android diagnostic modules, host scripts, tests, source pins, cumulative A51 patches and selected result summaries. It excludes device backups, proprietary runtime/SDK files, vendor firmware and binary images. Existing scripts retain assumptions about the original Windows/WSL workspace; the build guide explains those limits.

This snapshot has not been registered or merged upstream. The root `device.conf` reports the observed device status; the shared XNU adaptations remain separate patches for future focused review.

Original host tools and standalone code use MIT where their file notices permit it. XNU-derived modifications retain APSL 2.0, and Android/Linux-derived changes retain GPL and their existing notices. See [NOTICE](NOTICE) and [licensing](THIRD_PARTY_LICENSES.md). HakiOS is independent of Apple and Samsung.
