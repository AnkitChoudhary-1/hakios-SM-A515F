ENTRY(_start)
SECTIONS {
    /* QEMU virt RAM only. Not an A51 destination. */
    . = 0x40080000;
    .text : { KEEP(*(.text.boot)) *(.text .text.*) }
    .rodata : { *(.rodata .rodata.*) }
    .data : { *(.data .data.*) }
    .fixture_record_before : ALIGN(512) { *(.fixture.record.before) }
    .mmuoff.data.write : ALIGN(512) { *(.mmuoff.data.write) }
    .fixture_record_after : { *(.fixture.record.after) }
    . = ALIGN(16);
    .bss (NOLOAD) : { *(.bss .bss.*) *(COMMON) }
    . += 16384;
    __stack_top = .;
    ASSERT((hkf_vectors & 2047) == 0, "VBAR alignment")
    ASSERT(hkf_vectors_end - hkf_vectors == 2048, "vector table extent")
    ASSERT((hkf_record & 511) == 0, "record alignment")
    ASSERT(hkf_record_end - hkf_record == 512, "record extent")
    ASSERT(hkf_record - fixture_record_before == 512, "before guard adjacency")
    ASSERT(fixture_record_after == hkf_record_end, "after guard adjacency")
    /DISCARD/ : { *(.comment) *(.note*) *(.eh_frame*) }
}
