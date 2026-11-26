import pathlib
import sys

repo_linux = pathlib.Path('/opt/a51-hakios/upstream-a51/hakios')
repo_win = pathlib.Path(r'\\wsl$\A51-KernelBuilder\opt\a51-hakios\upstream-a51\hakios')
repo = repo_linux if repo_linux.exists() else repo_win

print(f"Using repo at {repo}")

# 1. Patch init.c to remove /dev/ufs_prism mount
init_p = repo / 'userland/src/init.c'
init_text = init_p.read_text(encoding='utf-8')

target_mount = """\t/* Mount staged user apps from /dev/ufs_prism onto /private/preboot/apps */
\tmkdir("/private/preboot/apps", 0755);
\tif (mount("apfs", "/private/preboot/apps", MNT_RDONLY, (void *)"/dev/ufs_prism") == 0) {
\t\tprintf("  staged user applications mounted on /private/preboot/apps\\n");
\t} else {
\t\tprintf("  mount /dev/ufs_prism on /private/preboot/apps failed: %s\\n", strerror(errno));
\t}"""

if target_mount in init_text:
    init_text = init_text.replace(target_mount, "\t/* User applications unmounted (Instagram removed) */")
    init_p.write_text(init_text, encoding='utf-8')
    print("[1] Successfully removed /dev/ufs_prism mount from init.c")
else:
    print("[1] Mount target not found or already removed in init.c")

# 2. Patch userland/build.sh to remove Instagram from INJECT
build_p = repo / 'userland/build.sh'
build_text = build_p.read_text(encoding='utf-8')

target_inject = "/redwood/lib/libhakios.app.dylib Sileo Instagram"
replacement_inject = "/redwood/lib/libhakios.app.dylib Sileo"

if target_inject in build_text:
    build_text = build_text.replace(target_inject, replacement_inject)
    build_p.write_text(build_text, encoding='utf-8')
    print("[2] Successfully removed Instagram from INJECT in build.sh")
else:
    print("[2] Target inject not found or already removed in build.sh")
