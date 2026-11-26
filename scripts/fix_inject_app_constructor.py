import pathlib

p = pathlib.Path('/opt/a51-hakios/upstream-a51/hakios/userland/src/inject_app.c')
if not p.exists():
    p = pathlib.Path(r'\\wsl$\A51-KernelBuilder\opt\a51-hakios\upstream-a51\hakios\userland\src\inject_app.c')

text = p.read_text(encoding='utf-8')

# 1. Add #include <dlfcn.h> if missing
if '#include <dlfcn.h>' not in text:
    text = text.replace('#include <unistd.h>', '#include <unistd.h>\n#include <dlfcn.h>')

# 2. Remove extern void NSSetUncaughtExceptionHandler
text = text.replace('extern void NSSetUncaughtExceptionHandler(NSUncaughtExceptionHandler *);\n', '')

# 3. Replace direct call with dlsym lookup
target_call = 'NSSetUncaughtExceptionHandler((NSUncaughtExceptionHandler *)hakios_uncaught_exception);'
safe_call = '''void (*set_handler)(NSUncaughtExceptionHandler *) = (void (*)(NSUncaughtExceptionHandler *))dlsym(RTLD_DEFAULT, "NSSetUncaughtExceptionHandler");
\tif (set_handler) {
\t\tset_handler(hakios_uncaught_exception);
\t}'''

if target_call in text:
    text = text.replace(target_call, safe_call)

p.write_text(text, encoding='utf-8')
print("Updated inject_app.c with dynamic dlsym for NSSetUncaughtExceptionHandler!")
