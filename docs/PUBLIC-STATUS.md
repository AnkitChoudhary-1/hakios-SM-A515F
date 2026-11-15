# Public snapshot status

This publication records the current decisions on 15 November 2026. Historical workspace documents retain their capture dates and may describe earlier failures or completion claims. This document, `state.json` and the selected summaries define the publication's status.

Phases 1–3 have selected completion evidence. Phase 3 ran the minimal open Darwin program as PID 1 on one Cortex-A53 CPU with XNU timers, attributable nonces and verified baseline restoration in three qualifying cycles. The [device summary](../validation/phase3-device-summary.json) contains selected observed log lines and the original report hash. It is a derived publication summary; complete raw evidence is retained locally and is not publicly replayable from this repository alone.

Phase 4 remains **in progress**, with its device gate **unpassed**. The trial `20261115T102436837863Z` completed one of three requested cycles and failed both 4 KiB and 64 KiB UFS reads (`s_rc=-4 s_ocs=7 m_rc=-4 m_ocs=7`, zero hashes). FMP/descriptor and inherited firmware-state explanations are hypotheses.

Remaining Phase 4 work:

- Reconcile the tested binary, exact sources and corrected-loader checks. Current manifests describe individual runs; a passing record is not automatically proof for newer exported sources.
- Demonstrate visible 1080×2400 display output and repeated physical brightness changes. The `0xCA000000` framebuffer remains an assumption.
- Demonstrate physical touch coordinates and debounced key press/release transitions. The retained touch-controller reference is HSI2C4 at `0x13870000`.
- Obtain genuine bounded UFS DMA reads with independent 4 KiB/64 KiB hash matches and validate larger-image loading.
- Verify write rejection through the actual submission path, then repeat complete qualifying hardware cycles with baseline restoration.

The shared UFS/input protocol models have passing native sanitizer records (45 UFS cases, 42 input cases). The platform has separate passing QEMU records. Read their exact source/build pins in `manifests/`; emulated MMIO and DMA cannot validate the peripherals.

Phases 5–10 remain planned. The target matching full user space is iOS/Darwin 16.5. The SDK is headers/stubs, and the complete runtime, SpringBoard and Safari are unavailable in the working project. No full iOS UI, GPU acceleration, Safari, Apple services or no-flash A51 launch is claimed.
