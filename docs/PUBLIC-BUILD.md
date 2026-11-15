# Building and reviewing the public snapshot

This is a source work package tied to a pinned common HakiOS checkout. It does not include an installable phone image. The original build used Ubuntu 24.04 in the `A51-KernelBuilder` WSL distribution, LLVM/clang 18, Python 3, QEMU and `/opt/a51-hakios` for isolated source/build directories.

## Portable host checks

From this repository on Linux/WSL, with `clang-18` and `bash` installed:

```sh
python3 scripts/run.py --label public-smoke -- python3 scripts/public-smoke.py
```

This parses the Python and shell sources, executes the existing boot-format tests and compiles/runs the shared UFS/input models with ASan/UBSan. It does not query or mutate a phone. Its logs and temporary programs remain local. The initial publication's check results are under `validation/`.

After preparing the pinned common/native baseline described below, the
publication's patch checks can be repeated with:

```sh
python3 scripts/run.py --label public-patch-checks -- python3 scripts/validate-publication.py patches --baseline COMMON_REPO
```

This materializes the affected baseline files in temporary directories,
checks and applies all four patches there, then verifies every resulting file
hash. It leaves the original upstream checkout untouched. The stored check
results include the patch hashes and exact validation scope.

## Source baseline and A51 patches

The common baseline is `63fc2b4633bac3af8e57dadab9f5a8d4cb940438` from `oosexgang/hakios-xnu-kernel`. XNU is `xnu-8796.121.2`, commit `c54f35ca767986246321eb901baf8f5ff7923f6a`. `manifests/source-lock.json` and `manifests/dependencies.json` retain the dependency identities. These records reference local paths; the downloaded dependencies themselves are excluded.

Use a **separate** common checkout at the pinned commit. Follow its setup instructions and supply any licensed SDK inputs locally. Run the upstream `xnu/apply.sh` first to prepare the common XNU tree. Both A51 patch sets are cumulative from that prepared Phase 1 baseline; select Phase 3 **or** Phase 4 in each isolated checkout.

For the experimental Phase 4 snapshot, after replacing `PUBLIC_REPO` and `COMMON_REPO` with your directories:

```sh
git -C COMMON_REPO apply --check PUBLIC_REPO/patches/phase4-common.patch
git -C COMMON_REPO/xnu-src/xnu-8796.121.2 apply --check PUBLIC_REPO/patches/phase4-xnu.patch
git -C COMMON_REPO apply PUBLIC_REPO/patches/phase4-common.patch
git -C COMMON_REPO/xnu-src/xnu-8796.121.2 apply PUBLIC_REPO/patches/phase4-xnu.patch
```

Substitute `phase3` in both filenames for the completed minimal platform snapshot. The XNU patches extend HakiOS's generated baseline; they are not claimed to apply directly to pristine Apple XNU. Future upstream contribution must export and review the appropriate final XNU patch against Apple's tag.

Select `devices/a51/configs/a51_defconfig` using the pinned common tree's configuration tools. See the retained [build runbook](BUILD.md), [Phase 3 platform guide](PHASE-3-PLATFORM.md) and [Phase 4 device-path guide](PHASE-4-DEVICE-PATH.md) for the original command sequence and recovery design.

## Workspace-specific limits

Many historical scripts use `C:/Users/Ankit/Desktop/A51/hakios-a51`, its `/mnt/c/Users/Ankit/Desktop/A51/hakios-a51` counterpart and timestamped `/opt/a51-hakios/experimental/` directories. Configure those assumptions for a new checkout before using the original build/capture scripts. The portable check above derives its root from its own file.

Hardcoded personal device serials have been replaced with `A51_SERIAL_HERE`. Baseline/image hashes and partition numbers refer to the original research device and are historical evidence, not values to reuse on another phone. Complete raw packets, exact historical binaries and the original Android backups are not included, so original evidence-replay and candidate-packaging scripts cannot run from this clone alone.

`phase*-device-*`, hardware gate, candidate execution and restore scripts can write or reboot a phone. Publication validation runs only host checks and patch checks. Hardware experiments require a separately prepared matching-device baseline and the documented recovery procedure; the publication does not establish readiness for installing a daily-use system.
