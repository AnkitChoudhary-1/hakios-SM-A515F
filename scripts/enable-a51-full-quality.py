"""Apply the isolated, full-quality performance candidate to the current checkout.

Saves exact pre-edit files and refuses ambiguous replacements. Run once in WSL.
"""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import subprocess

repo = Path('/opt/a51-hakios/upstream-a51/hakios')
out = Path(__file__).resolve().parents[1] / 'full-quality'
backup = out / 'source-before'
files = ['userland/src/eagl.c', 'devices/a51/drivers/gpu/hakios.a51gpu.c',
         'xnu/files/iokit/Kernel/MiniIOMobileFramebuffer.cpp']
if backup.exists():
    raise RuntimeError('Source snapshot already exists; review instead of reapplying')
backup.mkdir(parents=True)
sources = {}
records = {}
for rel in files:
    data = (repo / rel).read_bytes()
    target = backup / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    sources[rel] = data.decode()
    records[rel] = {'before_sha256': hashlib.sha256(data).hexdigest()}


def replace(s, old, new):
    assert s.count(old) == 1, f'Ambiguous replacement: {old[:100]!r}'
    return s.replace(old, new)


# Texture storage is reusable only until a client redefines or rebinds it.
rel = files[0]
s = sources[rel]
s = replace(s, '\tbool shared;                    /*', '\tbool storage;                   /* level zero allocated for this IOSurface binding */\n\tbool shared;                    /*')
s = replace(s, '\tfor (int k = 0; k < 4; k++) {\n\t\tsum = (sum ^ lane[k])',
'''\t/* Include the last 1..7 bytes too; packed/one-row surfaces need not be word sized. */
\tfor (; at < size; at++) {
\t\tlane[0] = (lane[0] ^ base[at]) * 0x9e3779b97f4a7c15ull;
\t\tlane[0] ^= lane[0] >> 29;
\t}
\tfor (int k = 0; k < 4; k++) {
\t\tsum = (sum ^ lane[k])''')
s = replace(s, '''\tglTexImage2D(image->to, 0, (GLint)internal_format(image->internal, image->format), image->width, image->height, 0,
\t    image->format, image->type, base);''',
'''\tif (image->storage) {
\t\tglTexSubImage2D(image->to, 0, 0, 0, image->width, image->height, image->format, image->type, base);
\t} else {
\t\tglTexImage2D(image->to, 0, (GLint)internal_format(image->internal, image->format), image->width, image->height, 0,
\t\t    image->format, image->type, base);
\t\timage->storage = true;
\t}
'''.rstrip())
s = replace(s, 'static void\nmy_glTexImage2D(',
'''/* Client texture redefinitions must not reuse an earlier IOSurface allocation. */
static void
image_storage_forget(struct eagl *e, GLenum target, GLint level)
{
\tGLint texture = 0;
\tif (target == GL_TEXTURE_2D && level == 0) {
\t\tglGetIntegerv(GL_TEXTURE_BINDING_2D, &texture);
\t\tstruct image *image = image_of(e, (GLuint)texture);
\t\tif (image != NULL) image->storage = false;
\t}
}

static void
my_glTexImage2D(''')
s = replace(s, '\tglTexImage2D(target, level, (GLint)internal_format((GLenum)internal, format),',
            '\timage_storage_forget(e, target, level);\n\tglTexImage2D(target, level, (GLint)internal_format((GLenum)internal, format),')
s = replace(s, '\tglCompressedTexImage2D(target, level, internal, width, height, border, size, data);',
            '\timage_storage_forget(e, target, level);\n\tglCompressedTexImage2D(target, level, internal, width, height, border, size, data);')
s = replace(s, '\tunsigned copied = 0, in_place = 0;', '\tunsigned copied = 0, in_place = 0, mirrors = 0;')
s = replace(s, '\t\t\tglFlush();                              /* (also after a glFinish: the copy is new since) */', '\t\t\tmirrors++;')
s = replace(s, '\tif (in_place != 0 && !finished && wait_for_frames) {',
'''\t/* Submit all output mirrors together; retain the display fence/finish below. */
\tif (mirrors != 0) glFlush();       /* even after a preceding glFinish: these copies are new */
\tif (in_place != 0 && !finished && wait_for_frames) {''')
sources[rel] = s

# Read the clock tree, as Samsung cal_dfs_get_rate does, rather than relying on
# the unused firmware FREQ_GET interface. Never program a PLL directly.
rel = files[1]
s = sources[rel]
s = replace(s, '1053000, 950000, 840000, 764000, 683000, 572000, 546000, 455000, 384000,',
            '1053000, 949000, 839000, 764000, 683000, 572000, 546000, 455000, 385000,')
start = s.index('\tstatic const uint32_t cl0_khz[] =')
end = s.index('\tuint32_t want[3]', start)
tables = s[start:end].replace('\tstatic const', 'static const')
s = s[:start] + s[end:]
at = s.index('\nstruct acpm_channel {')
s = s[:at] + '\n' + tables + s[at:]
helper = '''
/* The CPU and G3D BUSD dividers have EMPTY_CAL_ID DIVRATIO in Samsung
 * cmucal-node.c: their rate is the PLL parent's, not the BUSP peripheral divider.
 * Reject an unlocked PLL, the switch parent, or a clock-tree transition. */
static uint32_t
a51_clock_rate_from_regs(uint32_t pll, uint32_t mux, uint32_t div)
{
\tuint32_t m = (pll >> 16) & 0x3ff, p = (pll >> 8) & 0x3f, s = pll & 7;
\tif ((pll & 0xa0000000u) != 0xa0000000u || !m || !p ||
\t    (mux & 0x10001u) || (div & 0x10000u)) return 0;
\treturn (uint32_t)(26000ull * m / ((uint64_t)p << s));
}

/* Normalize only to a unique captured Android OPP; the GPU table rounds some
 * PLL rates to whole MHz. CPU rates must be exact, GPU tolerance is 500 kHz. */
static uint32_t
a51_clock_level(uint32_t rate, const uint32_t *levels, uint32_t count, uint32_t tolerance)
{
\tuint32_t found = 0;
\tif (!rate) return 0;
\tfor (uint32_t i = 0; i < count; i++) {
\t\tuint32_t diff = rate > levels[i] ? rate - levels[i] : levels[i] - rate;
\t\tif (diff <= tolerance) {
\t\t\tif (found) return 0;
\t\t\tfound = levels[i];
\t\t}
\t}
\treturn found;
}

static uint32_t
a51_clock_read(uint32_t domain)
{
\tvm_offset_t base;
\tuint32_t pll_off, mux_off, div_off;
\tconst uint32_t *levels;
\tuint32_t count;
\tif (!cmu_cpucl0) cmu_cpucl0 = ml_io_map(0x10900000UL, 0x2000);
\tif (!cmu_cpucl1) cmu_cpucl1 = ml_io_map(0x10800000UL, 0x2000);
\tif (domain == ACPM_CPUCL0_DOMAIN) {
\t\tbase = cmu_cpucl0; pll_off = 0x140; mux_off = 0x1000; div_off = 0x1810;
\t\tlevels = cl0_khz; count = sizeof(cl0_khz) / sizeof(cl0_khz[0]);
\t} else if (domain == ACPM_CPUCL1_DOMAIN) {
\t\tbase = cmu_cpucl1; pll_off = 0x120; mux_off = 0x1000; div_off = 0x1810;
\t\tlevels = cl1_khz; count = sizeof(cl1_khz) / sizeof(cl1_khz[0]);
\t} else if (domain == ACPM_G3D_DOMAIN) {
\t\tbase = acpm_cmu; pll_off = PLL_CON0_PLL_G3D; mux_off = CLK_CON_MUX_G3D_BUSD; div_off = 0x1800;
\t\tlevels = g3d_levels_khz; count = sizeof(g3d_levels_khz) / sizeof(g3d_levels_khz[0]);
\t} else return 0;
\tif (!base) return 0;
\tfor (unsigned retry = 0; retry < 10; retry++) {
\t\tuint32_t pll = rd(base + pll_off), mux = rd(base + mux_off), div = rd(base + div_off);
\t\t__asm__ volatile ("dmb sy" ::: "memory");
\t\tuint32_t rate = a51_clock_rate_from_regs(pll, mux, div);
\t\tif (rate && pll == rd(base + pll_off) && mux == rd(base + mux_off) && div == rd(base + div_off))
\t\t\treturn a51_clock_level(rate, levels, count, domain == ACPM_G3D_DOMAIN ? 500 : 0);
\t\tIOSleep(1);
\t}
\treturn 0;
}

/* A matched firmware answer is only acknowledgement. Verify actual hardware
 * after every request, including thermal downshifts and original-rate restore. */
static bool
a51_clock_set(const struct acpm_channel *dvfs, uint32_t domain, uint32_t rate)
{
\tuint32_t cmd[4] = { domain, rate, ACPM_FREQ_REQ, 0 };
\tbool acknowledged = acpm_call(dvfs, cmd);
\tIOSleep(10);
\tuint32_t observed = a51_clock_read(domain);
\ta51_report("a51gpu: clock request: domain %u requested %u observed %u kHz ack %u\\n",
\t    domain, rate, observed, acknowledged);
\treturn acknowledged && observed == rate;
}
'''
at = s.index('\n/* A string of the APM')
s = s[:at] + '\n' + helper + s[at:]
start = s.index('\tfor (uint32_t d = 0; d < 3; d++) {', s.index('\tuint32_t khz_now[3]'))
end = s.index('\tif (acpm_steps < 3)', start)
s = s[:start] + '''\tfor (uint32_t d = 0; d < 3; d++) {
\t\tkhz_now[d] = a51_clock_read(domains[d]);
\t}
\tuint32_t was = khz_now[2];
\tclock_said("step 2: hardware clocks: A53s %u kHz, A73s %u kHz, GPU %u kHz; PLL con0 GPU %x",
\t    khz_now[0], khz_now[1], khz_now[2], rd(acpm_cmu + PLL_CON0_PLL_G3D));
''' + s[end:]
s = replace(s, '\tint initial_t[3];', '\tconst uint32_t sensor_of[3] = { 1, 2, 0 };\n\tint initial_t[3];')
s = s.replace('initial_t[d]', 'initial_t[sensor_of[d]]')
start = s.index('\tbool answered[3];')
end = s.index('\t/*', start)
s = s[:start] + '''\tbool answered[3] = { false, false, false };
\tfor (uint32_t d = 0; d < 3; d++) {
\t\tanswered[d] = a51_clock_set(&dvfs, domains[d], want[d]);
\t\tif (!answered[d]) break;   /* no further boosts after any unverified change */
\t}
''' + s[end:]
s = replace(s, '\tuint32_t bus_khz[2] = { 2093000, 667000 };', '\tuint32_t bus_khz[2] = { 0, 0 }; /* unverified bus domains remain firmware controlled */')
s = replace(s, '\tconst uint32_t sensor_of[3] = { 1, 2, 0 };\n\tuint32_t asked', '\tuint32_t asked')
s = replace(s, '\tconst uint32_t *boot_khz = khz_now; /* verified pre-boost ACPM rates */', '\tconst uint32_t *boot_khz = khz_now; /* verified pre-boost hardware rates */')
s = replace(s, '\tuint32_t asked[3], at[3], floor_at[3], drops = 0, rises = 0, seconds = 0;',
            '\tuint32_t asked[3], at[3], floor_at[3], drops = 0, rises = 0, seconds = 0;\n\tbool restore_pending[3] = { false, false, false };')
s = replace(s, '\t\tclock_said("boost request incomplete: restoring original rates; boosting disabled");',
'''\t\tclock_said("boost request incomplete: restoring original rates; boosting disabled");
\t\tfor (uint32_t d = 0; d < 3; d++) restore_pending[d] = true;''')
s = replace(s, '''\t\t\tbool was_fault = fault[d];
\t\t\tuint32_t to''',
'''\t\t\tbool was_fault = fault[d];
\t\t\t/* Check once a second. Firmware drift or unreadable hardware disables
\t\t\t * future boosts and schedules a verified original-rate restoration. */
\t\t\tuint32_t observed = a51_clock_read(domains[d]);
\t\t\tif (observed != levels[d][at[d]]) {
\t\t\t\tfault[d] = true;
\t\t\t\trestore_pending[d] = true;
\t\t\t}
\t\t\tuint32_t to''')
s = replace(s, '\t\t\tif (to == at[d]) {',
'''\t\t\tif (fault[d] && !was_fault) restore_pending[d] = true;
\t\t\tif (restore_pending[d]) {
\t\t\t\tif (a51_clock_set(&dvfs, domains[d], boot_khz[d])) {
\t\t\t\t\tat[d] = floor_at[d];
\t\t\t\t\trestore_pending[d] = false;
\t\t\t\t} else if (seconds % 30 == 1) {
\t\t\t\t\ta51_report("a51gpu: clock guard: original-rate restore NOT VERIFIED domain %u\\n", domains[d]);
\t\t\t\t}
\t\t\t\tcontinue;
\t\t\t}
\t\t\tif (to == at[d]) {''')
s = replace(s, '''\t\t\tcmd[0] = domains[d];
\t\t\tcmd[1] = levels[d][to];
\t\t\tcmd[2] = ACPM_FREQ_REQ;
\t\t\tcmd[3] = 0;
\t\t\tif (acpm_call(&dvfs, cmd)) {''',
'''\t\t\tif (a51_clock_set(&dvfs, domains[d], levels[d][to])) {''')
s = replace(s, '''\t\t\t\tat[d] = to;
\t\t\t}
\t\t}
\t\tif (seconds % 30 == 0)''',
'''\t\t\t\tat[d] = to;
\t\t\t} else {
\t\t\t\tfault[d] = true;
\t\t\t\trestore_pending[d] = true;
\t\t\t}
\t\t}
\t\tif (seconds % 30 == 0)''')
s = replace(s, '''\t\t\t\tcmd[0] = domains[d]; cmd[1] = 0; cmd[2] = ACPM_FREQ_GET; cmd[3] = 0;
\t\t\t\tif (acpm_call(&dvfs, cmd)) { observed[d] = cmd[1]; }''',
'''\t\t\t\tobserved[d] = a51_clock_read(domains[d]);''')
sources[rel] = s

# Pair the panel writes without changing the bilinear interpolation, and keep
# scalar boundary pixels. This uses general registers, not kernel SIMD state.
rel = files[2]
s = sources[rel]
at = s.index('\n/*\n * Where the middle of the')
s = s[:at] + '''
static inline uint32_t
filtered_pixel(const uint32_t *from, uint32_t c, uint32_t w)
{
\tuint32_t a = from[c];
\treturn w == 0 || a == from[c + 1] ? a : blend(a, from[c + 1], w);
}

/* Aligned 64-bit framebuffer stores halve write-combined transactions.
 * memcpy of eight bytes emits a general-register store; no FP/SIMD registers.
 * Preserve exact scalar interpolation and never read past the final column. */
static void
filtered_row(uint32_t *out, const uint32_t *from, const uint32_t *column,
    const uint16_t *weights, uint32_t n)
{
\tuint32_t i = 0;
\tif (n && ((uintptr_t)out & 7)) {
\t\tout[0] = filtered_pixel(from, column[0], weights[0]);
\t\ti = 1;
\t}
\tfor (; i + 1 < n; i += 2) {
\t\tuint64_t pair = filtered_pixel(from, column[i], weights[i]);
\t\tpair |= (uint64_t)filtered_pixel(from, column[i + 1], weights[i + 1]) << 32;
\t\tmemcpy(out + i, &pair, sizeof(pair));
\t}
\tif (i < n) out[i] = filtered_pixel(from, column[i], weights[i]);
}
''' + s[at:]
s = replace(s, '''\t\t\tfor (uint32_t i = 0, n = (uint32_t) (cx1 - cx0); i < n; i++) {
\t\t\t\tuint32_t c = column[i], w = weights[i], a = from[c];

\t\t\t\tout[i] = w == 0 || a == from[c + 1] ? a : blend(a, from[c + 1], w);
\t\t\t}''',
'''\t\t\tfiltered_row(out, from, column, weights, (uint32_t)(cx1 - cx0));''')
sources[rel] = s

# Write only after every expected source shape has matched.
for rel, s in sources.items():
    (repo / rel).write_text(s)
    records[rel]['after_sha256'] = hashlib.sha256(s.encode()).hexdigest()
(out / 'source-changes.json').write_text(json.dumps({
    'at_utc': datetime.now(timezone.utc).isoformat(),
    'git_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip(),
    'files': records, 'preserves_original_render_quality': True,
    'hardware_tested': False,
}, indent=2) + '\n')
print('Full-quality renderer, clock-verification and display-copy changes applied; exact sources saved.')
