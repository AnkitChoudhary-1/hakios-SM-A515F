"""One-time, hash-guarded compiler-ordering fix and bounded panic diagnostics."""
from pathlib import Path
import difflib
import hashlib
import json

repo = Path('/opt/a51-hakios/upstream-a51/hakios')
out = Path(__file__).resolve().parents[1] / 'wifi-ordering-recovery'
names = ['devices/a51/drivers/wifi/hakios.a51wifi.c',
         'drivers/wifi/hakios.sta.c', 'xnu/files/bsd/sys/hakios.sta.h']
prior = json.loads((out.parent / 'wifi-stability-recovery/source-changes.json').read_text())
before = {name: (repo / name).read_bytes() for name in names}
for name, data in before.items():
    assert hashlib.sha256(data).hexdigest() == prior[name]['after_sha256'], name

source = before[names[0]].decode()
assert source.count('__asm__ volatile ("dc civac, %0" : : "r" (line));') == 2
assert source.count('__asm__ volatile ("dsb sy");') == 4
source = source.replace('__asm__ volatile ("dc civac, %0" : : "r" (line));',
                        '__asm__ volatile ("dc civac, %0" : : "r" (line) : "memory");')
source = source.replace('__asm__ volatile ("dsb sy");',
                        '__asm__ volatile ("dsb sy" : : : "memory");')
source = source.replace('static void\ncache_out(vm_offset_t start, vm_size_t size)',
'''/* Firmware is not cache-coherent with the AP. Hardware completion AND a compiler
 * memory barrier are needed around ownership transfer: asm volatile alone does
 * not constrain ordinary descriptor/payload loads and stores. */
static void
cache_out(vm_offset_t start, vm_size_t size)''', 1)

diagnostics = r'''
/* Numeric fault records only, no network payloads. Eight words fit hakios_tl's
 * 192-byte line. printf stays in msgbuf until kernel return on this boot, so
 * live diagnostics must explicitly use the loader timeline. */
static void
wifi_trace_words(const char *tag, const uint32_t *words, uint32_t count)
{
	if (count > 256) { count = 256; }
	for (uint32_t i = 0; i < count; i += 8) {
		char line[160];
		size_t n = snprintf(line, sizeof(line), "tl: wifi fault %.16s %03x:", tag, i * 4);
		for (uint32_t j = i; j < count && j < i + 8; j++) {
			n += snprintf(line + n, sizeof(line) - n, " %08x", words[j]);
		}
		hakios_tl("%s\n", line);
	}
}

static void
wifi_trace_fault(void)
{
	uint32_t record[256];
	if (runtime_panic_offset && !(runtime_panic_offset & 3) && runtime_panic_offset <= WLBT_MEMORY - sizeof(record)) {
		cache_out(wlbt_memory + runtime_panic_offset, sizeof(record));
		memcpy(record, (const void *)(wlbt_memory + runtime_panic_offset), sizeof(record));
		uint32_t bytes = record[1], count = 4, sum = 0xa5a5a5a5;
		if (record[0] == 2 && bytes >= 20 && bytes < sizeof(record) && !(bytes & 3)) {
			for (uint32_t i = 0; i < bytes / 4 - 1; i++) { sum ^= record[i]; }
			if (sum == record[bytes / 4 - 1]) { count = bytes / 4; }
		}
		wifi_trace_words("r4-panic", record, count);
		/* Samsung v2 field 52 references an optional v1 stack record. Its
		 * layout has version/byte length, no checksum. Reject malformed bounds. */
		if (count > 53 && record[52] && !(record[52] & 3) && record[52] <= WLBT_MEMORY - sizeof(record)) {
			vm_offset_t stack = wlbt_memory + record[52];
			cache_out(stack, sizeof(record));
			memcpy(record, (const void *)stack, sizeof(record));
			if (record[0] == 1 && record[1] >= 8 && record[1] < sizeof(record) && !(record[1] & 3)) {
				wifi_trace_words("r4-stack", record, record[1] / 4);
			}
		}
	}
	/* Quiesced station and gated producers, before any reset clears memory. */
	vm_offset_t sb = wlbt_memory + hip_base + HIP_SCOREBOARD;
	cache_out(sb, 128);
	hakios_tl("tl: wifi fault queues host %02x %02x %02x %02x %02x %02x fw %02x %02x %02x %02x %02x %02x\n",
	    *(volatile uint8_t *)(sb+0), *(volatile uint8_t *)(sb+1), *(volatile uint8_t *)(sb+2),
	    *(volatile uint8_t *)(sb+3), *(volatile uint8_t *)(sb+4), *(volatile uint8_t *)(sb+5),
	    *(volatile uint8_t *)(sb+64), *(volatile uint8_t *)(sb+65), *(volatile uint8_t *)(sb+66),
	    *(volatile uint8_t *)(sb+67), *(volatile uint8_t *)(sb+68), *(volatile uint8_t *)(sb+69));
}

'''
needle = 'static void\nwifi_fault(vm_offset_t mbox, const char *reason)'
assert source.count(needle) == 1
source = source.replace(needle, diagnostics + needle)
needle = '\twifi_dump[0] = 0;\n\tif (runtime_panic_offset && runtime_panic_offset <= WLBT_MEMORY - 1024)'
assert source.count(needle) == 1
source = source.replace(needle, '\twifi_trace_fault();\n' + needle)
source = source.replace("/* the firmware's state: its panic record (word 2: its log string's offset, 3: the panic id), the queues */",
                        "/* Firmware state: raw v2 panic words 2/3 and queue indices. Full field layout remains undecoded. */")

after = dict(before)
after[names[0]] = source.encode()
changes = {}
patches = []
for name in names:
    for phase, collection in [('before', before), ('after', after)]:
        target = out / ('source-' + phase) / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(collection[name])
    changes[name] = {'before_sha256': hashlib.sha256(before[name]).hexdigest(),
                     'after_sha256': hashlib.sha256(after[name]).hexdigest()}
    patches.extend(difflib.unified_diff(before[name].decode().splitlines(True),
                                       after[name].decode().splitlines(True),
                                       fromfile='a/' + name, tofile='b/' + name))
(out / 'source-changes.json').write_text(json.dumps(changes, indent=2) + '\n')
(out / 'wifi-ordering.patch').write_text(''.join(patches))
(repo / names[0]).write_bytes(after[names[0]])
(repo / 'xnu-src/xnu-8796.121.2/bsd/dev/hakios.a51wifi.c').write_bytes(after[names[0]])
print(json.dumps(changes, indent=2))
