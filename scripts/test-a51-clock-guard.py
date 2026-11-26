"""Compile and exercise the actual kernel clock guard without hardware access."""
from pathlib import Path
import re
import subprocess
import tempfile

p = Path('/opt/a51-hakios/upstream-a51/hakios/devices/a51/drivers/gpu/hakios.a51gpu.c')
source = p.read_text(encoding='utf-8')
match = re.search(r'static uint32_t\na51_guard_target\(.*?\n\}', source, re.S)
assert match
cases = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
POLICY
int main(void) {
    bool fault = false;
    assert(a51_guard_target(60,83,3,3,9,1,&fault)==3 && !fault);
    assert(a51_guard_target(84,83,3,3,9,1,&fault)==4);
    assert(a51_guard_target(83,83,3,3,9,1,&fault)==3);
    assert(a51_guard_target(82,81,1,1,7,1,&fault)==2);
    assert(a51_guard_target(74,83,5,3,9,5,&fault)==4);
    assert(a51_guard_target(74,83,5,3,9,4,&fault)==5);
    assert(a51_guard_target(84,83,9,3,9,1,&fault)==9);
    assert(a51_guard_target(-1000,83,3,3,9,1,&fault)==9 && fault);
    assert(a51_guard_target(55,83,9,3,9,5,&fault)==9 && fault);
    fault=false;
    assert(a51_guard_target(101,83,3,3,9,1,&fault)==9 && fault);
    fault=false;
    assert(a51_guard_target(126,83,3,3,9,1,&fault)==9 && fault);
    fault=false;
    assert(a51_guard_target(-41,83,3,3,9,1,&fault)==9 && fault);
    return 0;
}
'''.replace('POLICY', match.group())
with tempfile.TemporaryDirectory(prefix='a51-guard-') as folder:
    f = Path(folder) / 'guard.c'
    f.write_text(cases, encoding='utf-8')
    binary = Path(folder) / 'guard'
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(f),'-o',str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
print('12 actual clock-guard policy cases passed.')
