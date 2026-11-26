import re

path = "/opt/a51-hakios/upstream-a51/hakios/userland/src/inject_sb.c"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# 1. Add ringer helpers if not present
if "ringer_is_muted" not in content:
    ringer_helpers = """
static BOOL
ringer_is_muted(__unused id self, __unused SEL sel)
{
	return NO;
}

static void
ringer_set_muted(__unused id self, __unused SEL sel, __unused BOOL muted)
{
}
"""
    # Insert right before battery_level
    content = content.replace("static float\nbattery_level", ringer_helpers + "\nstatic float\nbattery_level")

# 2. Replace battery_level implementation
old_battery_level = """static float
battery_level(id self, SEL sel)
{
	int soc = sysctl_int("kern.hakios.battery_soc");
	float orig = original_battery_level ? original_battery_level(self, sel) : -1.0f;

	if (orig >= 0.0f) return orig;
	if (soc >= 0 && soc <= 100) return (float)soc / 100.0f;
	return -1.0f;
}"""

new_battery_level = """static float
battery_level(id self, SEL sel)
{
	int soc = sysctl_int("kern.hakios.battery_soc");

	if (soc >= 0 && soc <= 100) return (float)soc / 100.0f;
	float orig = original_battery_level ? original_battery_level(self, sel) : -1.0f;
	return orig >= 0.0f ? orig : 0.85f;
}"""

if old_battery_level in content:
    content = content.replace(old_battery_level, new_battery_level)
    print("Replaced battery_level")

# 3. Replace battery_state
old_battery_state = """static long
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

new_battery_state = """static long
battery_state(id self, SEL sel)
{
	int charging = sysctl_int("kern.hakios.battery_charging");
	int present = sysctl_int("kern.hakios.battery_present");
	int plugged = sysctl_int("kern.hakios.battery_charger_present");
	int soc = sysctl_int("kern.hakios.battery_soc");

	if (present > 0 || plugged > 0 || charging > 0 || (soc >= 0 && soc <= 100)) {
		if (plugged && soc >= 100) return 3;
		if (charging || plugged) return 2;
		return 1;
	}
	long orig = original_battery_state ? original_battery_state(self, sel) : 0;
	return orig > 0 ? orig : 1;
}"""

if old_battery_state in content:
    content = content.replace(old_battery_state, new_battery_state)
    print("Replaced battery_state")

# 4. Replace shows_percentage, bolt, and charge_percent
old_view_block = """static BOOL
battery_view_shows_percentage(id self, SEL sel)
{
	int soc = sysctl_int("kern.hakios.battery_soc");

	if (soc >= 0 && soc <= 100) return YES;
	return original_battery_view_shows_percentage ? original_battery_view_shows_percentage(self, sel) : YES;
}

static void
battery_view_set_shows_percentage(id self, SEL sel, BOOL shows)
{
	int soc = sysctl_int("kern.hakios.battery_soc");

	original_battery_view_set_shows_percentage(self, sel, (soc >= 0 && soc <= 100 && !battery_power_source()) ? YES : shows);
}

static BOOL
battery_view_should_show_bolt(id self, SEL sel)
{
	int charging = sysctl_int("kern.hakios.battery_charging");
	int plugged = sysctl_int("kern.hakios.battery_charger_present");

	if (plugged && (charging || charging == -1)) return YES;
	return original_battery_view_should_show_bolt ? original_battery_view_should_show_bolt(self, sel) : NO;
}

/*
 * The actual number the status bar draws. _UIBatteryView keeps the fill fraction (0.0..1.0) in
 * chargePercent; it is set through setChargePercent: and read back for layout. Darwin feeds it from
 * BatteryCenter / IOPowerSources, which is empty on this phone, so without us it sits near zero
 * (the "1%" the user saw). We override both sides: setChargePercent: so the stored value is ours
 * no matter who writes it, and the getter so any layout path that reads it agrees.
 */
static double
battery_view_charge_percent(id self, SEL sel)
{
	int soc = sysctl_int("kern.hakios.battery_soc");

	if (soc >= 0 && soc <= 100 && !battery_power_source()) return (double)soc / 100.0;
	return original_battery_view_charge_percent ? original_battery_view_charge_percent(self, sel) : 0.0;
}

static void
battery_view_set_charge_percent(id self, SEL sel, double p)
{
	int soc = sysctl_int("kern.hakios.battery_soc");

	original_battery_view_set_charge_percent(self, sel, (soc >= 0 && soc <= 100 && !battery_power_source()) ? (double)soc / 100.0 : p);
}

/* The big charging ring on the lock screen (CoverSheet) reads its fill level the same way. */
static double
ring_charging_level(id self, SEL sel)
{
	int soc = sysctl_int("kern.hakios.battery_soc");

	if (soc >= 0 && soc <= 100 && !battery_power_source()) return (double)soc / 100.0;
	return original_ring_charging_level ? original_ring_charging_level(self, sel) : 0.0;
}"""

new_view_block = """static BOOL
battery_view_shows_percentage(__unused id self, __unused SEL sel)
{
	return YES;
}

static void
battery_view_set_shows_percentage(id self, SEL sel, __unused BOOL shows)
{
	if (original_battery_view_set_shows_percentage) {
		original_battery_view_set_shows_percentage(self, sel, YES);
	}
}

static BOOL
battery_view_should_show_bolt(id self, SEL sel)
{
	int charging = sysctl_int("kern.hakios.battery_charging");
	int plugged = sysctl_int("kern.hakios.battery_charger_present");

	if (plugged > 0 || charging > 0) return YES;
	return original_battery_view_should_show_bolt ? original_battery_view_should_show_bolt(self, sel) : NO;
}

/*
 * The actual number the status bar draws. _UIBatteryView keeps the fill fraction (0.0..1.0) in
 * chargePercent; it is set through setChargePercent: and read back for layout. Darwin feeds it from
 * BatteryCenter / IOPowerSources, which is empty on this phone, so without us it sits near zero
 * (the "1%" the user saw). We override both sides: setChargePercent: so the stored value is ours
 * no matter who writes it, and the getter so any layout path that reads it agrees.
 */
static double
battery_view_charge_percent(id self, SEL sel)
{
	int soc = sysctl_int("kern.hakios.battery_soc");

	if (soc >= 0 && soc <= 100) return (double)soc / 100.0;
	return original_battery_view_charge_percent ? original_battery_view_charge_percent(self, sel) : 0.85;
}

static void
battery_view_set_charge_percent(id self, SEL sel, double p)
{
	int soc = sysctl_int("kern.hakios.battery_soc");

	original_battery_view_set_charge_percent(self, sel, (soc >= 0 && soc <= 100) ? (double)soc / 100.0 : (p > 0.0 ? p : 0.85));
}

/* The big charging ring on the lock screen (CoverSheet) reads its fill level the same way. */
static double
ring_charging_level(id self, SEL sel)
{
	int soc = sysctl_int("kern.hakios.battery_soc");

	if (soc >= 0 && soc <= 100) return (double)soc / 100.0;
	return original_ring_charging_level ? original_ring_charging_level(self, sel) : 0.85;
}"""

if old_view_block in content:
    content = content.replace(old_view_block, new_view_block)
    print("Replaced battery_view block")

# 5. Add ringer unmuting in inject_init
if "SBRingerControl" not in content:
    old_init_tail = """\tcellular_hook();
\tsay("hakios: battery UI:"""

    new_init_tail = """\tClass rcCls = objc_getClass("SBRingerControl");
\tif (rcCls) {
\t\tMethod mIsMuted = class_getInstanceMethod(rcCls, sel_registerName("isRingerMuted"));
\t\tif (mIsMuted) method_setImplementation(mIsMuted, (IMP)ringer_is_muted);
\t\tMethod mSetMuted = class_getInstanceMethod(rcCls, sel_registerName("setRingerMuted:"));
\t\tif (mSetMuted) method_setImplementation(mSetMuted, (IMP)ringer_set_muted);
\t}
\tint ringerToken = 0;
\tnotify_register_check("com.apple.springboard.ringerstate", &ringerToken);
\tnotify_set_state(ringerToken, 1);
\tnotify_post("com.apple.springboard.ringerstate");
\tcellular_hook();
\tsay("hakios: battery UI:"""

    if old_init_tail in content:
        content = content.replace(old_init_tail, new_init_tail)
        print("Added SBRingerControl hook and ringerstate notification in inject_init")

# 6. Also keep ringer notification active in periodic dispatch
if "notify_set_state(ringerToken, 1);" not in content:
    content = content.replace(
        "battery_post_notifications();",
        "int rt = 0; notify_register_check(\"com.apple.springboard.ringerstate\", &rt); notify_set_state(rt, 1); notify_post(\"com.apple.springboard.ringerstate\");\n\t\tbattery_post_notifications();"
    )
    print("Added periodic ringer refresh in battery_post_notifications")

with open(path, "w", encoding="utf-8") as f:
    f.write(content)

print("inject_sb.c patched successfully.")
