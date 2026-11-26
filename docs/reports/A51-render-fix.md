# A51 iOS rendering correction

Updated 21 November 2026, 15:29 UTC. Device SM-A515F / Exynos9611.

## Hardware evidence

The `device-services-layout-fix` run `boot-tests/20261121T143245-555261Z/` completed 360 seconds of host collection, with the last poll reporting `running 0 0`. No stop or reboot was sent. Collection ending does not end iOS.

Backboardd reported 1125×2436, scale 3; `screen-008.png` shows the iPhone X status bar, bottom home indicator and readable Settings labels. The owner still reported intermittent black boxes, uneven animation and no sound. Home and top-right Control Center gestures were not explicitly confirmed in that reply.

The GL bridge reported that its fixed 256-entry table of IOSurface texture bindings was full. The snapshots contain 54 distinct failed attachment texture IDs. Those failures are a concrete candidate for missing/black UI content, but other rendering defects remain possible. The frame analyzer recovered 114 gestures and 3,609 displayed frames; this uncontrolled run does not demonstrate sustained 50–60 FPS. The analyzer's draw/GPU/idle decomposition overlaps pipelined work and includes negative idle values; it must not be interpreted as an additive latency budget. A count of zero logged GPU wait events does not establish that no GPU waiting occurred.

Exact log hashes, diagnostics, feedback and the completed collector manifest are recorded in that run's `hardware-evidence.json`. The full frame analysis is in `frame-analysis.txt`.

## Change

`render-fix/` replaces the fixed IOSurface binding table in `userland/src/eagl.c` with a heap allocation that grows geometrically. Existing bindings survive allocation failure. Texture deletion compacts the live entries and releases surface/mirror references; context destruction releases retained surfaces and table storage. It does not evict live bindings to make room.

The package preserves iPhone X geometry and artwork. It adds `fb_ca_hz=120` independently of screen dimensions: upstream documents CoreAnimation drawing at half its advertised rate in this port. This is a pacing experiment, not evidence of 60 FPS on the A51. Panfrost, Wi-Fi, the battery monitor, audio diagnostics and manual return remain enabled. Kernel, loader, UEFI and DTB hashes match `device-services-layout-fix` exactly.

Charging control and speaker playback remain unimplemented in this package. The charger watchdog has expired in hardware logs; a charging icon is not evidence of battery charging. The TAS2562 amplifier remains held in reset and no PCM speaker path is available.

## Validation and reproduction

In WSL `A51-KernelBuilder`, run these scripts from the Windows workspace via `/mnt/c/Users/Ankit/Documents/Codex/2026-11-21/hi-2/outputs/scripts/`:

1. `python3 enable-a51-render-fix.py` records source before/after, a patch and hashes, then applies the rendering change.
2. `python3 test-a51-render-fix.py` compiles the actual table functions with ASan/UBSan. It passed 2,049 simultaneous bindings, four growth boundaries, allocation failure, replacement, middle deletion and 100 allocation/deletion reuse cycles. Mock GL/CF handles verify lifetime, not actual rendering.
3. `bash build-a51-render-fix.sh` rebuilds userland with the preserved firmware/job configuration. Compilation passed. `apfsck` found the root and flashboot images clean; all 499 root entries and eight flashboot entries were read back and matched the staging trees. The staged GL library contains the new capacity diagnostics; its SHA-256 is `9794b92b5266cf3773364ed67ae7e4349070fb97e7f70e49c931fc3b056ee946`.
4. `python3 prepare_boot.py --profile render-fix` builds the isolated package. Independent Windows checks verified all component hashes, payload entries and bounds, image hashes, Odin archive contents/MD5, unchanged kernel/firmware hashes, default geometry, pacing argument and manual-return argument. Diagnostic recovery SHA-256: `aff066578167ffa216733505a1923c36dde5ed3452583af9f67ad1478e2ec8db`.

Recovery installed at 2026-11-21T14:55:39.383068+00:00 with matching partition read-back. Hardware collection completed in `render-fix/boot-tests/20261121T145756-026016Z/`, with 125 gestures and 4,041 traced frame copies. The owner reported that the UI was still laggy. Many interactions measured approximately 20–40 FPS; occasional 50–60 FPS segments do not demonstrate sustained performance. The binding table grew from 256 to 512 entries, with no exhaustion or failed attachment IDs observed in these snapshots. This does not establish that all black boxes are fixed.

The run's `hardware-evidence.json` retains gaps above 100 ms separately from the upstream moving-frame FPS calculation. Frame-copy completions do not prove distinct panel scanouts; pending DECON frames may be replaced. No sustained 50–60 FPS claim is made.

Reproduction: when Android is running, the guarded installation command is `python outputs/scripts/install_a51.py --install-recovery --package-dir outputs/render-fix`. Enter recovery freshly, then run `python outputs/scripts/run_diagnostic.py --run --package-dir outputs/render-fix --trace-frames --manual-return --seconds 360`. Every payload uses `loader_return_after=0`; the six minutes bounds host collection only.

Acceptance requires a repeated Settings/Home/Control Center tour without the old table-exhaustion warnings or black content, correct navigation, working Wi-Fi, and a measured comparison of matched gestures. No FPS or black-box fix is claimed before that test.

## Android return

Use `C:\Users\Ankit\Documents\Codex\2026-11-21\hi-2\outputs\restore-current-recovery-RZ8N2032ZXE.tar.md5` in Odin AP only, with BL/CP/CSC empty, Re-Partition off, no PIT and Auto Reboot on. If recovery opens, select Reboot → System without wiping. Original partition backups and previous packages are preserved.

Timestamp provenance: WSL currently reads approximately Windows local time as UTC (about 5h30 ahead); rendering source/test records retain that original timestamp and a normalized Windows UTC timestamp. Device boot payload epochs are regenerated by the Windows runner.

## Current owner scope

Speaker, charging and third-party app work are paused. The isolated follow-up documented in `A51-UI-performance.md` completed hardware collection with owner-reported lag and ineffective tracing due to command-line truncation. The owner has stopped resolution, blur and animation experiments. The current request is an explanation of full-quality performance alternatives and Metal feasibility, recorded in `A51-Metal-feasibility.md`; no new rendering implementation or device change has begun.
