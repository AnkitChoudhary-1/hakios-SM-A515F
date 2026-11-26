import os
import re

# 1. Patch ramfs.c
ramfs_paths = [
    "/opt/a51-hakios/upstream-a51/hakios/xnu/files/bsd/miscfs/ramfs/ramfs.c",
    "/opt/a51-hakios/upstream-a51/hakios/xnu-src/xnu-8796.121.2/bsd/miscfs/ramfs/ramfs.c"
]

for path in ramfs_paths:
    if not os.path.exists(path):
        continue
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    if "ramfs_advlock" not in content:
        target1 = "static int\nramfs_offtoblk(struct vnop_offtoblk_args *ap)\n{\n\t*ap->a_lblkno = (daddr64_t)(ap->a_offset / PAGE_SIZE);\n\treturn 0;\n}"
        replacement1 = target1 + "\n\nstatic int\nramfs_advlock(__unused struct vnop_advlock_args *ap)\n{\n\treturn 0;\n}"
        if target1 in content:
            content = content.replace(target1, replacement1, 1)
        else:
            print(f"ERROR: target1 not found in {path}")
        
        target2 = "{ .opve_op = &vnop_offtoblk_desc, .opve_impl = (VOPFUNC)ramfs_offtoblk },\n\t{ .opve_op = (struct vnodeop_desc *)NULL, .opve_impl = (VOPFUNC)NULL }"
        replacement2 = "{ .opve_op = &vnop_offtoblk_desc, .opve_impl = (VOPFUNC)ramfs_offtoblk },\n\t{ .opve_op = &vnop_advlock_desc, .opve_impl = (VOPFUNC)ramfs_advlock },\n\t{ .opve_op = (struct vnodeop_desc *)NULL, .opve_impl = (VOPFUNC)NULL }"
        if target2 in content:
            content = content.replace(target2, replacement2, 1)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"Patched ramfs_advlock in {path}")
        else:
            print(f"ERROR: target2 not found in {path}")
    else:
        print(f"ramfs_advlock already present in {path}")

# 2. Patch hakios.a51audio.c
audio_paths = [
    "/opt/a51-hakios/upstream-a51/hakios/devices/a51/drivers/audio/hakios.a51audio.c",
    "/opt/a51-hakios/upstream-a51/hakios/xnu-src/xnu-8796.121.2/bsd/dev/hakios.a51audio.c"
]

for path in audio_paths:
    if not os.path.exists(path):
        continue
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # In a51audio_init, call hardware init (pinmux, clocks, abox) BEFORE tas2562_bringup
    old_init = """    /* 3. Bring up TAS2562 Smart Amp */
    tas2562_bringup();

    /* 4. Configure Exynos hardware pinmux, clocks, ABOX routing & DMA */
    a51_audio_hardware_init(cmu);"""
    
    new_init = """    /* 3. Configure Exynos hardware pinmux, clocks, ABOX routing & DMA first */
    a51_audio_hardware_init(cmu);

    /* 4. Bring up TAS2562 Smart Amp with running clocks and BCLK */
    tas2562_bringup();"""

    if old_init in content:
        content = content.replace(old_init, new_init, 1)
        print(f"Reordered hardware init and tas2562_bringup in {path}")

    # Update tas2562_bringup to use robust Android register configuration
    old_bringup_block = """    /* Full initialization sequence matching Android reference */
    amp_select(0, 0);
    amp_select(127, 0);
    amp_select(1, 1); /* Software Reset */
    delay(5000);

    amp_select(0, 0);
    amp_select(127, 0);
    amp_select(8, 0x10);  /* 16-bit I2S format, Left slot 0 */
    amp_select(11, 0x42); /* IV slot config */
    amp_select(12, 0x40);
    amp_select(6, 0x08);  /* 48 kHz sample rate auto-detect */
    amp_select(3, 0x14);  /* Playback Volume/Level (+14 dB safe audible level) */
    amp_select(7, 0x02);  /* Unmute left speaker */
    amp_select(48, 0x04); /* Unmute digital path */
    amp_select(2, 0x00);  /* Power operational mode: ACTIVE */
    amp_select(0x1a, 0x64);/* Boost configuration */
    amp_select(0x26, 0xf8);/* IRQ mask */
    amp_select(0x27, 0xb1);"""

    new_bringup_block = """    /* Full initialization sequence matching Android reference */
    amp_select(0, 0);
    amp_select(127, 0);
    amp_select(1, 1); /* Software Reset */
    delay(5000);

    amp_select(0, 0);
    amp_select(127, 0);
    amp_select(4, 0xcf);   /* MISCCONFIG0: retries enabled, IRQ pull-up */
    amp_select(0x0a, 0x03);/* TDMConfigurationReg4: Exynos format */
    amp_select(6, 0x08);   /* 48 kHz sample rate auto-detect */
    amp_select(7, 0x02);   /* TDMConfigurationReg1: I2S 1 BCLK delay, rising edge */
    amp_select(8, 0x10);   /* TDMConfigurationReg2: 16-bit I2S format, Left slot 0 */
    amp_select(3, 0x14);   /* Playback Volume/Level (+14 dB safe audible level) */
    amp_select(0x38, 0x00);/* CLOCKCONFIGURATION: auto clock rate detect */
    amp_select(0x30, 0x04);/* Clear latched IRQ */
    amp_select(0x1a, 0x00);/* Unmask IRQs */
    amp_select(2, 0x00);   /* Power operational mode: ACTIVE */"""

    if old_bringup_block in content:
        content = content.replace(old_bringup_block, new_bringup_block, 1)
        print(f"Updated tas2562_bringup registers in {path}")

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

# 3. Patch hakios.a51battery.c
battery_paths = [
    "/opt/a51-hakios/upstream-a51/hakios/devices/a51/drivers/power/hakios.a51battery.c",
    "/opt/a51-hakios/upstream-a51/hakios/xnu-src/xnu-8796.121.2/bsd/dev/hakios.a51battery.c"
]

for path in battery_paths:
    if not os.path.exists(path):
        continue
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    old_b_init = 'if (!PE_parse_boot_argn("a51battery",&stage,sizeof(stage)) || !stage) return;'
    new_b_init = 'if (!PE_parse_boot_argn("a51battery",&stage,sizeof(stage))) { stage = 2; }\n    if (!stage) return;'

    if old_b_init in content:
        content = content.replace(old_b_init, new_b_init, 1)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Defaulted a51battery stage=2 in {path}")
    else:
        print(f"a51battery init already patched or different in {path}")

print("Kernel driver patches applied successfully.")
