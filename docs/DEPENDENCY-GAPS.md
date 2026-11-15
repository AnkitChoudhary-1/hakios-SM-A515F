> Publication note: this is a historical workspace document. Current completion decisions are in [PUBLIC-STATUS.md](PUBLIC-STATUS.md); raw local evidence is described in [PUBLICATION.md](PUBLICATION.md).

# Dependencies, source-layout audit and feature gaps

Audit date: 10 November 2026. Repository statements below are upstream claims, not A51 test results. `manifests/research-audit.json` records the exact complete tree snapshots and hashes used.

## Pinned source layout

| Repository | Examined commit | Finding |
|---|---|---|
| Common HakiOS | `63fc2b4633bac3af8e57dadab9f5a8d4cb940438` | Full build checkout; QEMU baseline, common drivers, Qualcomm-oriented graphics; no A51/Exynos port found |
| Common MTK branch | `c36d664121623009962254a7e7ff06ec91530884` | Legacy `mtkloader/`, `xnu/files/bsd/dev/redwood_mali.c`, `userland/src/metal/`, Mesa/Panfrost patches |
| MT6768 device | `ad65e1f4b3ba479e9d7ada98f17398b83cc6f285` | Infinix Hot 20 / Mali-G52 reference; README describes a newer common-tree layout |
| hakios-metal | `d36f329e2684a1968b7c1a0ceee1661472cb707a` | Adreno-oriented common Metal implementation |
| hackios-xnu-userland | `2573c4a8d80ed143e534d16b5a386efa5b06ccbb` | README pointer to moved repository; no runtime distribution |

The device README says `mtk/loader/` and `mtk/mt6768/` exist in the common MTK branch. They are absent at the examined branch commit; the legacy paths above exist. This discrepancy is resolved for our baseline by using the exact pinned tree, not assuming the README matches its layout. A future upstream change requires a new audit.

The README also states that the working MTK Mesa/Metal user space still uses `kern.redwood.*` and `RedwoodMali` and is not yet in the common tree. Partial legacy components are public in the pinned MTK branch. Their existence prevents a blanket claim that Mali code is absent, but does not establish a complete, integrated and reproducible G72/iOS stack. We have not built those MTK components. Identify the matching user-client ABI, Panfrost version/patches, shader path, Metal plugin and compositor interfaces before planning reuse in Phase 6.

## Host build availability

| Input | Status | Evidence/qualification |
|---|---|---|
| Apple XNU 8796.121.2 and HFS 627.100.6 | Acquired, pinned | Source lock; generated XNU includes HakiOS overlays |
| AvailabilityVersions, libdispatch/firehose, pthread, bootstrap/MIG, tcsh, unifdef | Acquired, pinned | Source lock; support libraries built locally |
| Ubuntu clang/lld/llvm, flex/bison, UUID/zlib headers | Installed | Package manifest; missing UUID/dsymutil/python command issues recorded |
| Mach-O cctools toolchain | Acquired | Immutable release URL plus retained local archive hash |
| iPhoneOS16.5 SDK | Acquired, pinned | Theos sparse SDK checkout; build headers/stubs only |
| macOS13.3 Kernel.framework headers | Acquired | Archive checked against release checksum; only required framework extracted |
| QEMU/AAVMF/iPXE ROM | Installed | Package manifest and QEMU logs |
| Minimal open hello runtime | Built locally | Raw system calls; no proprietary iOS binaries needed |

SDK redistribution/authenticity is not inferred from a local checksum. Archive acquisition is pinned for repeatability; Ubuntu packages are version-recorded rather than a frozen repository snapshot.

## Darwin interface and Safari

The common `sysimage/unpack.sh` targets `iPhone10,3,iPhone10,6_16.5_20F66_Restore.ipsw`, expected size 6,165,698,198 bytes. It selects system files, OS/App cryptex contents and an identity device tree. Phase 1 has not acquired, unpacked or built this runtime. Placeholder identity is sufficient for hello and is explicitly unsuitable as proof of a full Darwin interface.

| Component | Current status | Work still required |
|---|---|---|
| Matching iOS/Darwin 16.5 runtime, dyld/cache/frameworks | Not supplied to this workspace | Identify and supply matching inputs; retain provenance; validate extracted-image tools and layout |
| launchd jobs and writable state | Compatibility sources exist; full images unbuilt | Build root/system images and RAM session state; verify IPC/process/service startup |
| SpringBoard/backboardd/CoreAnimation | Runtime unavailable locally | Integrate display/input/IOSurface/graphics services after device foundations |
| Safari/WebKit/JavaScriptCore and cryptex contents | Runtime unavailable locally | Match app/framework/service dependencies, certificates, DNS/TLS, subprocesses and page fixtures |
| Mali-G72 Mesa/Metal bridge | Partial reference pieces; complete A51 path unproven | Port GPU MMU/jobs/cache/fences and user-client ABI; validate rendering/compositor |
| Apple ID, activation, iCloud, App Store | Outside upstream support and first-release scope | No plan or claim of support |

Safari is not obtained by compiling XNU or copying SDK headers. A browser launching on another phone does not validate it here. Charging, radios, audio and graphics must each be established before the release's combined-use and frame-time suite. Upstream's own POCO performance figures vary with rendering resolution and do not guarantee native A51 60 fps.

## A51 hardware readiness

Android/Linux baseline works on the connected phone. No A51 XNU hardware feature has been implemented or tested in Phase 1: boot, display/touch, storage, charging/thermal, Mali rendering, Wi-Fi, Bluetooth, audio, Safari and stable 60 fps all remain unverified. DEVICE-BASELINE.md distinguishes live evidence from selected Linux references.

The live exact PCB revision, full firmware inventory/hashes and reserved-memory map remain pending access that can read them. ADB `su -c id` failed; boot-state properties conflict with retained custom-kernel/recovery history. Retained images and source establish traceable inputs for investigation, not actual unlock or safe placement.

No-flash RAM execution is still a Phase 2 research task. The retained Android configuration disables kexec. QEMU's RAM payload launch, MTK's persistent boot shim and Qualcomm fastboot procedures do not establish a Samsung A51 RAM launch.
