ENTRY(_start)
SECTIONS {
    /* QEMU virt DRAM begins at 0x40000000 */
    . = 0x40080000;
    .text.boot : { KEEP(*(.text.boot)) }
    .text : { *(.text .text.*) }
    .rodata : { *(.rodata .rodata.*) }
    .data.record : ALIGN(64) { *(.data.record) }
    .data.config : ALIGN(8)  { *(.data.config) }
    .data.boot_args : ALIGN(64) { *(.data.boot_args) }
    .data.devicetree : ALIGN(4096) {
        *(.data.devicetree)
    }
    .data.xnu_slice : ALIGN(4096) { *(.data.xnu_slice) }
    .data : { *(.data .data.*) }
    . = ALIGN(16);
    .bss (NOLOAD) : { *(.bss .bss.*) *(COMMON) }
    . += 16384;
    __stack_top = .;
    /DISCARD/ : { *(.comment) *(.note*) *(.eh_frame*) }
}
