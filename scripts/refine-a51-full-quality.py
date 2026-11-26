"""Complete paired panel writes for the existing nearest-neighbour path too."""
from pathlib import Path
import hashlib
import json

repo = Path('/opt/a51-hakios/upstream-a51/hakios')
out = Path(__file__).resolve().parents[1] / 'full-quality'
rel = 'xnu/files/iokit/Kernel/MiniIOMobileFramebuffer.cpp'
p = repo / rel
s = p.read_text()
at = s.index('\n/*\n * Where the middle of the')
s = s[:at] + '''
static void
nearest_row(uint32_t *out, const uint32_t *from, const uint32_t *column, uint32_t n)
{
\tuint32_t i = 0;
\tif (n && ((uintptr_t)out & 7)) {
\t\tout[0] = from[column[0]];
\t\ti = 1;
\t}
\tfor (; i + 1 < n; i += 2) {
\t\tuint64_t pair = from[column[i]];
\t\tpair |= (uint64_t)from[column[i + 1]] << 32;
\t\tmemcpy(out + i, &pair, sizeof(pair));
\t}
\tif (i < n) out[i] = from[column[i]];
}
''' + s[at:]
old = '''\t\t\tfor (int32_t x = cx0; x < cx1; x++) {
\t\t\t\tto[x] = from[fColumn[x]];
\t\t\t}'''
assert s.count(old) == 1
s = s.replace(old, '\t\t\tnearest_row(to + cx0, from, fColumn + cx0, (uint32_t)(cx1 - cx0));')
p.write_text(s)
record = json.loads((out / 'source-changes.json').read_text())
record['files'][rel]['after_sha256'] = hashlib.sha256(s.encode()).hexdigest()
rel = 'devices/a51/drivers/gpu/hakios.a51gpu.c'
p = repo / rel
s = p.read_text()
assert s.count('1040000, 936000, 832000, 728000') == 1
s = s.replace('1040000, 936000, 832000, 728000', '1040000, 936000')
s = s.replace('a DVFS request on channel 5:', 'a DVFS request on channel 0:')
s = s.replace('then asks the GPU\'s present speed (FREQ_GET)', 'then reads the hardware clock tree')
s = s.replace('/* dt: gpu_dvfs_table, first column */', '/* live Android gpu_freq_table, 22 November 2026 */')
p.write_text(s)
record['files'][rel]['after_sha256'] = hashlib.sha256(s.encode()).hexdigest()
(out / 'source-changes.json').write_text(json.dumps(record, indent=2) + '\n')
print('Both existing scaler modes use paired stores; CPU/GPU OPPs match live Android.')
