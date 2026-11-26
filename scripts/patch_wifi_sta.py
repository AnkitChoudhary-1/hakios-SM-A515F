import pathlib

wifi_files = [
    pathlib.Path("/opt/a51-hakios/upstream-a51/hakios/devices/a51/drivers/wifi/hakios.a51wifi.c"),
    pathlib.Path("/opt/a51-hakios/upstream-a51/hakios/xnu-src/xnu-8796.121.2/bsd/dev/hakios.a51wifi.c"),
]

for p in wifi_files:
    if p.exists():
        content = p.read_text(encoding="utf-8")
        target = "\t\ta51wpa_forget();\n\t\t(void)svc_vif(false);\n\t\tsvc.phase = HAKIOS_STA_IDLE;"
        replacement = "\t\ta51wpa_forget();\n\t\t/* keep VIF alive for retries */\n\t\tsvc.phase = HAKIOS_STA_IDLE;"
        if target in content:
            content = content.replace(target, replacement)
            p.write_text(content, encoding="utf-8")
            print(f"Updated VIF in {p}")
        else:
            print(f"Target not found in {p}")

sta_files = [
    pathlib.Path("/opt/a51-hakios/upstream-a51/hakios/drivers/wifi/hakios.sta.c"),
    pathlib.Path("/opt/a51-hakios/upstream-a51/hakios/xnu-src/xnu-8796.121.2/bsd/dev/hakios.sta.c"),
]

sta_target = """int
hakios_sta_ask_join_standing(const struct hakios_sta_join *what)
{
\tint error = hakios_sta_ask_join(what);

\tlck_mtx_lock(&sta_lock);
\tif (error == 0) {
\t\tstanding = *what;
\t}
\tlck_mtx_unlock(&sta_lock);
\treturn error;
}"""

sta_replacement = """int
hakios_sta_ask_join_standing(const struct hakios_sta_join *what)
{
\tlck_mtx_lock(&sta_lock);
\tfallback = *what;
\tlck_mtx_unlock(&sta_lock);

\tint error = hakios_sta_ask_join(what);

\tlck_mtx_lock(&sta_lock);
\tstanding = *what;
\tlck_mtx_unlock(&sta_lock);
\treturn error;
}"""

sta_retry_target = """\t\t\tlck_mtx_lock(&sta_lock);
\t\t\tif (error != 0 && fallback.ssid_length != 0 && !asked_join && !asked_leave && !asked_power) {
\t\t\t\tstanding = asked_join_what = fallback;
\t\t\t\tasked_join = true;
\t\t\t}
\t\t\tbzero(&fallback, sizeof(fallback));
\t\t\tlck_mtx_unlock(&sta_lock);"""

sta_retry_replacement = """\t\t\tlck_mtx_lock(&sta_lock);
\t\t\tif (error != 0 && fallback.ssid_length != 0 && !asked_join && !asked_leave && !asked_power) {
\t\t\t\tstanding = asked_join_what = fallback;
\t\t\t\tasked_join = true;
\t\t\t}
\t\t\tlck_mtx_unlock(&sta_lock);"""

for p in sta_files:
    if p.exists():
        content = p.read_text(encoding="utf-8")
        if sta_target in content:
            content = content.replace(sta_target, sta_replacement)
        if sta_retry_target in content:
            content = content.replace(sta_retry_target, sta_retry_replacement)
        p.write_text(content, encoding="utf-8")
        print(f"Updated sta logic in {p}")

print("Wi-Fi driver patch complete.")
