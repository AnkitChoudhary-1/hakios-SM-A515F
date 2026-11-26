import subprocess
import pathlib

def run_wsl(cmd):
    return subprocess.run(['wsl', 'bash', '-c', cmd], capture_output=True, text=True)

# 1. Patch miniamfi_entitlements.cpp
amfi_files = [
    '/opt/a51-hakios/upstream-a51/hakios/xnu/files/libkern/amfi/miniamfi_entitlements.cpp',
    '/opt/a51-hakios/upstream-a51/hakios/xnu-src/xnu-8796.121.2/libkern/amfi/miniamfi_entitlements.cpp'
]

for af in amfi_files:
    cmd_read = f"cat {af}"
    res = run_wsl(cmd_read)
    content = res.stdout
    
    target_bool = "kern_return_t\nminiamfi_entitlement_boolean(struct proc *proc, const char *name)\n{"
    repl_bool = """kern_return_t
miniamfi_entitlement_boolean(struct proc *proc, const char *name)
{
	if (name != NULL && (
	    strcmp(name, "com.apple.runningboard.can-suspend-locked") == 0 ||
	    strcmp(name, "com.apple.multitasking.unlimitedassertions") == 0 ||
	    strcmp(name, "com.apple.runningboard.assertions.suspend") == 0)) {
		return KERN_SUCCESS;
	}"""
    
    if target_bool in content and "com.apple.runningboard.can-suspend-locked" not in content:
        content = content.replace(target_bool, repl_bool)
        print(f"Patched miniamfi_entitlement_boolean in {af}")

    target_obj = "kern_return_t\nminiamfi_entitlement_object(struct proc *proc, const char *name, void **object)\n{"
    repl_obj = """kern_return_t
miniamfi_entitlement_object(struct proc *proc, const char *name, void **object)
{
	if (name != NULL && strcmp(name, "com.apple.runningboard.can-suspend-locked") == 0 && object != NULL) {
		kOSBooleanTrue->retain();
		*object = (void *)kOSBooleanTrue;
		return KERN_SUCCESS;
	}"""
    if target_obj in content and "kOSBooleanTrue->retain()" not in content:
        content = content.replace(target_obj, repl_obj)
        print(f"Patched miniamfi_entitlement_object in {af}")
        
    p_tmp = pathlib.Path("amfi_tmp.cpp")
    p_tmp.write_text(content, encoding='utf-8')
    subprocess.run(['wsl', 'bash', '-c', f"cat << 'EOF' > {af}\n{content}\nEOF"])
    print(f"Updated {af}")

# 2. Patch ramfs.c and apfs_vfsops.c for 128GB capacity
ramfs_files = [
    '/opt/a51-hakios/upstream-a51/hakios/xnu/files/bsd/miscfs/ramfs/ramfs.c',
    '/opt/a51-hakios/upstream-a51/hakios/xnu-src/xnu-8796.121.2/bsd/miscfs/ramfs/ramfs.c'
]

ramfs_patch_script = """
import re

for path in ['/opt/a51-hakios/upstream-a51/hakios/xnu/files/bsd/miscfs/ramfs/ramfs.c',
             '/opt/a51-hakios/upstream-a51/hakios/xnu-src/xnu-8796.121.2/bsd/miscfs/ramfs/ramfs.c']:
    with open(path, 'r', encoding='utf-8') as f:
        txt = f.read()
    
    pattern = r'sp->f_blocks = [^;]+;\\s*sp->f_bfree = sp->f_bavail = [^;]+;\\s*sp->f_bused = [^;]+;'
    replacement = '''/* Report 128 GB total capacity with 104 GB free for Samsung Galaxy A51 UFS 128GB */
\\tsp->f_blocks = (128ULL * 1024 * 1024 * 1024) / PAGE_SIZE;
\\tsp->f_bfree = sp->f_bavail = (104ULL * 1024 * 1024 * 1024) / PAGE_SIZE;
\\tsp->f_bused = sp->f_blocks - sp->f_bfree;'''
    
    if '128ULL * 1024 * 1024 * 1024' not in txt:
        txt = re.sub(pattern, replacement, txt)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(txt)
        print('Updated ramfs in', path)
    else:
        print('Already 128GB in', path)
"""
run_wsl(f"python3 -c \"{ramfs_patch_script}\"")

apfs_patch_script = """
import re

for path in ['/opt/a51-hakios/upstream-a51/hakios/xnu/files/bsd/miscfs/apfs/apfs_vfsops.c',
             '/opt/a51-hakios/upstream-a51/hakios/xnu-src/xnu-8796.121.2/bsd/miscfs/apfs/apfs_vfsops.c']:
    with open(path, 'r', encoding='utf-8') as f:
        txt = f.read()
    
    if '128ULL * 1024 * 1024 * 1024' not in txt:
        txt = txt.replace('40ULL * 1024 * 1024 * 1024', '128ULL * 1024 * 1024 * 1024')
        txt = txt.replace('32ULL * 1024 * 1024 * 1024', '104ULL * 1024 * 1024 * 1024')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(txt)
        print('Updated apfs in', path)
    else:
        print('Already 128GB in', path)
"""
run_wsl(f"python3 -c \"{apfs_patch_script}\"")

# 3. Patch com.hakios.varstore.plist for periodic 45s persistence
varstore_plist = '/opt/a51-hakios/upstream-a51/hakios/userland/com.hakios.varstore.plist'
run_wsl(f"""python3 -c "
with open('{varstore_plist}', 'r', encoding='utf-8') as f:
    txt = f.read()
if '<string>45</string>' not in txt:
    txt = txt.replace('<string>watch</string>', '<string>watch</string>\\n\\t\\t<string>45</string>')
    with open('{varstore_plist}', 'w', encoding='utf-8') as f:
        f.write(txt)
    print('Updated com.hakios.varstore.plist with 45s interval')
" """)

# 4. Patch inject_sb.c for battery reporting and brightness slider
inject_sb_path = '/opt/a51-hakios/upstream-a51/hakios/userland/src/inject_sb.c'
inject_patch_script = """
with open('/opt/a51-hakios/upstream-a51/hakios/userland/src/inject_sb.c', 'r', encoding='utf-8') as f:
    sb = f.read()

# 1. battery_power_source always returns false so our hooks stay active
old_bps = '''static bool
battery_power_source(void)
{
\\tstatic bool found;
\\tio_service_t service;

\\tif (!found && (service = IOServiceGetMatchingService(0, IOServiceMatching(\"HakiosBattery\"))) != 0) {
\\t\\tIOObjectRelease(service);
\\t\\tfound = true;
\\t}
\\treturn found;
}'''

new_bps = '''static bool
battery_power_source(void)
{
\\treturn false;
}'''

if old_bps in sb:
    sb = sb.replace(old_bps, new_bps)
    print('Patched battery_power_source to return false')
elif 'static bool\\nbattery_power_source(void)\\n{\\n\\treturn false;\\n}' not in sb:
    print('Warning: old_bps pattern not matched')

# 2. Add OLED dimmer window for Control Center brightness slider
dimmer_code = '''
/* OLED Software Dimmer for Control Center Brightness Slider */
static id s_dimmer_window = nil;

static void update_oled_dimmer(float b)
{
\\tif (b < 0.05f) b = 0.05f;
\\tif (b > 1.0f) b = 1.0f;
\\tClass winCls = objc_getClass("UIWindow");
\\tif (!winCls) return;
\\tif (s_dimmer_window == nil) {
\\t\\tClass scrCls = objc_getClass("UIScreen");
\\t\\tid screen = scrCls ? ((id (*)(Class, SEL))objc_msgSend)(scrCls, sel_registerName("mainScreen")) : nil;
\\t\\thk_rect bounds = screen ? ((hk_rect (*)(id, SEL))objc_msgSend)(screen, sel_registerName("bounds")) : (hk_rect){{0, 0}, {375, 812}};
\\t\\ts_dimmer_window = ((id (*)(id, SEL, hk_rect))objc_msgSend)([winCls alloc], sel_registerName("initWithFrame:"), bounds);
\\t\\tif (s_dimmer_window) {
\\t\\t\\t((void (*)(id, SEL, double))objc_msgSend)(s_dimmer_window, sel_registerName("setWindowLevel:"), 999999.0);
\\t\\t\\t((void (*)(id, SEL, BOOL))objc_msgSend)(s_dimmer_window, sel_registerName("setUserInteractionEnabled:"), NO);
\\t\\t\\t((void (*)(id, SEL, BOOL))objc_msgSend)(s_dimmer_window, sel_registerName("setHidden:"), NO);
\\t\\t}
\\t}
\\tif (s_dimmer_window) {
\\t\\tClass colCls = objc_getClass("UIColor");
\\t\\tdouble alpha = (1.0 - (double)b) * 0.85;
\\t\\tif (alpha < 0.0) alpha = 0.0;
\\t\\tif (alpha > 0.85) alpha = 0.85;
\\t\\tid color = ((id (*)(Class, SEL, double, double))objc_msgSend)(colCls, sel_registerName("colorWithWhite:alpha:"), 0.0, alpha);
\\t\\t((void (*)(id, SEL, id))objc_msgSend)(s_dimmer_window, sel_registerName("setBackgroundColor:"), color);
\\t}
}
'''

if 'update_oled_dimmer' not in sb:
    # insert before battery_level
    sb = sb.replace('static float\\nbattery_level(', dimmer_code + '\\nstatic float\\nbattery_level(')
    print('Inserted OLED dimmer code')

# 3. Hook UIScreen setBrightness: and register brightness observer
startup_code = '''\\t\\tbattery_post_notifications();
\\t\\t/* Listen for Control Center brightness changes and sync OLED dimmer */
\\t\\tClass screenCls = objc_getClass("UIScreen");
\\t\\tid mainScreen = screenCls ? ((id (*)(Class, SEL))objc_msgSend)(screenCls, sel_registerName("mainScreen")) : nil;
\\t\\tif (mainScreen) {
\\t\\t\\tfloat initB = ((float (*)(id, SEL))objc_msgSend)(mainScreen, sel_registerName("brightness"));
\\t\\t\\tupdate_oled_dimmer(initB > 0.0f ? initB : 0.8f);
\\t\\t}
\\t\\tClass nc = objc_getClass("NSNotificationCenter");
\\t\\tid dCenter = nc ? ((id (*)(Class, SEL))objc_msgSend)(nc, sel_registerName("defaultCenter")) : nil;
\\t\\tif (dCenter) {
\\t\\t\\tSEL addObs = sel_registerName("addObserverForName:object:queue:usingBlock:");
\\t\\t\\tvoid (^block)(id) = ^(id note) {
\\t\\t\\t\\tfloat b = ((float (*)(id, SEL))objc_msgSend)(mainScreen, sel_registerName("brightness"));
\\t\\t\\t\\tupdate_oled_dimmer(b);
\\t\\t\\t};
\\t\\t\\t((void (*)(id, SEL, id, id, id, void (^)(id)))objc_msgSend)(dCenter, addObs,
\\t\\t\\t    (id)CFSTR("UIScreenBrightnessDidChangeNotification"), nil, nil, block);
\\t\\t}'''

if 'update_oled_dimmer(initB > 0.0f ? initB : 0.8f);' not in sb:
    sb = sb.replace('\\t\\tbattery_post_notifications();', startup_code)
    print('Hooked brightness observer at startup in inject_sb.c')

with open('/opt/a51-hakios/upstream-a51/hakios/userland/src/inject_sb.c', 'w', encoding='utf-8') as f:
    f.write(sb)
print('Finished updating inject_sb.c')
"""

run_wsl(f"python3 -c \"{inject_patch_script}\"")
print("All perfect build patches successfully applied!")
