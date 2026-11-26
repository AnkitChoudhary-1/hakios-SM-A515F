"""Add an opt-in A51 audio power/clock baseline. Host source changes only.

Stage 1 deliberately has no MMIO writes, DSP start or amplifier enable. Values
come from this SM-A515F's live revision-07 DT and Samsung's Exynos9610 CAL/ABOX
sources, not the disabled RT5510 codec in the generic device tree.
"""
from pathlib import Path
import hashlib
import json

REPO = Path('/opt/a51-hakios/upstream-a51/hakios')
OUT = Path(__file__).resolve().parents[1] / 'audio-performance'
SOURCE = r'''/* A51 Exynos9611 audio bring-up; boot-arg a51audio=1.
 * Evidence: SM-A515F revision-07 live DT; Samsung Exynos9610 cmucal-sfr.c,
 * pmucal_local_exynos9610.h and sound/soc/samsung/abox/abox.c.
 * The speaker is TAS2562 at HSI2C3 0x11d10000, address 0x4c, UAIF2.
 * Stage 1 reads PMU and, only if DISPAUD is already powered, its CMU.
 * It does not touch ABOX, the SysMMU, I2C or the speaker. No sink is
 * registered until real playback has been implemented and tested.
 */
#include <kern/startup.h>
#include <libkern/libkern.h>
#include <mach/mach_types.h>
#include <pexpert/pexpert.h>
#include <sys/systm.h>

extern vm_offset_t ml_io_map(vm_offset_t phys_addr, vm_size_t size);
extern void loader_log_line(const char *line);

static uint32_t
audio_rd(vm_offset_t address)
{
    return *(volatile uint32_t *)address;
}

static void
a51audio_init(void)
{
    uint32_t step = 0;
    if (!PE_parse_boot_argn("a51audio", &step, sizeof(step)) || step == 0) {
        return;
    }
    loader_log_line("a51audio: stage 1: PMU/CMU baseline; TAS2562/UAIF2; no playback\n");
    vm_offset_t pmu = ml_io_map(0x11860000UL, 0x5000);
    if (!pmu) {
        loader_log_line("a51audio: PMU mapping failed; stopped\n");
        return;
    }
    uint32_t status = audio_rd(pmu + 0x4004);
    char line[512];
    snprintf(line, sizeof(line),
        "a51audio: DISPAUD config=%08x status=%08x; ABOX CPU config=%08x status=%08x option=%08x\n",
        audio_rd(pmu + 0x4000), status, audio_rd(pmu + 0x2520),
        audio_rd(pmu + 0x2524), audio_rd(pmu + 0x2528));
    loader_log_line(line);
    if ((status & 0xf) != 0xf) {
        loader_log_line("a51audio: DISPAUD off; gated register reads skipped\n");
        return;
    }
    vm_offset_t cmu = ml_io_map(0x14980000UL, 0x4000);
    if (!cmu) {
        loader_log_line("a51audio: CMU mapping failed; stopped\n");
        return;
    }
    snprintf(line, sizeof(line),
        "a51audio: AUD PLL con0=%08x con3=%08x; AUDIF div=%08x; CPU mux=%08x div=%08x; bus mux=%08x div=%08x\n",
        audio_rd(cmu + 0x160), audio_rd(cmu + 0x16c), audio_rd(cmu + 0x1800),
        audio_rd(cmu + 0x1004), audio_rd(cmu + 0x180c),
        audio_rd(cmu + 0x1000), audio_rd(cmu + 0x1808));
    loader_log_line(line);
    snprintf(line, sizeof(line),
        "a51audio: UAIF2 mux=%08x div=%08x gate=%08x reset-gate=%08x; ABOX ACLK gate=%08x CCLK=%08x; QCH CPU=%08x ACLK=%08x BCLK2=%08x\n",
        audio_rd(cmu + 0x1018), audio_rd(cmu + 0x182c),
        audio_rd(cmu + 0x2008), audio_rd(cmu + 0x2018),
        audio_rd(cmu + 0x2020), audio_rd(cmu + 0x2030),
        audio_rd(cmu + 0x3000), audio_rd(cmu + 0x3014), audio_rd(cmu + 0x3020));
    loader_log_line(line);
    loader_log_line("a51audio: baseline complete; DSP/DMA/I2C untouched; audio sink unavailable\n");
}

STARTUP(EARLY_BOOT, STARTUP_RANK_LAST, a51audio_init);
'''
CONF = '''# A51 audio bring-up, separate from the Qualcomm SOUND/ADSP drivers.
driver A51AUDIO
\tfile bsd/dev/hakios.a51audio.c
\thelp a51audio=1: read-only Exynos audio power and clock baseline
'''
folder = REPO / 'devices/a51/drivers/audio'
folder.mkdir(exist_ok=True)
for name, contents in [('hakios.a51audio.c', SOURCE), ('conf', CONF)]:
    target = folder / name
    if target.exists() and target.read_text(encoding='utf-8') != contents:
        raise RuntimeError(f'Refusing to overwrite differing source: {target}')
    target.write_text(contents, encoding='utf-8')
    (OUT / name).write_text(contents, encoding='utf-8')
for config in [REPO / 'devices/a51/configs/a51.config', REPO / '.config']:
    contents = config.read_text(encoding='utf-8')
    if 'CONFIG_HAKIOS_A51AUDIO=y' not in contents:
        (OUT / (config.name + '.before-audio')).write_text(contents, encoding='utf-8')
        config.write_text(contents + '\n# opt-in read-only audio bring-up\nCONFIG_HAKIOS_A51AUDIO=y\n', encoding='utf-8')
(OUT / 'audio-source-manifest.json').write_text(json.dumps({
    'source': str(folder / 'hakios.a51audio.c'),
    'sha256': hashlib.sha256(SOURCE.encode()).hexdigest(),
    'stage': 1, 'mmio_writes': False, 'audio_playback_implemented': False,
    'hardware': 'SM-A515F rev07, TAS2562/ABOX UAIF2',
}, indent=2) + '\n', encoding='utf-8')
print('A51 audio baseline enabled; host files only.')
