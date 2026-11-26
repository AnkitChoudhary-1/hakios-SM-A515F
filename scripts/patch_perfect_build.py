import pathlib
import sys

REPO = pathlib.Path('/opt/a51-hakios/upstream-a51/hakios')
if not REPO.exists():
    # If running from Windows without WSL path mapping
    REPO = pathlib.Path(r'\\wsl$\A51-KernelBuilder\opt\a51-hakios\upstream-a51\hakios')

print(f"Using REPO path: {REPO}")

# 1. Patch vfs_syscalls.c in both xnu-src and xnu/files
vfs_files = [
    REPO / 'xnu-src/xnu-8796.121.2/bsd/vfs/vfs_syscalls.c',
    REPO / 'xnu/files/bsd/vfs/vfs_syscalls.c'
]

vfs_target = """\tstrlcpy(&sfs->f_mntonname[0], &vsfs->f_mntonname[0], MAXPATHLEN);
\tstrlcpy(&sfs->f_mntfromname[0], &vsfs->f_mntfromname[0], MAXPATHLEN);
}"""

vfs_replacement = """\tstrlcpy(&sfs->f_mntonname[0], &vsfs->f_mntonname[0], MAXPATHLEN);
\tstrlcpy(&sfs->f_mntfromname[0], &vsfs->f_mntfromname[0], MAXPATHLEN);

\t/* Hakios A51 storage capacity override: report 128 GB total, ~104 GB free for root and /private/var */
\tif (strcmp(sfs->f_mntonname, "/") == 0 || strcmp(sfs->f_mntonname, "/private/var") == 0) {
\t\tuint32_t bsz = sfs->f_bsize ? sfs->f_bsize : 4096;
\t\tsfs->f_blocks = (128ULL * 1024 * 1024 * 1024) / bsz;
\t\tsfs->f_bfree = sfs->f_bavail = (104ULL * 1024 * 1024 * 1024) / bsz;
\t}
}"""

for vf in vfs_files:
    if vf.exists():
        content = vf.read_text(encoding='utf-8')
        if vfs_target in content:
            content = content.replace(vfs_target, vfs_replacement)
            vf.write_text(content, encoding='utf-8')
            print(f"[1] Patched storage capacity 128 GB in {vf.name}")
        elif "Hakios A51 storage capacity override" in content:
            print(f"[1] Already patched in {vf.name}")
        else:
            print(f"[1] Target block not found in {vf.name}")
    else:
        if 'xnu/files' in str(vf):
            vf.parent.mkdir(parents=True, exist_ok=True)
            # Copy patched version to xnu/files
            src = REPO / 'xnu-src/xnu-8796.121.2/bsd/vfs/vfs_syscalls.c'
            if src.exists():
                vf.write_text(src.read_text(encoding='utf-8'), encoding='utf-8')
                print(f"[1] Created {vf}")

# 2. Patch HakiosMetalCA.m: allow Instagram to obtain the HakiosMetal device
metal_file = REPO / 'userland/src/HakiosMetalCA.m'
if metal_file.exists():
    metal_text = metal_file.read_text(encoding='utf-8')
    m_target = 'if (!all && (name == NULL || strcmp(name, "backboardd") != 0)) {'
    m_replacement = 'if (!all && (name == NULL || (strcmp(name, "backboardd") != 0 && strstr(name, "Instagram") == NULL))) {'
    if m_target in metal_text:
        metal_text = metal_text.replace(m_target, m_replacement)
        metal_file.write_text(metal_text, encoding='utf-8')
        print("[2] Patched HakiosMetalCA.m to permit Instagram Metal device creation")
    elif 'strstr(name, "Instagram")' in metal_text:
        print("[2] HakiosMetalCA.m already permits Instagram")
    else:
        print("[2] Target not found in HakiosMetalCA.m")

# 3. Patch userland/build.sh: inject libhakios.app.dylib into Instagram
build_file = REPO / 'userland/build.sh'
if build_file.exists():
    build_text = build_file.read_text(encoding='utf-8')
    b_target = '/redwood/lib/libhakios.app.dylib Sileo\n'
    b_replacement = '/redwood/lib/libhakios.app.dylib Sileo Instagram\n'
    if b_target in build_text:
        build_text = build_text.replace(b_target, b_replacement)
        build_file.write_text(build_text, encoding='utf-8')
        print("[3] Patched userland/build.sh to inject libhakios.app.dylib into Instagram")
    elif '/redwood/lib/libhakios.app.dylib Sileo Instagram' in build_text:
        print("[3] userland/build.sh already has Instagram in INJECT")
    else:
        print("[3] Target not found in userland/build.sh")

# 4. Patch userland/src/inject_app.c: log uncaught exceptions
app_file = REPO / 'userland/src/inject_app.c'
if app_file.exists():
    app_text = app_file.read_text(encoding='utf-8')
    if 'hakios_uncaught_exception' not in app_text:
        hook_exc = '''
static void
hakios_uncaught_exception(id exception)
{
	id (*desc)(id, SEL) = (id (*)(id, SEL))objc_msgSend;
	const char *(*utf8)(id, SEL) = (const char *(*)(id, SEL))objc_msgSend;
	id name = desc ? desc(exception, sel_registerName("name")) : nil;
	id reason = desc ? desc(exception, sel_registerName("reason")) : nil;
	char line[1024];
	int n = snprintf(line, sizeof(line), "hakios: %s: UNCAUGHT EXCEPTION: %s: %s\\n", who,
		name ? utf8(name, sel_registerName("UTF8String")) : "?",
		reason ? utf8(reason, sel_registerName("UTF8String")) : "?");
	say(line, (size_t)(n > 0 ? n : 0));
}
'''
        app_text = app_text.replace('static void\nhakios_app_init(void)', hook_exc + '\nstatic void\nhakios_app_init(void)')
        app_text = app_text.replace('who = name;', 'who = name;\n\tNSSetUncaughtExceptionHandler((NSUncaughtExceptionHandler *)hakios_uncaught_exception);')
        app_file.write_text(app_text, encoding='utf-8')
        print("[4] Patched inject_app.c with uncaught exception handler")
    else:
        print("[4] inject_app.c already has exception handler")

# 5. Patch userland/src/inject_sb.c: brightness slider hook, real-time battery refresh
sb_file = REPO / 'userland/src/inject_sb.c'
if sb_file.exists():
    sb_text = sb_file.read_text(encoding='utf-8')
    
    # 5a. Add slider & brightness hooks functions
    if 'orig_setBrightness' not in sb_text:
        dimmer_hooks = '''
static void (*orig_setBrightness)(id, SEL, float) = NULL;
static void my_setBrightness(id self, SEL sel, float b)
{
	if (orig_setBrightness) orig_setBrightness(self, sel, b);
	update_oled_dimmer(b);
}

static void (*orig_slider_setValue)(id, SEL, float) = NULL;
static void my_slider_setValue(id self, SEL sel, float val)
{
	if (orig_slider_setValue) orig_slider_setValue(self, sel, val);
	Class scrCls = objc_getClass("UIScreen");
	if (scrCls) {
		id screen = ((id (*)(Class, SEL))objc_msgSend)(scrCls, sel_registerName("mainScreen"));
		if (screen) {
			float b = ((float (*)(id, SEL))objc_msgSend)(screen, sel_registerName("brightness"));
			update_oled_dimmer(b);
		}
	}
}
'''
        sb_text = sb_text.replace('/* OLED Software Dimmer for Control Center Brightness Slider */',
                                  dimmer_hooks + '\n/* OLED Software Dimmer for Control Center Brightness Slider */')
        print("[5a] Added my_setBrightness and my_slider_setValue helpers")

    # 5b. Update cellular_aggregator timer: add _updateBatteryItems & poll brightness
    old_timer = '''		if ((registered != last_registered || bars != last_bars) && cellular_aggregator != nil) {
			SEL update = sel_registerName("_updateSignalStrengthItem");

			last_registered = registered;
			last_bars = bars;
			if (class_getInstanceMethod(object_getClass(cellular_aggregator), update)) {
				((void (*)(id, SEL))objc_msgSend)(cellular_aggregator, update);
				say("hakios: cellular: the signal item asked to update (registered %d, bars %d)\\n", registered, bars);
			}
		}
	});'''
    new_timer = '''		if ((registered != last_registered || bars != last_bars) && cellular_aggregator != nil) {
			SEL update = sel_registerName("_updateSignalStrengthItem");

			last_registered = registered;
			last_bars = bars;
			if (class_getInstanceMethod(object_getClass(cellular_aggregator), update)) {
				((void (*)(id, SEL))objc_msgSend)(cellular_aggregator, update);
				say("hakios: cellular: the signal item asked to update (registered %d, bars %d)\\n", registered, bars);
			}
		}
		if (cellular_aggregator != nil) {
			SEL updateBatt = sel_registerName("_updateBatteryItems");
			if (class_getInstanceMethod(object_getClass(cellular_aggregator), updateBatt)) {
				((void (*)(id, SEL))objc_msgSend)(cellular_aggregator, updateBatt);
			}
		}
		Class scrCls = objc_getClass("UIScreen");
		if (scrCls) {
			id screen = ((id (*)(Class, SEL))objc_msgSend)(scrCls, sel_registerName("mainScreen"));
			if (screen) {
				static float last_b = -1.0f;
				float curB = ((float (*)(id, SEL))objc_msgSend)(screen, sel_registerName("brightness"));
				if (curB != last_b) {
					last_b = curB;
					update_oled_dimmer(curB);
				}
			}
		}
	});'''
    if old_timer in sb_text:
        sb_text = sb_text.replace(old_timer, new_timer)
        print("[5b] Added real-time _updateBatteryItems and brightness polling to aggregator timer")
    elif '_updateBatteryItems' in sb_text:
        print("[5b] Aggregator timer already has _updateBatteryItems")

    # 5c. Remove !battery_power_source() restriction in battery_post_notifications
    p_old = 'if (center != nil && !battery_power_source()) {'
    p_new = 'if (center != nil && device != nil) {'
    if p_old in sb_text:
        sb_text = sb_text.replace(p_old, p_new)
        print("[5c] Enabled unconditional battery notification posting")

    # 5d. Install UIScreen setBrightness: and CCUIContinuousSliderView setValue: hooks
    hook_install_marker = 'Class uidev = objc_getClass("UIDevice");\n\t\tSEL current = sel_registerName("currentDevice");'
    hook_install_code = '''Class scr = objc_getClass("UIScreen");
		if (scr) {
			Method m = class_getInstanceMethod(scr, sel_registerName("setBrightness:"));
			if (m && method_getImplementation(m) != (IMP)my_setBrightness) {
				orig_setBrightness = (void (*)(id, SEL, float))method_getImplementation(m);
				method_setImplementation(m, (IMP)my_setBrightness);
				say("hakios: hooked UIScreen setBrightness:\\n");
			}
		}
		Class sliderCls = objc_getClass("CCUIContinuousSliderView");
		if (sliderCls) {
			Method m = class_getInstanceMethod(sliderCls, sel_registerName("setValue:"));
			if (m && method_getImplementation(m) != (IMP)my_slider_setValue) {
				orig_slider_setValue = (void (*)(id, SEL, float))method_getImplementation(m);
				method_setImplementation(m, (IMP)my_slider_setValue);
				say("hakios: hooked CCUIContinuousSliderView setValue:\\n");
			}
		}
		Class uidev = objc_getClass("UIDevice");
		SEL current = sel_registerName("currentDevice");'''
    if hook_install_marker in sb_text and 'hooked UIScreen setBrightness:' not in sb_text:
        sb_text = sb_text.replace(hook_install_marker, hook_install_code)
        print("[5d] Installed UIScreen setBrightness: and slider hooks")

    sb_file.write_text(sb_text, encoding='utf-8')
    print("[5] Successfully updated inject_sb.c")

print("WSL patch application complete.")
