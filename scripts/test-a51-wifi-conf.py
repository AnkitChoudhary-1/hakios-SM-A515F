"""Compile the actual driver parser on the host and check open/WPA2 configurations."""
import pathlib
import subprocess

REPO = pathlib.Path('/opt/a51-hakios/upstream-a51/hakios')
OUT = pathlib.Path(__file__).resolve().parents[1] / 'gpu-wifi'
WORK = pathlib.Path(__file__).resolve().parents[2] / 'work' / 'wifi-parser'


def main():
    text = (REPO / 'devices/a51/drivers/wifi/hakios.a51wifi.c').read_text(encoding='utf-8')
    parser = text[text.index('static bool\nwifi_conf('):text.index('/* Does an RSN element')]
    code = '''#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <assert.h>
#include <stdio.h>
static const char *config;
static const char *hakios_image_file(const char *a, const char *b, uint64_t *n, void *unused) {
    (void)a; (void)b; (void)unused; *n = config ? strlen(config) : 0; return config;
}
'''+parser+'''
static void check(const char *text, bool expected, bool expect_open) {
    char ssid[33], psk[64]; uint8_t pmk[32]; bool have_pmk, open;
    config = text;
    bool result = wifi_conf(ssid, sizeof(ssid), psk, sizeof(psk), pmk, &have_pmk, &open);
    assert(result == expected);
    if (result) assert(open == expect_open);
}
int main(void) {
    check(NULL, false, false);
    check("ssid=OPPO K13 5G B93C\\nsecurity=open\\n", true, true);
    check("security=open\\r\\nssid=OPPO K13 5G B93C\\r\\n", true, true);
    check("ssid=OPPO K13 5G B93C\\n", false, false);
    check("ssid=test\\npsk=12345678\\n", true, false);
    check("ssid=test\\nsecurity=wpa2\\npsk=12345678\\n", true, false);
    check("ssid=test\\npmk=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\\n", true, false);
    check("ssid=test\\nsecurity=open\\npsk=12345678\\n", false, false);
    check("ssid=test\\nsecurity=wpa3\\npsk=12345678\\n", false, false);
    check("security=open\\n", false, false);
    check("ssid=12345678901234567890123456789012345\\nsecurity=open\\n", false, false);
    check("ssid=test\\npmk=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx\\n", false, false);
    puts("12 actual-parser configuration cases passed");
}
'''
    WORK.mkdir(parents=True, exist_ok=True)
    source = WORK / 'parser.c'
    source.write_text(code, encoding='utf-8')
    subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror', str(source), '-o', str(WORK / 'parser')], check=True)
    result = subprocess.run([str(WORK / 'parser')], capture_output=True, text=True, check=True)
    (OUT / 'parser-validation.txt').write_text(result.stdout, encoding='utf-8')
    print(result.stdout, end='')


if __name__ == '__main__':
    main()
