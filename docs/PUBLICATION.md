# Publication scope and provenance

The user authorized publishing the current A51 work to `AnkitChoudhary-1/hakios-SM-A515F`. The export is a separate snapshot under the local project's `publication/` directory. It does not alter the active platform sources, Android projects, backups or phone.

Included: authored source and tests in `scripts/`, `prototype/`, `drivers/`, `diagnostics/` and `userland/`; comprehensive historical Markdown documentation; selected source/build manifests; independently pinned cumulative Phase 3/4 common and XNU differences; MIT/APSL/GPL license texts; a derived Phase 3 device summary; and public validation records.

Excluded: full `evidence/` and `runs/` trees, live Android logs and inventory dumps, `console_ramoops.txt`, device/partition backups, vendor firmware, Apple runtime and SDK material, generated executables and image/archive build outputs, unrelated Android kernel projects, and personal device serials/MAC addresses.

The publication sanitizes personal device identifiers and repairs local application Markdown links. `PUBLICATION-MANIFEST.json` records the original and exported file hashes, transformations, captured source inputs and each patch's before/after file identities. Publication summaries and sanitized text are separate artifacts; their hashes do not replace the original hardware evidence's hashes.

## Retained evidence

The full local evidence archive remains authoritative for strict replay. References to absent `evidence/`, `runs/`, original backup images and WSL source/build directories in historical documents describe retained local records. They are not claims that those inputs ship in this repository. App-local links into excluded folders resolve here so readers can understand the missing prerequisite.

The selected Phase 3 device summary records three original qualifying cycles, their nonces/image hashes and a short allowlist of observed PID 1/platform/timer/exit lines. Complete Android logs and the complete original report are excluded. Current Phase 4 passing native/QEMU manifests may precede newer source changes; match their source and build hashes before attributing a result to this export.

## Upstream contribution

This push publishes the work package in the maintainer's repository. No PR, device-manifest registration or merge into HakiOS is performed by this publication. Future upstream contributions should follow the pinned common `CONTRIBUTING.md` and device-publishing guide: validate the device layout, pin the device repository revision, and propose shared improvements as focused changes with honest execution evidence.

The A51 platform still uses shared kernel adaptations and `soc none` in its temporary device descriptor. A complete upstream Exynos SoC/device packaging pass is planned; do not treat this source snapshot as an already integrated upstream device.

## Initial publication checks

The exported sources passed 36 boot-format tests and both native ASan/UBSan
models: 45 UFS cases with 90,825 checks and 42 input cases with 20,620 checks.
Syntax checks parsed 188 Python files and five shell scripts. All four
cumulative patches applied to temporary baseline trees and produced the
expected hashes for all 41 changed files. See
[portable host results](../validation/public-smoke.json) and
[patch results](../validation/patch-checks.json) for the exact tested identities.

The final publication manifest includes these records and the exported file
hashes. Actual staged Git blobs must match that manifest and pass the text,
JSON and device-identifier/credential-pattern scan before publication. These
checks establish the source package's integrity; Phase 4 hardware
qualification remains pending.
