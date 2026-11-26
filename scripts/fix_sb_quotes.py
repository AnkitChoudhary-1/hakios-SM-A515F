import subprocess

script = """
with open('/opt/a51-hakios/upstream-a51/hakios/userland/src/inject_sb.c', 'r', encoding='utf-8') as f:
    sb = f.read()

replacements = [
    ('objc_getClass(UIWindow)', 'objc_getClass("UIWindow")'),
    ('objc_getClass(UIScreen)', 'objc_getClass("UIScreen")'),
    ('sel_registerName(mainScreen)', 'sel_registerName("mainScreen")'),
    ('sel_registerName(bounds)', 'sel_registerName("bounds")'),
    ('sel_registerName(initWithFrame:)', 'sel_registerName("initWithFrame:")'),
    ('sel_registerName(setWindowLevel:)', 'sel_registerName("setWindowLevel:")'),
    ('sel_registerName(setUserInteractionEnabled:)', 'sel_registerName("setUserInteractionEnabled:")'),
    ('sel_registerName(setHidden:)', 'sel_registerName("setHidden:")'),
    ('objc_getClass(UIColor)', 'objc_getClass("UIColor")'),
    ('sel_registerName(colorWithWhite:alpha:)', 'sel_registerName("colorWithWhite:alpha:")'),
    ('sel_registerName(setBackgroundColor:)', 'sel_registerName("setBackgroundColor:")'),
    ('sel_registerName(brightness)', 'sel_registerName("brightness")'),
    ('objc_getClass(NSNotificationCenter)', 'objc_getClass("NSNotificationCenter")'),
    ('sel_registerName(defaultCenter)', 'sel_registerName("defaultCenter")'),
    ('sel_registerName(addObserverForName:object:queue:usingBlock:)', 'sel_registerName("addObserverForName:object:queue:usingBlock:")'),
    ('(id)CFSTR(UIScreenBrightnessDidChangeNotification)', '(id)CFSTR("UIScreenBrightnessDidChangeNotification")'),
]

for old, new in replacements:
    sb = sb.replace(old, new)

with open('/opt/a51-hakios/upstream-a51/hakios/userland/src/inject_sb.c', 'w', encoding='utf-8') as f:
    f.write(sb)
print('Fixed quotes in inject_sb.c successfully')
"""

subprocess.run(['wsl', 'python3', '-c', script], check=True)
