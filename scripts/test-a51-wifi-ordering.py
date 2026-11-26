"""Actual-function bounded fault tracing and optimized ARM64 ordering checks (WSL)."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--package-dir', type=Path, required=True)
args = parser.parse_args()
out = args.package_dir.resolve() / 'host-tests'
out.mkdir(parents=True, exist_ok=True)
repo = Path('/opt/a51-hakios/upstream-a51/hakios')
source = (repo / 'devices/a51/drivers/wifi/hakios.a51wifi.c').read_text()

def function(name):
    start = source.index('\n' + name + '(')
    start = source.rfind('static ', 0, start)
    pos = source.index('{', start) + 1
    depth = 1
    while depth:
        depth += (source[pos] == '{') - (source[pos] == '}')
        pos += 1
    return source[start:pos]

pre = r'''
#include <assert.h>
#include <stdint.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uintptr_t vm_offset_t;
typedef size_t vm_size_t;
#define WLBT_MEMORY (16u << 20)
#define HIP_SCOREBOARD 448
static vm_offset_t wlbt_memory;
static uint32_t runtime_panic_offset = 0x1000, hip_base = 0x2000;
static char lines[70][192];
static unsigned line_count, cache_calls;
static void cache_out(vm_offset_t address, vm_size_t size) {
    assert(address >= wlbt_memory && size <= WLBT_MEMORY);
    assert(address - wlbt_memory <= WLBT_MEMORY - size);
    cache_calls++;
}
static void hakios_tl(const char *format, ...) {
    assert(line_count < 70);
    va_list ap;
    va_start(ap, format);
    int n = vsnprintf(lines[line_count], sizeof(lines[0]), format, ap);
    va_end(ap);
    assert(n >= 0 && (unsigned)n < sizeof(lines[0]));
    line_count++;
}
'''
tests = r'''
static uint8_t *saved;
static uint32_t *panic_record(void) {return (uint32_t *)(wlbt_memory + runtime_panic_offset);}
static void seal(uint32_t count) {
    uint32_t *r = panic_record(), sum = 0xa5a5a5a5;
    r[0] = 2; r[1] = count * 4;
    for (unsigned i = 0; i < count - 1; i++) sum ^= r[i];
    r[count - 1] = sum;
}
static void trace_unchanged(unsigned expected_lines, unsigned expected_caches) {
    memcpy(saved, (void *)wlbt_memory, WLBT_MEMORY);
    line_count = cache_calls = 0;
    wifi_trace_fault();
    assert(line_count == expected_lines && cache_calls == expected_caches);
    assert(!memcmp(saved, (void *)wlbt_memory, WLBT_MEMORY));
    assert(strstr(lines[line_count - 1], "fault queues host"));
}
int main(void) {
    wlbt_memory = (uintptr_t)calloc(1, WLBT_MEMORY); saved = malloc(WLBT_MEMORY);
    assert(wlbt_memory && saved);
    uint32_t *r = panic_record();
    /* Small checked panic: exactly the record length, followed by queue indices. */
    r[2] = 0x12345678; r[3] = 0xdeadbeef; seal(5);
    trace_unchanged(2, 2); assert(strstr(lines[0], "12345678 deadbeef"));
    /* Untrusted record emits only four header words and never follows a stack pointer. */
    r[4] ^= 1; trace_unchanged(2, 2);
    const uint32_t lengths[] = {0, 4, 8, 16, 19, 21, 1024, 1028, UINT32_MAX};
    for (unsigned i = 0; i < sizeof(lengths) / sizeof(lengths[0]); i++) {
        r[1] = lengths[i]; trace_unchanged(2, 2);
    }
    seal(5); r[0] = 1; trace_unchanged(2, 2);
    runtime_panic_offset = 0; trace_unchanged(1, 1);
    runtime_panic_offset = 0x1001; trace_unchanged(1, 1);
    runtime_panic_offset = WLBT_MEMORY - 1023; trace_unchanged(1, 1);
    runtime_panic_offset = WLBT_MEMORY - 1024; seal(5); trace_unchanged(2, 2);
    runtime_panic_offset = 0x1000; r = panic_record();
    /* Valid optional v1 stack and maximal checked v2 record. */
    memset(r, 0, 1024); r[52] = 0x5000; seal(54);
    uint32_t *stack = (uint32_t *)(wlbt_memory + 0x5000);
    stack[0] = 1; stack[1] = 36;
    trace_unchanged(10, 3); assert(strstr(lines[7], "r4-stack"));
    stack[1] = 1020; trace_unchanged(40, 3);
    const uint32_t stack_lengths[] = {0, 4, 7, 9, 1024, UINT32_MAX};
    for (unsigned i = 0; i < sizeof(stack_lengths) / sizeof(stack_lengths[0]); i++) {
        stack[1] = stack_lengths[i]; trace_unchanged(8, 3);
    }
    stack[0] = 2; stack[1] = 36; trace_unchanged(8, 3);
    const uint32_t offsets[] = {0, 1, 0x5001, WLBT_MEMORY - 1023, UINT32_MAX};
    for (unsigned i = 0; i < sizeof(offsets) / sizeof(offsets[0]); i++) {
        r[52] = offsets[i]; seal(54); trace_unchanged(8, 2);
    }
    r[52] = WLBT_MEMORY - 1024; seal(54);
    stack = (uint32_t *)(wlbt_memory + r[52]); stack[0] = 1; stack[1] = 8;
    trace_unchanged(9, 3);
    /* In a 53-word record field 52 is the checksum, not a trusted stack offset. */
    memset(r, 0, 1024); seal(53); trace_unchanged(8, 2);
    memset(r, 0, 1024); seal(255); trace_unchanged(33, 2);
    /* Direct formatter bounds: cap words at 256 and truncate arbitrary long tags. */
    line_count = 0; wifi_trace_words("r4-panic", r, 0); assert(line_count == 0);
    wifi_trace_words("abcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyz", r, UINT32_MAX);
    assert(line_count == 32 && strstr(lines[31], "3e0:"));
    for (unsigned i = 0; i < line_count; i++) assert(strlen(lines[i]) < 160);
    free(saved); free((void *)wlbt_memory);
    puts("panic/stack bounds, checksum, formatter limits and read-only tracing passed");
}
'''
(out / 'trace-fixture.c').write_text(pre + function('wifi_trace_words') + '\n' + function('wifi_trace_fault') + tests)
subprocess.run(['clang', '-O1', '-g', '-fsanitize=address,undefined', 'trace-fixture.c', '-o', 'trace-fixture'], cwd=out, check=True)
run = subprocess.run([str(out / 'trace-fixture')], cwd=out, check=True, text=True, capture_output=True)

arm = 'typedef unsigned long vm_offset_t;\ntypedef unsigned long vm_size_t;\n' + function('cache_out') + r'''
void ownership(unsigned long *p) {
    *p = 123;
    cache_out((vm_offset_t)p, sizeof(*p));
    *p = *p + 1;
}
'''
(out / 'ordering-fixture.c').write_text(arm)
for filename, options in [('ordering.ll', ['-emit-llvm']), ('ordering.s', [])]:
    subprocess.run(['clang', '--target=aarch64-none-elf', '-O2', '-S', *options,
                    'ordering-fixture.c', '-o', filename], cwd=out, check=True)
ir = (out / 'ordering.ll').read_text()
asm = (out / 'ordering.s').read_text()
assert ir.count('~{memory}') >= 2
assert ir.index('store i64 123') < ir.index('dc civac') < ir.index('dsb sy') < ir.index('load i64')
assert re.search(r'\bstr\b', asm[:asm.index('dc\tcivac')])
assert re.search(r'\bldr\b', asm[asm.index('dsb\tsy'):])
assert source.count('"dc civac, %0" : : "r" (line) : "memory"') == 2
assert source.count('"dsb sy" : : : "memory"') == 4
result = {'passed': True, 'hardware_tested': False, 'wifi_sha256': hashlib.sha256(source.encode()).hexdigest(),
          'trace_test': run.stdout.strip(), 'arm64_ordering': 'optimized IR has memory clobbers; store before cache maintenance, load after dsb',
          'limitations': 'host tests do not identify the firmware panic cause or establish device stability'}
(out / 'ordering-results.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
