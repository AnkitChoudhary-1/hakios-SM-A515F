"""Add explicit open-network autojoin to A51's existing station service.

Runs in WSL. Exact replacements prevent silently patching an unexpected revision.
The older step-7 WPA2 diagnostic continues rejecting open configurations.
"""
import pathlib
import subprocess

REPO = pathlib.Path('/opt/a51-hakios/upstream-a51/hakios')
OUT = pathlib.Path(__file__).resolve().parents[1] / 'gpu-wifi'


def main():
    path = REPO / 'devices/a51/drivers/wifi/hakios.a51wifi.c'
    text = path.read_text(encoding='utf-8')
    edits = [
        ('/* fw/wifi.conf: ssid=NAME, psk=PASSPHRASE or pmk=64 hex digits. Its values are never printed. */',
         '/* fw/wifi.conf: ssid=NAME, psk=PASSPHRASE or pmk=64 hex digits; security=open for an open network. */'),
        ('uint8_t pmk[32], bool *have_pmk)', 'uint8_t pmk[32], bool *have_pmk, bool *open)'),
        ('\t*have_pmk = false;\n\tif (text == NULL)',
         '\t*have_pmk = false;\n\t*open = false;\n\tbool security_valid = true;\n\tif (text == NULL)'),
        ('\t\t} else if (n > 4 && memcmp(line, "psk=", 4)',
         '\t\t} else if (n >= 9 && memcmp(line, "security=", 9) == 0) {\n'
         '\t\t\t*open = n == 13 && memcmp(line + 9, "open", 4) == 0;\n'
         '\t\t\tsecurity_valid = *open || (n == 13 && memcmp(line + 9, "wpa2", 4) == 0);\n'
         '\t\t} else if (n > 4 && memcmp(line, "psk=", 4)'),
        ('return ssid[0] != 0 && (psk[0] != 0 || *have_pmk);',
         'return security_valid && ssid[0] != 0 &&\n'
         '\t    (*open ? (psk[0] == 0 && !*have_pmk) : (psk[0] != 0 || *have_pmk));'),
        ('bool have_pmk;', 'bool have_pmk, open;'),
        ('pmk, &have_pmk)', 'pmk, &have_pmk, &open)'),
        ('if (!wifi_conf(ssid, sizeof(ssid), psk, sizeof(psk), pmk, &have_pmk, &open))',
         'if (!wifi_conf(ssid, sizeof(ssid), psk, sizeof(psk), pmk, &have_pmk, &open) || open)'),
        ('what->security = HAKIOS_STA_WPA2_PSK;',
         'what->security = open ? HAKIOS_STA_OPEN : HAKIOS_STA_WPA2_PSK;'),
    ]
    for old, new in edits:
        expected = 2 if old in ('bool have_pmk;', 'pmk, &have_pmk)') else 1
        assert text.count(old) == expected, old
        text = text.replace(old, new)
    OUT.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    diff = subprocess.run(['git', 'diff', '--', 'drivers/wifi/hakios.a51wifi.c'],
                          cwd=REPO / 'devices/a51', capture_output=True, text=True, check=True).stdout
    assert diff
    (OUT / 'open-network.patch').write_text(diff, encoding='utf-8')
    print('Explicit open-network autojoin added; patch saved.')


if __name__ == '__main__':
    main()
