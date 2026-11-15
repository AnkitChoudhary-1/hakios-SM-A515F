/* SPDX-License-Identifier: MIT */
ENTRY(_start)
SECTIONS {
    . = 0x80080000;
    .text.entry : { KEEP(*(.text.entry)) }
    .text : { *(.text .text.*) }
    .rodata : { *(.rodata .rodata.*) }
    .data : { *(.data .data.*) }
    .bss (NOLOAD) : ALIGN(64) { __bss_start = .; *(.bss .bss.*) *(COMMON) . = ALIGN(64); __bss_end = .; }
    ASSERT(. < 0x80200000, "return code/context/stack must fit native TTBR0 identity block")
    .toc : ALIGN(4096) { KEEP(*(.toc)) }
    .payload : ALIGN(4096) { KEEP(*(.payload)) }
    __image_end = .;
    ASSERT(. <= 0x82328000, "loader/payload exceeds Samsung Image source slot")
    /DISCARD/ : { *(.comment) *(.note*) *(.eh_frame*) }
}
