#!/usr/bin/env python3
"""Set up Samsung Galaxy A51 device profile and defconfig in HakiOS kernel tree."""
from pathlib import Path
import subprocess
import sys

ROOT = Path("/opt/a51-hakios/src/hakios-xnu-kernel")
DEV_DIR = ROOT / "devices/a51"
CONFIGS_DIR = DEV_DIR / "configs"

DEV_DIR.mkdir(parents=True, exist_ok=True)
CONFIGS_DIR.mkdir(parents=True, exist_ok=True)

DEVICE_CONF = """# devices/a51/device.conf: Samsung Galaxy A51 (SM-A515F / Exynos 9611)

device a51
	title       Samsung Galaxy A51 (SM-A515F)
	vendor      Samsung
	soc         none
	defconfig   a51_defconfig
	maintainer  HakiOS Team
	status      display     missing   Phase 4 DECON/DSIM driver planned
	status      touch       missing   Phase 4 Melfas touch driver planned
	status      buttons     missing   Phase 4 power/volume buttons planned
	status      storage     missing   Phase 4 UFS block driver planned
	status      audio       missing   Phase 8 ABOX driver planned
	status      network     missing   Phase 7 SCSC WLBT driver planned
	status      gpu         missing   Phase 6 Mali-G72 driver planned
"""

A51_DEFCONFIG = """# HakiOS defconfig for Samsung Galaxy A51 (SM-A515F / Exynos 9611)
# Starts from common kernel and open profile; leaves out unsupported foreign drivers.
#include common_defconfig
#include open.config
CONFIG_DEVICE="a51"
# CONFIG_UFS is not set
# CONFIG_TOUCHSCREEN is not set
# CONFIG_HAKIOS_GOODIX is not set
# CONFIG_HAKIOS_BUTTONS is not set
# CONFIG_HAKIOS_UFS is not set
# CONFIG_HAKIOS_ADRENO is not set
# CONFIG_HAKIOS_CAMERA is not set
# CONFIG_HAKIOS_TORCH is not set
# CONFIG_HAKIOS_HAPTIC is not set
# CONFIG_HAKIOS_ADSP is not set
# CONFIG_HAKIOS_SPEAKER is not set
# CONFIG_HAKIOS_SOUND is not set
# CONFIG_HAKIOS_MIC is not set
# CONFIG_HAKIOS_BATTERY is not set
# CONFIG_HAKIOS_CPUFREQ is not set
# CONFIG_HAKIOS_THERMAL is not set
# CONFIG_HAKIOS_PMIC is not set
# CONFIG_HAKIOS_BATTGUARD is not set
# CONFIG_HAKIOS_SOCINFO is not set
# CONFIG_HAKIOS_WIFI is not set
# CONFIG_HAKIOS_BT is not set
# CONFIG_HAKIOS_QMI is not set
# CONFIG_HAKIOS_MODEM is not set
"""

(DEV_DIR / "device.conf").write_text(DEVICE_CONF, encoding="utf-8")
(CONFIGS_DIR / "a51_defconfig").write_text(A51_DEFCONFIG, encoding="utf-8")

manifest = (ROOT / "devices/manifest.conf").read_text(encoding="utf-8")
if "device a51" not in manifest:
    manifest += "\ndevice a51\n\tpath        devices/a51\n"
    (ROOT / "devices/manifest.conf").write_text(manifest, encoding="utf-8")

print("Files written successfully.")
res = subprocess.run([sys.executable, str(ROOT / "tools/hakios-device.py"), "check", "a51"],
                     cwd=ROOT, capture_output=True, text=True)
print(res.stdout)
print(res.stderr)
sys.exit(res.returncode)

