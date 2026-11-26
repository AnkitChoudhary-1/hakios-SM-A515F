import pathlib

init_path = pathlib.Path('/opt/a51-hakios/upstream-a51/hakios/userland/src/init.c')
content = init_path.read_text(encoding='utf-8')

target = """\tmount_cryptex("App", ",c=2", devpath);
\tcheck(bind_dir("/private/preboot/redwood", "/redwood"), "this image back on /redwood");
\tflash_root_mode = 1;"""

addition = """\tmount_cryptex("App", ",c=2", devpath);
\tcheck(bind_dir("/private/preboot/redwood", "/redwood"), "this image back on /redwood");

\t/* Mount staged applications from /dev/ufs_prism into /Applications */
\tmkdir("/private/preboot/apps", 0755);
\tif (mount("apfs", "/private/preboot/apps", MNT_RDONLY, (void *)"/dev/ufs_prism") == 0) {
\t\tprintf("  staged apps container mounted on /private/preboot/apps\\n");
\t\tint afd = open("/private/preboot/apps", O_RDONLY | O_DIRECTORY, 0);
\t\toff_t apos = 0;
\t\twhile (afd >= 0 && (n = getdirentries(afd, buf, sizeof(buf), &apos)) > 0) {
\t\t\tfor (char *p = buf; p < buf + n;) {
\t\t\t\tstruct dirent *de = (struct dirent *)(void *)p;
\t\t\t\tsize_t len = de->d_namlen;
\t\t\t\tif (de->d_reclen == 0) break;
\t\t\t\tp += de->d_reclen;
\t\t\t\tif (len < 5 || len >= sizeof(name) || strncmp(de->d_name + len - 4, ".app", 4) != 0) continue;
\t\t\t\tmemcpy(name, de->d_name, len);
\t\t\t\tname[len] = 0;
\t\t\t\tstrcpy(to, join("/Applications/", name, ""));
\t\t\t\tstrcpy(from, join("/private/preboot/apps/", name, ""));
\t\t\t\tif (synthetic_dir(to) && bind_dir(from, to)) {
\t\t\t\t\tprintf("  mounted application into /Applications: %s\\n", name);
\t\t\t\t}
\t\t\t}
\t\t}
\t\tif (afd >= 0) close(afd);
\t}

\tflash_root_mode = 1;"""

if target in content:
    init_path.write_text(content.replace(target, addition), encoding='utf-8')
    print("Successfully patched init.c to mount apps from /dev/ufs_prism")
elif "staged apps container mounted" in content:
    print("init.c already patched")
else:
    raise RuntimeError("Target string not found in init.c")
