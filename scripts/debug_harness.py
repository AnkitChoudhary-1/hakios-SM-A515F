import subprocess
from pathlib import Path

def run():
    work = Path("/tmp/debug_harness")
    work.mkdir(parents=True, exist_ok=True)
    
    # Check dt_blob
    dt_bin = Path("evidence/phase-3/xnu-loader-host/20261113T024722922669Z/device_tree.bin").read_bytes()
    (work / "device_tree.bin").write_bytes(dt_bin)
    print(f"device_tree.bin size: {len(dt_bin)}")

    # dt_blob.S
    (work / "dt_blob.S").write_text("""
.section .data.devicetree, "aw", %progbits
.align 12
.global dt_blob_start
dt_blob_start:
.incbin "device_tree.bin"
.global dt_blob_end
dt_blob_end:
""")

    # test.c
    (work / "test.c").write_text("""
#include <stdint.h>
extern uint8_t dt_blob_start[];
extern uint8_t dt_blob_end[];
uint64_t get_start(void) { return (uint64_t)&dt_blob_start[0]; }
uint64_t get_end(void) { return (uint64_t)&dt_blob_end[0]; }
uint64_t get_size(void) { return (uint64_t)(&dt_blob_end[0] - &dt_blob_start[0]); }
""")

    # harness.ld
    (work / "harness.ld").write_text("""
ENTRY(get_start)
SECTIONS {
    . = 0x40080000;
    .text : { *(.text .text.*) }
    .data.devicetree : ALIGN(4096) {
        dt_blob_start = .;
        *(.data.devicetree)
        dt_blob_end = .;
    }
}
""")

    # Build
    flags = ['--target=aarch64-none-elf', '-mcpu=cortex-a53', '-ffreestanding', '-O2', '-I', str(work)]
    subprocess.check_call(['clang', *flags, '-c', str(work / 'dt_blob.S'), '-o', str(work / 'dt_blob.o')], cwd=work)
    subprocess.check_call(['clang', *flags, '-c', str(work / 'test.c'), '-o', str(work / 'test.o')], cwd=work)
    subprocess.check_call(['ld.lld', '-T', str(work / 'harness.ld'), str(work / 'test.o'), str(work / 'dt_blob.o'), '-o', str(work / 'test.elf')], cwd=work)

    # Inspect symbols
    out = subprocess.check_output(['llvm-nm', str(work / 'test.elf')]).decode()
    print("=== SYMBOLS ===")
    for line in out.splitlines():
        if "dt_blob" in line:
            print(line)

    dis = subprocess.check_output(['llvm-objdump', '-d', str(work / 'test.elf')]).decode()
    print("=== DISASSEMBLY ===")
    print(dis)

if __name__ == '__main__':
    run()
