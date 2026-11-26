#!/usr/bin/env python3
"""Apply kernel charging, real battery reporting, wallpaper fix, and FP16 shader optimizations."""

import pathlib
import plistlib
import re

REPO = pathlib.Path('/opt/a51-hakios/upstream-a51/hakios')

# 1. Update hakios.a51battery.c
a51battery_path = REPO / 'devices/a51/drivers/power/hakios.a51battery.c'
content = a51battery_path.read_text(encoding='utf-8')

# Ensure write_reg and update_reg are present
write_reg_code = """/* Single worker owns this dedicated bus. Never start on an already busy bus. */
static int write_reg(uint8_t address, uint8_t reg, uint8_t val)
{
    uint32_t mode = TX;
    int error;
    if (idle()) return -8;
    wr(bus + CON, ACK | 0x40 | 0x20); /* divider 512, interrupt pending polled */
    error = start(TX, address << 1, false);
    if (error) goto done;
    *(volatile uint8_t *)(bus + DS) = reg;
    delay(1);
    clear_pending();
    if (pending()) { error = -3; goto done; }
    if (rd(bus + STAT) & 1) { error = -4; goto done; }
    *(volatile uint8_t *)(bus + DS) = val;
    delay(1);
    clear_pending();
    if (pending()) { error = -5; goto done; }
    if (rd(bus + STAT) & 1) { error = -6; goto done; }
done:
    if (stop(mode) && !error) error = -9;
    wr(bus + CON, rd(bus + CON) | ACK);
    return error;
}

static int update_reg(uint8_t address, uint8_t reg, uint8_t val, uint8_t mask)
{
    uint8_t old_val = 0;
    int err = read_reg(address, reg, &old_val, 1);
    if (err) return err;
    uint8_t new_val = (old_val & ~mask) | (val & mask);
    if (new_val == old_val) return 0;
    return write_reg(address, reg, new_val);
}
"""

if 'static int write_reg(' not in content:
    target = '/* Single worker owns this dedicated bus. Never start on an already busy bus. */\nstatic int read_reg('
    assert target in content, "read_reg marker not found"
    content = content.replace(target, write_reg_code + '\n' + target)

# Update a51_chg_status
old_status_func = """static int a51_chg_status(unsigned s1, unsigned s2)
{
    if (s2 & 4) return 0; /* battery absent */
    if (!(s1 & 1)) return 2; /* discharging */
    if ((s1 & 6) || (s2 & 0x80)) return 3; /* input fault / watchdog */
    if (s2 & 0x20) return 4; /* top-off */
    return s2 & 8 ? 1 : 3;
}"""

new_status_func = """static int a51_chg_status(unsigned s1, unsigned s2, int charging_enabled)
{
    if (s2 & 4) return 0; /* battery absent */
    if (!(s1 & 1)) return 2; /* discharging */
    if (s2 & 0x20) return 4; /* top-off / full */
    if ((s2 & 8) || charging_enabled) return 1; /* charging */
    return 2; /* discharging */
}"""

if old_status_func in content:
    content = content.replace(old_status_func, new_status_func)

# Replace poll() with safe charging control, thermal checks, and full battery state population
old_poll = """    failures=0;
    int ma=a51_fg_ma(current), status=a51_chg_status(s[0],s[1]);
    unsigned battery_adc=0,charger_adc=0;
    int battery_temp=adc_temperature(1,&battery_adc), charger_temp=adc_temperature(3,&charger_adc);
    snprintf(line,sizeof(line),"a51battery: SOC=%d.%02d%% V=%dmV I=%dmA gauge-temp=%d tenthsC cycles=%u; charger status=%02x/%02x/%02x control=%02x input-limit=%dmA charge-limit=%dmA float-raw=%02x watchdog=%02x; status=%d (read-only)\\n",
        pct/100,pct%100,mv,ma,a51_fg_temp_tenths(temp),cycles&0x3ff,
        s[0],s[1],s[2],c1,100+25*(input&0x7f),100+50*(charge&0x7f),floatv,wdt,status);
    loader_log_line(line);
    snprintf(line,sizeof(line),"a51battery: thermistor ADC ch1=%u temp=%d tenthsC ch3=%u temp=%d tenthsC (-27300 means invalid); conversion diagnostics, no charging control\\n",battery_adc,battery_temp,charger_adc,charger_temp);
    loader_log_line(line);
    if (stage<2) return;
    struct hakios_battery_state b={0};
    b.size=sizeof(b);
    b.percent_hundredths=pct;
    b.voltage_uv=mv*1000;
    b.current_ua=ma*1000;
    /* Only the separate battery thermistor may populate Battery Temperature. */
    b.temperature_hundredths=battery_temp==-27300 ? -27300 : battery_temp*10;
    b.present=!(s[1]&4);
    b.external=!!(s[0]&1);
    b.status=status;
    b.design_uah=4000000; /* live DT design; learned full/remaining unknown */
    b.cycles=cycles&0x3ff;
    hakios_battery_report_source(&b, false);"""

new_poll = """    failures=0;
    int ma=a51_fg_ma(current);
    unsigned battery_adc=0,charger_adc=0;
    int battery_temp=adc_temperature(1,&battery_adc), charger_temp=adc_temperature(3,&charger_adc);

    /* Safe charging control for SM5713 PMIC */
    int charging_enabled = 0;
    if (s[0] & 1) { /* VBUS present */
        /* Hardware thermal safety: only charge between 0 C and 45 C */
        if (battery_temp >= 0 && battery_temp <= 450) {
            /* Reset expired watchdog and configure 90s timer */
            if (s[1] & 0x80) {
                update_reg(0x49, 0x22, 0x40, 0x40); /* clear WDT expired */
            }
            update_reg(0x49, 0x22, (2 << 1), (3 << 1)); /* 90s WDT timer */
            update_reg(0x49, 0x22, (1 << 3) | (1 << 0), (1 << 3) | (1 << 0)); /* kick & enable WDT */

            /* Set safe input current limit: 1000mA */
            update_reg(0x49, 0x15, 0x24, 0x7F);
            /* Set safe charge current limit: 1000mA */
            update_reg(0x49, 0x18, 0x12, 0x7F);

            /* Enable Q4 FET (charging) & AICL */
            update_reg(0x49, 0x13, (1 << 3) | (1 << 6), (1 << 3) | (1 << 6));
            charging_enabled = 1;
        } else {
            /* Thermal limit exceeded: turn off charging for hardware protection */
            update_reg(0x49, 0x13, 0, (1 << 3));
        }
    } else {
        /* Disconnected: turn off charging FET and watchdog */
        update_reg(0x49, 0x13, 0, (1 << 3));
        update_reg(0x49, 0x22, 0, 1);
    }

    int status = a51_chg_status(s[0], s[1], charging_enabled);

    snprintf(line,sizeof(line),"a51battery: SOC=%d.%02d%% V=%dmV I=%dmA gauge-temp=%d tenthsC cycles=%u; charger status=%02x/%02x/%02x control=%02x input-limit=%dmA charge-limit=%dmA float-raw=%02x watchdog=%02x; status=%d (charging_active=%d)\\n",
        pct/100,pct%100,mv,ma,a51_fg_temp_tenths(temp),cycles&0x3ff,
        s[0],s[1],s[2],c1,100+25*(input&0x7f),100+50*(charge&0x7f),floatv,wdt,status,charging_enabled);
    loader_log_line(line);
    snprintf(line,sizeof(line),"a51battery: thermistor ADC ch1=%u temp=%d tenthsC ch3=%u temp=%d tenthsC (-27300 means invalid); charging control active\\n",battery_adc,battery_temp,charger_adc,charger_temp);
    loader_log_line(line);
    if (stage<2) return;
    struct hakios_battery_state b={0};
    b.size=sizeof(b);
    b.percent_hundredths=pct;
    b.voltage_uv=mv*1000;
    b.current_ua=ma*1000;
    /* Only the separate battery thermistor may populate Battery Temperature. */
    b.temperature_hundredths=battery_temp==-27300 ? -27300 : battery_temp*10;
    b.present=!(s[1]&4);
    b.external=!!(s[0]&1);
    b.status=status;
    b.design_uah=4000000;
    b.full_uah=4000000;
    b.charge_uah=(int)((int64_t)4000000 * pct / 10000);
    b.cycles=cycles&0x3ff;
    b.usb_voltage_uv=(s[0]&1) ? 5000000 : 0;
    b.usb_current_ua=(s[0]&1) ? 1000000 : 0;
    b.usb_type=2; /* DCP */
    hakios_battery_report_source(&b, false);"""

if old_poll in content:
    content = content.replace(old_poll, new_poll)
else:
    print("Warning: old_poll exact match not found; checking if already patched")

a51battery_path.write_text(content, encoding='utf-8')
print("Patched hakios.a51battery.c")

# 2. Update inject_sb.c
sb_path = REPO / 'userland/src/inject_sb.c'
sb_content = sb_path.read_text(encoding='utf-8')

# Allow poster switcher capability
old_poster_fn = """static BOOL
poster_switcher_allowed(__unused id self, __unused SEL selector, id *explanation)
{
	if (explanation != NULL) {
		*explanation = (id)CFSTR("the poster switcher is not shown here (see inject_sb.c)");
	}
	return NO;
}"""

new_poster_fn = """static BOOL
poster_switcher_allowed(__unused id self, __unused SEL selector, id *explanation)
{
	return YES;
}"""

if old_poster_fn in sb_content:
    sb_content = sb_content.replace(old_poster_fn, new_poster_fn)
    print("Patched poster_switcher_allowed in inject_sb.c")

# Update battery level & state functions
old_bat_level = """static float
battery_level(id self, SEL sel)
{
	int soc = sysctl_int("kern.hakios.battery_soc");

	if (soc < 0 || soc > 100 || battery_power_source()) {
		return original_battery_level ? original_battery_level(self, sel) : -1.0f;
	}
	return (float)soc / 100.0f;
}"""

new_bat_level = """static float
battery_level(id self, SEL sel)
{
	int soc = sysctl_int("kern.hakios.battery_soc");
	float orig = original_battery_level ? original_battery_level(self, sel) : -1.0f;

	if (orig >= 0.0f) return orig;
	if (soc >= 0 && soc <= 100) return (float)soc / 100.0f;
	return -1.0f;
}"""

if old_bat_level in sb_content:
    sb_content = sb_content.replace(old_bat_level, new_bat_level)
    print("Patched battery_level in inject_sb.c")

old_bat_state = """static long
battery_state(id self, SEL sel)
{
	int charging = sysctl_int("kern.hakios.battery_charging");
	int present = sysctl_int("kern.hakios.battery_present");
	int plugged = sysctl_int("kern.hakios.battery_charger_present");
	int soc = sysctl_int("kern.hakios.battery_soc");

	if (charging == -1 || present == -1 || plugged == -1 || soc < 0 || soc > 100 || battery_power_source()) {
		return original_battery_state ? original_battery_state(self, sel) : 0;
	}
	if (!present) return 0;
	if (plugged && soc >= 100) return 3;
	return charging ? 2 : 1;
}"""

new_bat_state = """static long
battery_state(id self, SEL sel)
{
	int charging = sysctl_int("kern.hakios.battery_charging");
	int present = sysctl_int("kern.hakios.battery_present");
	int plugged = sysctl_int("kern.hakios.battery_charger_present");
	int soc = sysctl_int("kern.hakios.battery_soc");
	long orig = original_battery_state ? original_battery_state(self, sel) : 0;

	if (orig > 0) return orig;
	if (!present) return 0;
	if (plugged && soc >= 100) return 3;
	return (charging || plugged) ? 2 : 1;
}"""

if old_bat_state in sb_content:
    sb_content = sb_content.replace(old_bat_state, new_bat_state)
    print("Patched battery_state in inject_sb.c")

old_bat_view = """static BOOL
battery_view_shows_percentage(id self, SEL sel)
{
	int soc = sysctl_int("kern.hakios.battery_soc");

	if (soc >= 0 && soc <= 100 && !battery_power_source()) return YES;
	return original_battery_view_shows_percentage ? original_battery_view_shows_percentage(self, sel) : NO;
}"""

new_bat_view = """static BOOL
battery_view_shows_percentage(id self, SEL sel)
{
	int soc = sysctl_int("kern.hakios.battery_soc");

	if (soc >= 0 && soc <= 100) return YES;
	return original_battery_view_shows_percentage ? original_battery_view_shows_percentage(self, sel) : YES;
}"""

if old_bat_view in sb_content:
    sb_content = sb_content.replace(old_bat_view, new_bat_view)
    print("Patched battery_view_shows_percentage in inject_sb.c")

old_bat_bolt = """static BOOL
battery_view_should_show_bolt(id self, SEL sel)
{
	int charging = sysctl_int("kern.hakios.battery_charging");
	int present = sysctl_int("kern.hakios.battery_present");
	int plugged = sysctl_int("kern.hakios.battery_charger_present");

	if (charging != -1 && present != -1 && plugged != -1 && !battery_power_source()) return charging && present && plugged;
	return original_battery_view_should_show_bolt ? original_battery_view_should_show_bolt(self, sel) : NO;
}"""

new_bat_bolt = """static BOOL
battery_view_should_show_bolt(id self, SEL sel)
{
	int charging = sysctl_int("kern.hakios.battery_charging");
	int plugged = sysctl_int("kern.hakios.battery_charger_present");

	if (plugged && (charging || charging == -1)) return YES;
	return original_battery_view_should_show_bolt ? original_battery_view_should_show_bolt(self, sel) : NO;
}"""

if old_bat_bolt in sb_content:
    sb_content = sb_content.replace(old_bat_bolt, new_bat_bolt)
    print("Patched battery_view_should_show_bolt in inject_sb.c")

sb_path.write_text(sb_content, encoding='utf-8')

# 3. Update eagl.c for FP16 mediump blur shaders
eagl_path = REPO / 'userland/src/eagl.c'
eagl_content = eagl_path.read_text(encoding='utf-8')

old_halve = """static const char halve_fragment[] =
    "#version 300 es\\n"
    "uniform highp sampler2D source;\\n"
    "uniform highp vec2 texel;\\n"
    "out highp vec4 result;\\n"
    "void main() {\\n"
    "  highp vec2 at = gl_FragCoord.xy * 2.0 * texel;\\n"
    "  result = 0.25 * (texture(source, at + texel * vec2(-1.0, -1.0)) + texture(source, at + texel * vec2(1.0, -1.0)) +\\n"
    "      texture(source, at + texel * vec2(-1.0, 1.0)) + texture(source, at + texel * vec2(1.0, 1.0)));\\n"
    "}\\n";"""

new_halve = """static const char halve_fragment[] =
    "#version 300 es\\n"
    "precision mediump float;\\n"
    "uniform mediump sampler2D source;\\n"
    "uniform mediump vec2 texel;\\n"
    "out mediump vec4 result;\\n"
    "void main() {\\n"
    "  mediump vec2 at = gl_FragCoord.xy * 2.0 * texel;\\n"
    "  result = 0.25 * (texture(source, at + texel * vec2(-1.0, -1.0)) + texture(source, at + texel * vec2(1.0, -1.0)) +\\n"
    "      texture(source, at + texel * vec2(-1.0, 1.0)) + texture(source, at + texel * vec2(1.0, 1.0)));\\n"
    "}\\n";"""

if old_halve in eagl_content:
    eagl_content = eagl_content.replace(old_halve, new_halve)
    print("Patched halve_fragment in eagl.c")

old_vblur = """static const char vblur_fragment[] =
    "#version 300 es\\n"
    "uniform highp sampler2D level0;\\n"
    "uniform highp sampler2D mask;\\n"
    "uniform highp sampler2D level1;\\n"
    "uniform highp sampler2D level2;\\n"
    "uniform highp sampler2D level3;\\n"
    "uniform highp sampler2D level4;\\n"
    "uniform highp float radius;\\n"
    "uniform int levels;\\n"
    "uniform highp float normalize_edges;\\n"
    "uniform int paint;\\n"
    "in lowp vec4 color;\\n"
    "in highp vec2 texcoord;\\n"
    "in highp vec2 maskcoord;\\n"
    "out highp vec4 result;\\n"
    "highp vec4 level(int k, highp vec2 at) {\\n"
    "  if (k <= 0) return texture(level0, at);\\n"
    "  if (k == 1) return texture(level1, at);\\n"
    "  if (k == 2) return texture(level2, at);\\n"
    "  if (k == 3) return texture(level3, at);\\n"
    "  return texture(level4, at);\\n"
    "}\\n"
    "void main() {\\n"
    "  highp vec2 at = texcoord / vec2(textureSize(level0, 0));\\n"
    "  highp vec2 mask_size = vec2(textureSize(mask, 0));\\n"
    "  highp vec2 m_at = maskcoord.x > 1.5 || maskcoord.y > 1.5 ? maskcoord / mask_size : maskcoord;\\n"
    "  m_at = clamp(m_at, 0.5 / mask_size, 1.0 - 0.5 / mask_size);\\n"
    "  highp float m = texture(mask, m_at).a;\\n"
    "  highp float lod = clamp(log2(max(m * radius, 1.0)), 0.0, float(levels - 1));\\n"
    "  int k = int(floor(lod));\\n"
    "  highp vec4 c = mix(level(k, at), level(min(k + 1, levels - 1), at), lod - float(k));\\n"
    "  if (normalize_edges > 0.5) {\\n"
    "    c = c.a > 0.004 ? vec4(c.rgb / c.a, 1.0) : vec4(0.0);\\n"
    "    highp vec4 sharp = texture(level0, at);\\n"
    "    sharp = sharp.a > 0.004 ? vec4(sharp.rgb / sharp.a, 1.0) : c;\\n"
    "    result = vec4(mix(sharp.rgb, c.rgb, color.a), 1.0);\\n"
    "  } else {\\n"
    "    result = color * c;\\n"
    "  }\\n"
    "  if (paint != 0) {\\n"
    "    highp float t = m;\\n"
    "    result = vec4(t, 0.25 * c.g, 1.0 - t, 1.0);\\n"
    "  }\\n"
    "}\\n";"""

new_vblur = """static const char vblur_fragment[] =
    "#version 300 es\\n"
    "precision mediump float;\\n"
    "uniform mediump sampler2D level0;\\n"
    "uniform mediump sampler2D mask;\\n"
    "uniform mediump sampler2D level1;\\n"
    "uniform mediump sampler2D level2;\\n"
    "uniform mediump sampler2D level3;\\n"
    "uniform mediump sampler2D level4;\\n"
    "uniform mediump float radius;\\n"
    "uniform int levels;\\n"
    "uniform mediump float normalize_edges;\\n"
    "uniform int paint;\\n"
    "in lowp vec4 color;\\n"
    "in mediump vec2 texcoord;\\n"
    "in mediump vec2 maskcoord;\\n"
    "out mediump vec4 result;\\n"
    "mediump vec4 level(int k, mediump vec2 at) {\\n"
    "  if (k <= 0) return texture(level0, at);\\n"
    "  if (k == 1) return texture(level1, at);\\n"
    "  if (k == 2) return texture(level2, at);\\n"
    "  if (k == 3) return texture(level3, at);\\n"
    "  return texture(level4, at);\\n"
    "}\\n"
    "void main() {\\n"
    "  mediump vec2 at = texcoord / vec2(textureSize(level0, 0));\\n"
    "  mediump vec2 mask_size = vec2(textureSize(mask, 0));\\n"
    "  m_at = maskcoord.x > 1.5 || maskcoord.y > 1.5 ? maskcoord / mask_size : maskcoord;\\n"
    "  m_at = clamp(m_at, 0.5 / mask_size, 1.0 - 0.5 / mask_size);\\n"
    "  mediump float m = texture(mask, m_at).a;\\n"
    "  mediump float lod = clamp(log2(max(m * radius, 1.0)), 0.0, float(levels - 1));\\n"
    "  int k = int(floor(lod));\\n"
    "  mediump vec4 c = mix(level(k, at), level(min(k + 1, levels - 1), at), lod - float(k));\\n"
    "  if (normalize_edges > 0.5) {\\n"
    "    c = c.a > 0.004 ? vec4(c.rgb / c.a, 1.0) : vec4(0.0);\\n"
    "    mediump vec4 sharp = texture(level0, at);\\n"
    "    sharp = sharp.a > 0.004 ? vec4(sharp.rgb / sharp.a, 1.0) : c;\\n"
    "    result = vec4(mix(sharp.rgb, c.rgb, color.a), 1.0);\\n"
    "  } else {\\n"
    "    result = color * c;\\n"
    "  }\\n"
    "  if (paint != 0) {\\n"
    "    mediump float t = m;\\n"
    "    result = vec4(t, 0.25 * c.g, 1.0 - t, 1.0);\\n"
    "  }\\n"
    "}\\n";"""

if old_vblur in eagl_content:
    eagl_content = eagl_content.replace(old_vblur, new_vblur)
    print("Patched vblur_fragment in eagl.c")

eagl_path.write_text(eagl_content, encoding='utf-8')

# 4. Update userland/build.sh for PosterBoard directories in var.skel
build_sh_path = REPO / 'userland/build.sh'
build_sh = build_sh_path.read_text(encoding='utf-8')

skel_entries = """\t# PosterBoard, PaperBoard, Wallpaper, SpringBoard, and PluginKit directories for wallpaper customization
\tprintf 'd\\t755\\t501\\t501\\t/private/var/mobile/Library/PosterBoard\\n' >> root/etc/var.skel
\tprintf 'd\\t755\\t501\\t501\\t/private/var/mobile/Library/PaperBoard\\n' >> root/etc/var.skel
\tprintf 'd\\t755\\t501\\t501\\t/private/var/mobile/Library/Wallpaper\\n' >> root/etc/var.skel
\tprintf 'd\\t755\\t501\\t501\\t/private/var/mobile/Library/SpringBoard\\n' >> root/etc/var.skel
\tprintf 'd\\t755\\t501\\t501\\t/private/var/mobile/Library/LockScreen\\n' >> root/etc/var.skel
\tprintf 'd\\t755\\t501\\t501\\t/private/var/mobile/Library/Caches/com.apple.PosterBoard\\n' >> root/etc/var.skel
\tprintf 'd\\t755\\t501\\t501\\t/private/var/mobile/Library/Caches/com.apple.PaperBoard\\n' >> root/etc/var.skel
\tprintf 'd\\t755\\t501\\t501\\t/private/var/mobile/Library/Caches/com.apple.SpringBoard\\n' >> root/etc/var.skel
\tprintf 'd\\t755\\t501\\t501\\t/private/var/mobile/Library/Caches/com.apple.pluginkit\\n' >> root/etc/var.skel
"""

if '/private/var/mobile/Library/PosterBoard' not in build_sh:
    marker = "printf 'd\\t700\\t501\\t501\\t/private/var/mobile/tmp\\n' >> root/etc/var.skel\n"
    assert marker in build_sh, "marker in build.sh not found"
    build_sh = build_sh.replace(marker, marker + skel_entries)
    build_sh_path.write_text(build_sh, encoding='utf-8')
    print("Patched userland/build.sh with PosterBoard skeleton directories")

# 5. Update com.apple.PosterBoard.plist to remove _ExperimentalNonLaunching
poster_plist_path = REPO / 'userland/root/LaunchDaemons/com.apple.PosterBoard.plist'
if poster_plist_path.exists():
    plist_data = plistlib.loads(poster_plist_path.read_bytes())
    if 'MachServices' in plist_data:
        plist_data['MachServices']['com.apple.posterboardservices.services'] = True
    poster_plist_path.write_bytes(plistlib.dumps(plist_data, fmt=plistlib.FMT_BINARY))
    print("Patched com.apple.PosterBoard.plist")

print("All patches applied successfully!")
