# A51 UI performance experiment

Updated after the completed 15:34–15:40 UTC hardware collection on 21 November 2026. SM-A515F, Exynos 9611, serial RZ8N2032ZXE.

## Scope and measured starting point

The owner requests UI performance at 50–60 FPS only. Audio, third-party applications and charging development are paused. Existing packages and partition backups remain available.

The traced `render-fix/boot-tests/20261121T145756-026016Z/` run recorded 125 gestures and 4,041 frame copies. Many interactions ran at roughly 20–40 moving frames/s, with occasional segments near 50–60. The owner's feedback was "the ui is still laggy". The full record is that run's `hardware-evidence.json` and `frame-analysis.txt`, including separate long-stall statistics. No sustained target has been demonstrated.

A later `smooth-ui` package was already installed with matching recovery read-back at 15:19:12 UTC. Its completed run `boot-tests/20261121T152003-718051Z/` collected 330 seconds with no stop or reboot sent. That payload had no `touch_lat=1`; it cannot supply a comparable gesture FPS trace. Its logs confirm that the wallpaper became one picture and continue to show expensive GL frames. Cumulative GL frame times are not panel FPS measurements.

## Candidate: ui-performance

The candidate keeps all six component hashes identical to `smooth-ui` and `render-fix`: kernel, USB loader, root APFS, resident APFS, UEFI and DTB. Two configuration changes distinguish it from the installed `smooth-ui` package:

- `fbscale=2` draws 750×1624 instead of 1125×2436. Logical geometry stays 375×812 points and the iPhone X artwork subtype remains unchanged. This reduces rendered pixels by 55.6%; the 1080×2400 physical panel still requires a full scaled copy. Fine text and icons will be less sharp.
- `wallpaper_freeze=2` hides the wallpaper window, producing a plain background. At scale 2, `wallpaper_freeze=1` needs a previously persisted scale-3 wallpaper picture; `var_store=0` does not provide it. Removing the wallpaper avoids retaining its repeated rendering cost. Other app content remains active.

The existing status-bar fallback hook selects `_UIStatusBarVisualProvider_Split1125` for this configuration. Navigation and status-bar layout still require hardware checks. The rejected XR configuration (`fbsubtype=1792`, 828×1792) is not used.

Existing reduced motion/transparency, blur suppression and Control Center fade settings remain active. `fb_ca_hz=120` remains the advertised CoreAnimation rate because upstream documents half-rate rendering; the panel remains 60 Hz. `fb_threads=1` remains necessary: upstream A51 measurements found three workers slower when writing its write-combined framebuffer.

Clock requests retain their temperature and measured-rate guards. Hardware reports invalid ACPM frequency reads, so those guards have refused boosts. This candidate does not invent clock readings or bypass those guards. Rendering and GPU work, panel copying, thermal behavior and frame pacing must be measured separately; their overlapping trace durations cannot be summed into a latency budget.

## Build and verification

From the workspace in Windows:

```powershell
wsl -d A51-KernelBuilder -- python3 /mnt/c/Users/Ankit/Documents/Codex/2026-11-21/hi-2/outputs/scripts/prepare_boot.py --profile ui-performance
python outputs/scripts/verify-a51-ui-package.py
python outputs/scripts/run_diagnostic.py --prepare --package-dir outputs/ui-performance --trace-frames --manual-return
```

The Windows verifier checks every component checksum against the installed package, unique command arguments, scale and subtype policy, one worker, payload entries/bounds, embedded UEFI/payload/DTB, recovery size/hash, Odin recovery-only tar/MD5, and the original rollback hash. Its initial tracing-capacity check omitted the loader's command-line prefix and was invalidated by the hardware log; see the current result below. Its annotated result is `ui-performance/static-verification.json`. Preparation issued no phone commands. WSL's clock is about 5h30 ahead; the Windows runner regenerates the boot epoch before each run.

Prepared boot arguments request `loader_return_after=0`. The actual hardware command line truncated that argument; source inspection confirms that an absent argument also leaves the return timer disabled. APFS writes and persistent variable storage remain disabled. This is a performance candidate, not a verified 50–60 FPS build.

## Installation and controlled test

Historical reproduction procedure for this candidate: the owner restored Android, installation completed at 15:32:27 UTC with matching recovery read-back, and the test started at 15:34 UTC. Do not repeat this experiment: the owner has now stopped resolution and visual-effect changes.

```powershell
python outputs/scripts/install_a51.py --install-recovery --package-dir outputs/ui-performance
& 'C:\Android\platform-tools\adb.exe' -s RZ8N2032ZXE reboot recovery
python outputs/scripts/run_diagnostic.py --run --package-dir outputs/ui-performance --trace-frames --manual-return --seconds 360
```

Use the guarded installer; it verifies phone identity, original Android boot/GPT, backups, package and recovery read-back. Enter recovery freshly before the RAM boot. The 360-second window limits host collection only and never ends iOS.

Once Home appears, record the time/order of these interactions: open Settings and scroll its main list up/down ten times at a consistent pace; return Home with the bottom gesture three times; open/close top-right Control Center three times; repeat Settings scrolling after several minutes. Check readable labels, correct status bar, black content, freezes and heat. Record owner feedback and compare equivalent interactions with earlier traces. Wi-Fi is an inherited regression check, not a new development task.

Run `summarize-a51-render-test.py` on the completed run with the owner's actual feedback. Inspect all gaps, including those above 100 ms, repeated images and DECON frame replacements. The existing FPS script measures completion of copies to framebuffer memory; it excludes gaps at least 100 ms and cannot establish distinct scanouts. Do not declare sustained 50–60 FPS from its best segments alone. The target requires repeated scrolling and transitions close to 16.7–20 ms per presented frame with no recurrent stalls, corruption or thermal degradation.

## Return to Android

Open `D:\Odin3_v3.14.4\Odin3_v3.14.4\Odin3_v3.14.4.exe`. Select `C:\Users\Ankit\Documents\Codex\2026-11-21\hi-2\outputs\restore-current-recovery-RZ8N2032ZXE.tar.md5` in AP only. Leave BL/CP/CSC empty, Re-Partition off, no PIT, Auto Reboot on. After PASS, if recovery opens choose Reboot → System without wiping.

The original recovery image SHA-256 is `12412e2008d950260cda627ac7a6b8eac954b49ef9db5573a297f67e4fc85999`; the restore tar SHA-256 is `b19b680469b04d82622c22e27f29e4ede226256418cceab1c1934740b84274e5`. Backups are under `outputs/backups/RZ8N2032ZXE/`.

## Current result

Recovery installation and matching read-back passed. Run `ui-performance/boot-tests/20261121T153420-552848Z/` completed collection at 15:40:22 UTC; the last successful poll was `running 0 0` at 359 seconds. No stop or reboot was sent. The owner reports "still laggy" and requests stopping resolution reduction, blur suppression and animation changes. This candidate did not meet the requested result; sustained 50–60 FPS remains unverified.

The runtime log reports `cmdline: 607 of 607 characters` and ends in `loader_return_`. The loader prepends arguments that the host verifier did not budget for. Consequently `touch_lat=1` and the complete explicit return-timer argument were absent. Requested tracing in the manifest is not evidence of effective tracing, and no valid gesture FPS comparison can be made from this run. `xnu/files/osfmk/arm64/loader_return.c`, `loader_return_timer_init`, returns without scheduling a timer when `loader_return_after` is absent or zero. Manual return therefore remains effective by the kernel default.

No further device or rendering configuration changes are authorized by the latest question. The requested read-only Metal feasibility assessment is recorded in [A51-Metal-feasibility.md](A51-Metal-feasibility.md).
