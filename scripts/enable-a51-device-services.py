"""Reproducible host-only follow-up to the preserved audio-performance build."""
from pathlib import Path
import difflib
import hashlib
import json
import re

REPO = Path('/opt/a51-hakios/upstream-a51/hakios')
HERE = Path(__file__).resolve().parent
OUT = HERE.parent / 'device-services'
OUT.mkdir(exist_ok=True)


def save(rel, contents):
    target = REPO / rel
    before = target.read_text(encoding='utf-8') if target.exists() else ''
    record = OUT / 'source-before' / rel
    record.parent.mkdir(parents=True, exist_ok=True)
    if not record.exists():
        record.write_text(before, encoding='utf-8')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(contents, encoding='utf-8')


def edit(rel, patch):
    original = (REPO / rel).read_text(encoding='utf-8')
    save(rel, patch(original))


def replace(t, old, new):
    if new in t:
        return t
    if t.count(old) != 1:
        raise RuntimeError('Changed source context: ' + old[:100])
    return t.replace(old, new, 1)


def bridge(t):
    if 'hakios_battery_report_source' in t:
        return t
    t = t.replace('reported by Qualcomm firmware', 'reported by the battery monitor')
    t = t.replace('Qualcomm firmware reports', 'the battery monitor reports')
    t = replace(t, 'static uint64_t battery_updates, battery_failures;',
                'static uint64_t battery_updates, battery_failures;\nstatic int battery_data_valid;\n'
                'SYSCTL_DECL(_kern_hakios);\n'
                'SYSCTL_INT(_kern_hakios, OID_AUTO, battery_data_valid, CTLFLAG_RD | CTLFLAG_LOCKED,\n'
                '    &battery_data_valid, 0, "1 while the battery reading is valid");')
    t = replace(t, 'hakios_battery_report(const struct hakios_battery_state *b)\n{',
                'hakios_battery_report_source(const struct hakios_battery_state *b, bool from_dsp)\n{\n'
                '\tif (!b || b->size != sizeof(*b) || b->percent_hundredths < 0 || b->percent_hundredths > 10000) {\n'
                '\t\thakios_battery_invalidate();\n\t\treturn;\n\t}')
    t = replace(t, 'battery_temperature_c = (int)(((int64_t)b->temperature_hundredths + 50) / 100);',
                'battery_temperature_c = b->temperature_hundredths == -27300 ? -273 :\n'
                '\t    b->temperature_hundredths / 100;')
    t = replace(t, 'battery_charging = b->status == 1;',
                'battery_charging = b->present && b->external && b->status == 1;')
    t = replace(t, 'battery_source_dsp = 1;', 'battery_source_dsp = from_dsp;\n\tbattery_data_valid = 1;')
    marker = 'static void\nbattery_thread('
    extra = '''void
hakios_battery_report(const struct hakios_battery_state *b)
{
    hakios_battery_report_source(b, true); /* existing ADSP caller */
}

extern void HakiosBatteryInvalidate(void);
void
hakios_battery_invalidate(void)
{
    battery_data_valid = 0;
    battery_charging = 0;
    battery_charger_present = 0;
    battery_temperature_c = -273;
    battery_failures++;
    HakiosBatteryInvalidate(); /* preserve last SOC, mark stale, withdraw charging */
}

'''
    return replace(t, marker, extra + marker)


def power_source(t):
    if 'HakiosBatteryInvalidate(void)' in t:
        return t
    t = replace(t, '\tvoid report(const struct hakios_battery_state * b);',
                '\tvoid report(const struct hakios_battery_state * b);\n\tvoid invalidate(void);')
    t = replace(t, 'bool charging = b->external && b->status == 1;',
                'bool charging = b->present && b->external && b->status == 1;')
    t = replace(t, 'flag("FullyCharged", b->external && (b->status == 4 || percent == 100));',
                'flag("BatteryDataValid", true);\n\tflag("FullyCharged", b->present && b->external && b->status == 4);')
    t = replace(t, 'number("Temperature", b->temperature_hundredths);',
                'if (b->temperature_hundredths != -27300) {\n'
                '\t\tnumber("Temperature", b->temperature_hundredths);\n'
                '\t} else {\n\t\tproperties->removeObject("Temperature");\n\t}')
    # Unknown adapter measurements must not appear as an observed zero-watt port.
    t = replace(t, 'if ((n = OSNumber::withNumber((unsigned long long) ((mv * ma + 500000) / 1000000), 32)) != NULL)',
                'if (mv > 0 && ma > 0 && (n = OSNumber::withNumber((unsigned long long) ((mv * ma + 500000) / 1000000), 32)) != NULL)')
    for expr in ['ma', 'mv']:
        t = replace(t, f'if ((n = OSNumber::withNumber((unsigned long long) {expr}, 32)) != NULL)',
                    f'if ({expr} > 0 && (n = OSNumber::withNumber((unsigned long long) {expr}, 32)) != NULL)')
    return t + '''
void
HakiosBattery::invalidate(void)
{
    flag("BatteryDataValid", false);
    flag("FullyCharged", false);
    flag("AppleRawExternalConnected", false);
    setIsCharging(false);
    setExternalConnected(false);
    setExternalChargeCapable(false);
    properties->removeObject("Temperature");
    properties->removeObject(kIOPMPSAdapterDetailsKey);
    updateStatus();
}

extern "C" void HakiosBatteryInvalidate(void);
void HakiosBatteryInvalidate(void)
{
    if (battery != NULL) battery->invalidate();
}
'''


def acpm(t):
    if 'acpm_range_valid' in t:
        return t
    start = t.index('static bool\nacpm_channel_read(')
    end = t.index('/* A string of the APM', start)
    segment = t[start:end]
    segment = replace(segment, 'static bool\nacpm_channel_read(', '''/* SRAM offsets must be aligned and their whole range mapped, without overflow. */
static bool
acpm_range_valid(uint32_t offset, uint32_t bytes)
{
    return offset != 0 && !(offset & 3) && offset < ACPM_SRAM_SIZE &&
        bytes <= ACPM_SRAM_SIZE - offset;
}

static bool
acpm_channel_read(''')
    segment = replace(segment, 'if (index >= ap_max || channels == 0 || channels + (index + 1) * sizeof(*ch) > ACPM_SRAM_SIZE)',
                      'if (index >= ap_max || index >= 16 ||\n\t    !acpm_range_valid(channels, (index + 1) * sizeof(*ch)))')
    segment = replace(segment, 'ch->rx_base < ACPM_SRAM_SIZE && ch->tx_base < ACPM_SRAM_SIZE && ch->id <= 15;',
                      '''!(ch->q_elem_size & 3) && ch->id <= 15 &&
           acpm_range_valid(ch->rx_base, ch->q_len * ch->q_elem_size) &&
           acpm_range_valid(ch->tx_base, ch->q_len * ch->q_elem_size) &&
           acpm_range_valid(ch->rx_front, 4) && acpm_range_valid(ch->rx_rear, 4) &&
           acpm_range_valid(ch->tx_front, 4) && acpm_range_valid(ch->tx_rear, 4);''')
    segment = replace(segment, '\tif (!single && next == rd(acpm_sram + ch->rx_rear)) {',
                      '\tif (front >= ch->q_len || rd(acpm_sram + ch->rx_rear) >= ch->q_len) {\n'
                      '\t\ta51_report("a51gpu: ACPM: invalid receive indices on channel %u\\n", ch->id);\n'
                      '\t\treturn false;\n\t}\n\tif (!single && next == rd(acpm_sram + ch->rx_rear)) {')
    segment = replace(segment, '\tfor (uint32_t i = 0; i < 100000; i++) {',
                      '\tbool trace = acpm_seq <= 16 || cmd[2] == ACPM_FREQ_GET;\n'
                      '\t/* Retain first requests; periodic GETs are already only every 10s. */\n'
                      '\tif (trace) a51_report("a51gpu: ACPM request ch=%u seq=%u words=%08x/%08x/%08x/%08x\\n",\n'
                      '\t    ch->id, seq, cmd[0], cmd[1], cmd[2], cmd[3]);\n'
                      '\tfor (uint32_t i = 0; i < 100000; i++) {')
    segment = replace(segment, '\t\t\tfor (uint32_t w = 0; w < 4; w++) {\n\t\t\t\tcmd[w] = rd(acpm_sram + ch->tx_base + w * 4);',
                      '\t\t\t__asm__ volatile ("dmb sy" ::: "memory");\n'
                      '\t\t\tif (((rd(acpm_sram + ch->tx_base) >> 16) & 0x3f) != seq) {\n'
                      '\t\t\t\ta51_report("a51gpu: ACPM: stale single-slot answer ch=%u wanted seq=%u\\n", ch->id, seq);\n'
                      '\t\t\t\twr(acpm_mbox + ACPM_INTCR1, 1u << ch->id);\n'
                      '\t\t\t\tdelay(1);\n\t\t\t\tcontinue;\n\t\t\t}\n'
                      '\t\t\tfor (uint32_t w = 0; w < 4; w++) {\n\t\t\t\tcmd[w] = rd(acpm_sram + ch->tx_base + w * 4);')
    segment = replace(segment, '\t\tfor (uint32_t at = rear; at != tfront;',
                      '\t\tif (rear >= ch->q_len || tfront >= ch->q_len) {\n'
                      '\t\t\ta51_report("a51gpu: ACPM: invalid transmit indices ch=%u rear=%u front=%u\\n", ch->id, rear, tfront);\n'
                      '\t\t\treturn false;\n\t\t}\n'
                      '\t\t__asm__ volatile ("dmb sy" ::: "memory");\n'
                      '\t\tfor (uint32_t at = rear; at != tfront;')
    segment = segment.replace('\t\t\treturn true;',
                              '\t\t\tif (trace) a51_report("a51gpu: ACPM reply ch=%u seq=%u words=%08x/%08x/%08x/%08x\\n",\n'
                              '\t\t\t    ch->id, seq, cmd[0], cmd[1], cmd[2], cmd[3]);\n\t\t\treturn true;')
    segment = re.sub(r'\bprintf\(', 'a51_report(', segment)
    t = t[:start] + segment + t[end:]
    t = replace(t, '\t\tuint32_t is = rd(p + 32) & 0xff, stay = rd(p + 40) & 0xff;',
                '\t\tuint32_t is = rd(p + 32) & 0xff, stay = rd(p + 40) & 0xff;\n'
                '\t\tif (rd(p) > 31) { clock_said("invalid plugin id %u", rd(p)); return; }')
    t = replace(t, 'file == NULL || size == 0 || base == 0 || base + size > ACPM_SRAM_SIZE',
                'file == NULL || size == 0 || (size & 3) || id > 31 ||\n'
                '\t\t    size > ACPM_SRAM_SIZE || !acpm_range_valid(base, (uint32_t)size)')
    t = replace(t, '\t\tif (!answered) {', '\t\tif (!answered || !(rd(p + 32) & 0xff)) {')
    t = replace(t, 'not attached: no answer", id, name);', 'not attached: answer or attached-state missing", id, name);')
    # Important bring-up details must survive the daemon printf flood.
    start=t.index('static void\nclock_thread(')
    end=t.index('\n\tuint32_t was = khz_now[2];',start)
    t=t[:start]+re.sub(r'\bprintf\(', 'a51_report(', t[start:end])+t[end:]
    t=t.replace('DVFS is channel 5', 'DVFS is channel 0')
    return t


edit('drivers/power/hakios.battery.c', bridge)
edit('drivers/power/hakios.battery.cpp', power_source)
edit('xnu/files/bsd/sys/hakios.input.h', lambda t: replace(t,
     'void hakios_battery_report(const struct hakios_battery_state *state);',
     'void hakios_battery_report(const struct hakios_battery_state *state);\n'
     'void hakios_battery_report_source(const struct hakios_battery_state *state, bool from_dsp);\n'
     'void hakios_battery_invalidate(void);'))
driver = (HERE/'hakios.a51battery.c').read_text(encoding='utf-8')
driver = driver.replace('#include "a51-sm5713-decode.h"', (HERE/'a51-sm5713-decode.h').read_text(encoding='utf-8'))
driver = driver.replace('#include "a51-adc-monitor.c"', (HERE/'a51-adc-monitor.c').read_text(encoding='utf-8'))
save('devices/a51/drivers/power/hakios.a51battery.c', driver)
save('devices/a51/drivers/power/conf', '''# Dedicated Exynos battery bus; no Qualcomm charger path.
driver A51BATTERY
    file bsd/dev/hakios.a51battery.c
    help a51battery=1 register diagnostics, =2 measured Darwin battery status; no charging writes
''')
for config in ['devices/a51/configs/a51.config', '.config']:
    edit(config, lambda t: t.replace('# CONFIG_HAKIOS_BATTERY is not set', 'CONFIG_HAKIOS_BATTERY=y')
         + ('' if 'CONFIG_HAKIOS_A51BATTERY=y' in t else '\nCONFIG_HAKIOS_A51BATTERY=y\n'))
edit('devices/a51/drivers/gpu/hakios.a51gpu.c', acpm)
# Fix an early development snapshot with an over-broad printf substitution.
edit('devices/a51/drivers/gpu/hakios.a51gpu.c', lambda t: t.replace('sna51_report(', 'snprintf('))

# make-kernel synchronizes drivers; headers in xnu/files need their own update.
header = REPO/'xnu/files/bsd/sys/hakios.input.h'
save('xnu-src/xnu-8796.121.2/bsd/sys/hakios.input.h', header.read_text(encoding='utf-8'))


def audio(t):
    if 'A51_DEVICE_SERVICES_AUDIO' in t:
        return t
    extra = (HERE/'a51-audio-probe-extra.c').read_text(encoding='utf-8')
    t = replace(t, '#include <kern/startup.h>', '#include <kern/startup.h>\n#include <kern/clock.h>')
    t = replace(t, 'static void\na51audio_init(void)', extra+'\nstatic void\na51audio_init(void)')
    t = replace(t, '    loader_log_line("a51audio: baseline complete; DSP/DMA/I2C untouched; audio sink unavailable\\n");',
                '    a51_audio_services(step, cmu);\n'
                '    loader_log_line("a51audio: probe complete; DSP/DMA untouched; audio sink unavailable\\n");')
    return t


edit('devices/a51/drivers/audio/hakios.a51audio.c', audio)
edit('devices/a51/drivers/audio/hakios.a51audio.c', lambda t: replace(t, '#include <kern/startup.h>', '#include <kern/startup.h>\n#include <kern/clock.h>'))

records=[]
patch=[]
for before in sorted((OUT/'source-before').rglob('*')):
    if not before.is_file(): continue
    rel=before.relative_to(OUT/'source-before')
    current=REPO/rel
    text=current.read_text(encoding='utf-8')
    snapshot=OUT/'source'/rel
    snapshot.parent.mkdir(parents=True,exist_ok=True)
    snapshot.write_text(text,encoding='utf-8')
    records.append({'path':str(rel),'sha256':hashlib.sha256(text.encode()).hexdigest()})
    patch.extend(difflib.unified_diff(before.read_text(encoding='utf-8').splitlines(True),text.splitlines(True),fromfile='a/'+str(rel),tofile='b/'+str(rel)))
(OUT/'device-services.patch').write_text(''.join(patch),encoding='utf-8')
(OUT/'source-manifest.json').write_text(json.dumps({'files':records,'host_only':True,'charging_control_implemented':False,'speaker_playback_implemented':False},indent=2)+'\n',encoding='utf-8')
print('Battery bridge and ACPM diagnostics installed on host; phone untouched.')
