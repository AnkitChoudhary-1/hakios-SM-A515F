# Galaxy A51: first experimental iOS 16.5 test

Prepared on 2026-11-21 for **SM-A515F / RZ8N2032ZXE / A515FXXU8HWI5**. **The first five-minute iOS boot test succeeded; Android has now been restored as requested.** Captures show Control Center and the Phone keypad, and the owner confirmed home screen and touch. The saved Android recovery was restored through Odin; its full hash and unchanged Android boot were verified over rooted ADB. Diagnostic recovery is no longer installed. See [A51-first-boot-result.md](A51-first-boot-result.md) and `return-to-android.json`.

This prepares a five-minute HakiOS kernel session with software rendering and touch. GPU acceleration, Wi-Fi, UFS writes, and persistent variable storage are disabled. SpringBoard UI rendering was captured; the home screen and touch were confirmed by the owner. Calls, cellular data, audio, Bluetooth, camera, and battery/PMIC support are unavailable in the selected configuration.

## Exactly what installation changes

1. `--install-system` writes **8,365,539,328 bytes** to the existing `/dev/block/by-name/darwin` (`sda33`). This replaces the prior experimental filesystem. The remaining 2,373,955,584 bytes of that partition are not written.
2. `--install-recovery` writes **25,749,504 bytes** to `/dev/block/by-name/recovery` (`sda13`). This replaces the current recovery boot image with the diagnostic UEFI/XNU image. The rest of the partition is not written.

The installer verifies the exact device, GPT copies, partition GUID/range, backup checksums, image capacity, staging checksum, and partition read-back. It uses the existing partition layout. Android's `boot` partition and userdata are not installation targets. Installation temporarily stages an image in `/data/local/tmp`; it removes that staging file after successful verification. A failed action may leave that file for inspection.

The complete current darwin, boot, recovery, and GPT backups are under `backups/RZ8N2032ZXE/`. Keep them until testing and restoration are finished. They preserve the phone's current modified state; they are not factory firmware.

## Installation procedure (already completed for this phone)

Leave Android running, root available, and USB debugging connected. Use Windows PowerShell in the workspace:

```powershell
Set-Location -LiteralPath 'C:\Users\Ankit\Documents\Codex\2026-11-21\hi-2'
python.exe outputs\scripts\install_a51.py --check
python.exe outputs\scripts\install_a51.py --install-system
python.exe outputs\scripts\install_a51.py --install-recovery
```

Run each command only after the previous command succeeds. If a check or write fails, stop and read the error; do not proceed to the next install action. Recovery installation additionally verifies the installed Apple system region. These scripts do not reboot automatically. Successes are recorded in `device-action-history.jsonl`.

## Enter diagnostic recovery and collect a fresh test

The iOS system installation passed, but diagnostic recovery was subsequently rolled back to return to Android. For any future authorized test, reinstall diagnostic recovery with `install_a51.py --install-recovery`, then enter it freshly. Do not run the kernel twice in one loader session:

```powershell
& 'C:\Android\platform-tools\adb.exe' -s RZ8N2032ZXE reboot recovery
& 'C:\Android\platform-tools\fastboot.exe' devices
& 'C:\Android\platform-tools\fastboot.exe' -s xnuloader getvar product
python.exe outputs\scripts\run_diagnostic.py --run
```

The expected USB serial/product is `xnuloader`, version `0.5`. This generic loader serial is different from Android's device serial. Connect only this prepared test phone while collecting. Samsung Download Mode is a different interface and does not accept these fastboot commands.

If USB initialization succeeds, the diagnostic image waits in the loader. The collector first requires `result: idle`, saves the initial log, stages a fresh-epoch payload into RAM, and sends one `oem run`. The payload includes the kernel, boot helper, and resident initial-root filesystem. It then collects logs about every 15 seconds and screenshots about every minute, with bounded command timeouts. Captures and command transcripts are saved under `boot-tests/<UTC timestamp>/`.

The requested kernel runtime is 300 seconds; the host collector allows up to 330 seconds. A normal USB-mode return leaves the loader available. The collector does not stop or reboot the phone. The first run completed this timed return; further runs require a fresh recovery boot. A successful loader result or capture alone does not prove iOS is usable; inspect the logs and screenshot before recording home-screen success.

If fastboot cannot see the loader, check Device Manager for the new USB interface and use the Android Bootloader Interface driver from the installed Android USB driver package if available. Preserve any visible phone message. If loader USB startup fails, the source falls through to an automatic attempt with the embedded kernel, then a reset; a firmware or kernel hang may prevent that normal return. Do not flash a different image solely because Windows has not bound the USB driver.

To collect an already running test without requesting another kernel start:

```powershell
python.exe outputs\scripts\run_diagnostic.py --collect
```

Use a fresh recovery boot between kernel attempts. The port documents CPU-off limitations; the script rejects a second run in a firmware session whose result is no longer `idle`.

## Return to Android

Android is currently running after restoring saved recovery. The following commands document the loader reset attempt; on this phone it returned to recovery and required the Odin fallback below. For a future loader session, if `getvar result` reports `returned ...`, the reset command is shown below. If a later test is still running after captures are saved, a responding loader accepts:

```powershell
& 'C:\Android\platform-tools\fastboot.exe' -s xnuloader oem stop
& 'C:\Android\platform-tools\fastboot.exe' -s xnuloader getvar result
```

Wait for a result that no longer starts with `running`, then reset with:

```powershell
& 'C:\Android\platform-tools\fastboot.exe' -s xnuloader reboot
```

Observed on this phone: `fastboot reboot` returned to xnuloader instead of Android. A button restart opened the UEFI menu; Power off and a USB-disconnected start also returned to the loader. Do not assume a cold reset clears the recovery selection. The owner restored the verified saved Android recovery through Odin as described below. Android then booted; rooted ADB, boot completion, the restored recovery hash and unchanged Android boot hash were verified. If saved recovery opens during a future restore, choose Reboot -> System without wiping. See `return-to-android.json`.

## Restore the saved current state

With Android running again and rooted ADB available, these explicit actions restore the saved partitions:

```powershell
python.exe outputs\scripts\install_a51.py --restore-recovery
python.exe outputs\scripts\install_a51.py --restore-darwin
```

Recovery restoration writes the full saved **71,106,560-byte** image. Darwin restoration writes the full saved **10,739,494,912-byte** partition image. Both check the backup and verify the read-back. Restoring recovery alone removes the diagnostic recovery entry; restoring darwin also restores the earlier experimental filesystem and partition tail. Restore actions require this phone's GPT and Android boot to match the verified original session state.

If rooted Android is unavailable, a recovery-only Odin restore archive is prepared:

`restore-current-recovery-RZ8N2032ZXE.tar.md5`

Enter Samsung Download Mode using the A51's standard button sequence: with the phone off, hold both volume buttons while connecting USB to the PC, then confirm the warning with Volume Up. In Odin, put this archive in **AP**, leave **Re-Partition disabled**, and do not select a PIT or other partition files. Keeping Auto Reboot off lets you choose the next boot manually. The archive contains only `recovery.img`. This fallback restores recovery; it does not restore darwin and does not guarantee recovery from failures in unrelated firmware.

The separate `hakios-a51-ios16.5-timed-boot-RECOVERY.tar.md5` is an alternative automatic kernel-attempt package. It has been statically validated but is **not selected for the first test**. Use the diagnostic package to obtain evidence before changing the boot recipe.

## Records to update after testing

Update `A51-iOS16.5-build-notes.md` with the actual install/restore result, test timestamp, loader result, last kernel messages, observed display/touch behavior, and any changes to boot arguments. Preserve the original manifests and captures. Record “home screen verified” only after examining an actual screenshot or direct on-device observation.
