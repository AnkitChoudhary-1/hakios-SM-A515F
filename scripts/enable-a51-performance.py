"""Patch only host sources: reliable GPU diagnostics and guarded ACPM clocks."""
from pathlib import Path
import difflib
import hashlib
import json
import re

REPO = Path('/opt/a51-hakios/upstream-a51/hakios')
OUT = Path(__file__).resolve().parents[1] / 'audio-performance'
SOURCE = REPO / 'devices/a51/drivers/gpu/hakios.a51gpu.c'


def replace(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError('Source context changed: ' + old[:100])
    return text.replace(old, new, 1)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    original = SOURCE.read_text(encoding='utf-8')
    if 'a51_guard_target' in original:
        print('Performance patch already installed; no changes.')
        return
    (OUT / 'hakios.a51gpu.before.c').write_text(original, encoding='utf-8')
    helper = '''
/* Whole lines use the loader's existing interrupt-safe lock; printf's ring can
 * lose these diagnostics to daemon output. Only low-rate reports use this path. */
extern void loader_log_line(const char *line);
static int a51_report(const char *format, ...) __printflike(1, 2);
static int
a51_report(const char *format, ...)
{
\tchar line[768];
\tva_list ap;
\tva_start(ap, format);
\tint length = vsnprintf(line, sizeof(line), format, ap);
\tva_end(ap);
\tloader_log_line(line);
\tprintf("%s", line);
\treturn length;
}

/* Sensor loss or >100 C permanently disables boosting for that domain this
 * boot. A failed fallback request is retried next second (at is not advanced). */
static uint32_t
a51_guard_target(int temp, uint32_t trip, uint32_t at, uint32_t asked,
    uint32_t floor, uint32_t seconds, bool *fault)
{
\tif (temp < -40 || temp > 125 || temp > 100) {
\t\t*fault = true;
\t}
\tif (*fault) {
\t\treturn floor;
\t}
\tif (temp > (int)trip && at < floor) {
\t\treturn at + 1;
\t}
\tif (temp < 75 && at > asked && seconds % 5 == 0) {
\t\treturn at - 1;
\t}
\treturn at;
}
'''
    text = replace(original, 'extern uint64_t kvtophys(vm_offset_t va);',
                   'extern uint64_t kvtophys(vm_offset_t va);\n' + helper)
    # These functions run on worker threads, never on the hot job/IRQ path.
    for start, end in [('cpu_clocks_say(void)', '/*\n * The SoC'),
                       ('tmu_say(void)', '/* In interrupt'),
                       ('if (report && mach_absolute_time() >= next_report)',
                        '\n\t\tfor (uint32_t i = 0; i < 3; i++)'),
                       ('clock_said(const char *format, ...)\n{',
                        '\nstatic bool')]:
        a = text.index(start)
        b = text.index(end, a)
        text = text[:a] + re.sub(r'\bprintf\(', 'a51_report(', text[a:b]) + text[b:]
    preflight = '''\t/* All sensors and the original rates must be usable before any boost. */
\tint initial_t[3];
\tif (!tmu_temps(initial_t)) {
\t\tclock_said("step 3 refused: TMU unavailable; clocks unchanged");
\t\treturn;
\t}
\tconst uint32_t *guard_levels[3] = { cl0_khz, cl1_khz, g3d_levels_khz };
\tconst uint32_t guard_counts[3] = { sizeof(cl0_khz) / sizeof(cl0_khz[0]),
\t    sizeof(cl1_khz) / sizeof(cl1_khz[0]), sizeof(g3d_levels_khz) / sizeof(g3d_levels_khz[0]) };
\tfor (uint32_t d = 0; d < 3; d++) {
\t\tbool found = false;
\t\tfor (uint32_t i = 0; i < guard_counts[d]; i++) {
\t\t\tfound |= guard_levels[d][i] == khz_now[d];
\t\t}
\t\tif (!found || khz_now[d] > want[d] || initial_t[d] < -40 || initial_t[d] >= 75) {
\t\t\tclock_said("step 3 refused: original rate %u kHz or sensor %d C unsuitable; clocks unchanged",
\t\t\t    khz_now[d], initial_t[d]);
\t\t\treturn;
\t\t}
\t}
\tbool answered[3];'''
    text = replace(text, '\tbool answered[3];', preflight)
    text = replace(text, '\t\tanswered[d] = acpm_call(&dvfs, cmd);',
                   '\t\tanswered[d] = acpm_call(&dvfs, cmd);\n'
                   '\t\tIOSleep(10);\n'
                   '\t\tcmd[0] = domains[d]; cmd[1] = 0; cmd[2] = ACPM_FREQ_GET; cmd[3] = 0;\n'
                   '\t\tanswered[d] = acpm_call(&dvfs, cmd) && cmd[1] == want[d] && answered[d];')
    text = replace(text, '\tconst uint32_t boot_khz[3] = { 1053000, 1456000, 260000 };',
                   '\tconst uint32_t *boot_khz = khz_now; /* verified pre-boost ACPM rates */')
    text = replace(text, '\tint hottest[3] = { -1000, -1000, -1000 };',
                   '\tint hottest[3] = { -1000, -1000, -1000 };\n'
                   '\tbool fault[3] = { false, false, false };\n'
                   '\tif (!answered[0] || !answered[1] || !answered[2]) {\n'
                   '\t\tfault[0] = fault[1] = fault[2] = true;\n'
                   '\t\tclock_said("boost request incomplete: restoring original rates; boosting disabled");\n\t}')
    text = replace(text, '\t\tint t[3];', '\t\tint t[3] = { -1000, -1000, -1000 };')
    text = replace(text, '\t\tif (!tmu_temps(t)) {\n\t\t\tcontinue;\n\t\t}',
                   '\t\tif (!tmu_temps(t)) {\n'
                   '\t\t\tt[0] = t[1] = t[2] = -1000;\n\t\t}')
    a = text.index('\t\t\tuint32_t to = at[d];')
    b = text.index('\t\t\tif (to == at[d])', a)
    text = text[:a] + '''\t\t\tbool was_fault = fault[d];
\t\t\tuint32_t to = a51_guard_target(temp, d == 0 ? 81 : 83, at[d], asked[d],
\t\t\t    floor_at[d], seconds, &fault[d]);
\t\t\tif (fault[d] && !was_fault) {
\t\t\t\ta51_report("a51gpu: clock guard: domain %u sensor %d C: restore %u kHz; boosting disabled\\n",
\t\t\t\t    d, temp, boot_khz[d]);
\t\t\t}
\t\t\tif (temp > hottest[d]) {
\t\t\t\thottest[d] = temp;
\t\t\t}
''' + text[b:]
    text = replace(text, '\t\t\t\tprintf("a51gpu: temperature watch:',
                   '\t\t\t\ta51_report("a51gpu: temperature watch:')
    text = replace(text, '\t\tif (seconds % 30 == 0) {\n\t\t\tclock_said(', '''\t\tif (seconds % 30 == 0) {
\t\t\tuint32_t observed[3] = { 0, 0, 0 };
\t\t\tfor (uint32_t d = 0; d < 3; d++) {
\t\t\t\tcmd[0] = domains[d]; cmd[1] = 0; cmd[2] = ACPM_FREQ_GET; cmd[3] = 0;
\t\t\t\tif (acpm_call(&dvfs, cmd)) { observed[d] = cmd[1]; }
\t\t\t}
\t\t\ta51_report("a51gpu: verified clocks: A53s %u A73s %u GPU %u kHz; guard faults %u%u%u\\n",
\t\t\t    observed[0], observed[1], observed[2], fault[0], fault[1], fault[2]);
\t\t\tclock_said(''')
    SOURCE.write_text(text, encoding='utf-8')
    (OUT / 'a51-performance.patch').write_text(''.join(difflib.unified_diff(
        original.splitlines(True), text.splitlines(True),
        fromfile='a/devices/a51/drivers/gpu/hakios.a51gpu.c',
        tofile='b/devices/a51/drivers/gpu/hakios.a51gpu.c')), encoding='utf-8')
    (OUT / 'performance-source-manifest.json').write_text(json.dumps({
        'source': str(SOURCE), 'before_sha256': hashlib.sha256(original.encode()).hexdigest(),
        'after_sha256': hashlib.sha256(text.encode()).hexdigest(),
        'phone_writes': False,
    }, indent=2) + '\n', encoding='utf-8')
    print('Guarded performance source patched; no phone commands issued.')


if __name__ == '__main__':
    main()
