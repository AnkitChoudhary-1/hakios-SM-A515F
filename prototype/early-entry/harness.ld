ENTRY(_start)
SECTIONS {
    /* QEMU virt synthetic address; no A51 destination is selected. */
    . = 0x40080000;
    .text : { KEEP(*(.text.boot)) *(.text .text.*) *(.idmap.text) }
    .rodata : { *(.rodata .rodata.*) }
    .data : { *(.data .data.*) }
    .mmuoff.data.write : ALIGN(2048) { *(.mmuoff.data.write) }
    . = ALIGN(16);
    .bss (NOLOAD) : { *(.bss .bss.*) *(COMMON) }
    . += 16384;
    __stack_top = .;
    /DISCARD/ : { *(.comment) *(.note*) *(.eh_frame*) }
}
