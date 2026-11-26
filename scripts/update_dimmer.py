import subprocess

script = """
with open('/opt/a51-hakios/upstream-a51/hakios/userland/src/inject_sb.c', 'r', encoding='utf-8') as f:
    sb = f.read()

import re
old_dimmer = r'/\\* OLED Software Dimmer for Control Center Brightness Slider \\*/[\\s\\S]*?}\\n}'
new_dimmer = '''/* OLED Software Dimmer for Control Center Brightness Slider */
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
\\t\\tCGRect bounds = screen ? ((CGRect (*)(id, SEL))objc_msgSend)(screen, sel_registerName("bounds")) : (CGRect){{0, 0}, {375, 812}};
\\t\\tid alloced = ((id (*)(Class, SEL))objc_msgSend)(winCls, sel_registerName("alloc"));
\\t\\ts_dimmer_window = ((id (*)(id, SEL, CGRect))objc_msgSend)(alloced, sel_registerName("initWithFrame:"), bounds);
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
}'''

sb = re.sub(old_dimmer, new_dimmer, sb)

with open('/opt/a51-hakios/upstream-a51/hakios/userland/src/inject_sb.c', 'w', encoding='utf-8') as f:
    f.write(sb)
print('Updated update_oled_dimmer successfully')
"""

subprocess.run(['wsl', 'python3', '-c', script], check=True)
