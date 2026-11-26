# Connect the A51 diagnostic loader on Windows

Resolved on 2026-11-21: the owner manually selected Android Bootloader Interface from Google’s signed driver package. Windows now reports problem code 0 and driver version 11.0.0.0; fastboot communicates with `xnuloader`. The first XNU test reached iOS UI. The steps below document the original Code 28 fix for reproducibility; no repeat driver installation is needed while the interface works.

The official Google USB driver was downloaded from:

https://dl.google.com/android/repository/usb_driver_r13-windows.zip

The unmodified signed package is prepared in:

`C:\Users\Ankit\Documents\Codex\2026-11-21\hi-2\outputs\Windows-USB-driver`

Its INF is `android_winusb.inf`. The stock INF does not list the loader's custom PID D00D, so automatic driver matching may find no driver. Select the Android Bootloader Interface model explicitly.

1. Leave the A51 connected at its loader screen. Open **Device Manager** from the Windows Start menu.
2. Find **xnuloader**, usually under **Other devices**. Right-click it and choose **Update driver**.
3. Choose **Browse my computer for drivers**, then **Let me pick from a list of available drivers on my computer**.
4. If a device-type list appears, select **Show All Devices**, then **Next**.
5. Choose **Have Disk**, then **Browse**, and select:

   `C:\Users\Ankit\Documents\Codex\2026-11-21\hi-2\outputs\Windows-USB-driver\android_winusb.inf`

6. Choose **Android Bootloader Interface** and install it. Windows may ask for administrator authorization and warn that the selected model is not an automatic hardware-ID match. This is the manual binding of Google's WinUSB driver to the loader's fastboot interface. Confirm that you selected **xnuloader**, not the Samsung Android ADB interface or another device.
7. Verify `fastboot devices` lists `xnuloader`, then follow [A51-first-boot-guide.md](A51-first-boot-guide.md). Use a fresh recovery boot for each kernel test.

Do not edit the INF, disable signature enforcement, or change Windows security settings. If Windows refuses the unmodified package, report the exact message so the next action can be based on that failure.

The assistant's computer-use helper could not start: `windows sandbox failed: CreateProcessWithLogonW failed: 1920`. This prevents desktop automation here; it does not describe a phone fault.
