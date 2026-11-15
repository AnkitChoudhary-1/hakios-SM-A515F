/* SPDX-License-Identifier: MIT */
ENTRY(_a51_loader_image_start)

SECTIONS {
    /* Exynos 9611 Android boot v2 kernel loads at 0x80080000 */
    . = 0x80080000;

    .text.entry : {
        KEEP(*(.text.entry))
    }

    .text : {
        *(.text .text.*)
    }

    .rodata : {
        *(.rodata .rodata.*)
    }

    .data.record : ALIGN(64) {
        *(.data.record)
    }

    .data.config : ALIGN(8) {
        *(.data.config)
    }

    .data.toc : ALIGN(4096) {
        KEEP(*(.data.toc))
    }

    .data.payload : ALIGN(4096) {
        KEEP(*(.data.payload))
    }

    .data : {
        *(.data)
    }

    .bss (NOLOAD) : ALIGN(16) {
        *(.bss .bss.*)
        *(COMMON)
    }

    . = ALIGN(4096);
    _a51_loader_image_end = .;

    /DISCARD/ : {
        *(.comment)
        *(.note*)
        *(.eh_frame*)
    }
}

