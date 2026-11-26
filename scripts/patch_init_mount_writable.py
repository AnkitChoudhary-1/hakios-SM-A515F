import pathlib

init_path = pathlib.Path('/opt/a51-hakios/upstream-a51/hakios/userland/src/init.c')
content = init_path.read_text(encoding='utf-8')

# Revert previous incorrect patch if present
old_patch = """\t/* Mount staged applications from /dev/ufs_prism into /Applications */
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
\t}"""
if old_patch in content:
    content = content.replace(old_patch, "")
    print("Reverted preboot patch")

# Place at the end of mount_writable()
target = """\t\tprintf("  /var/jb from %s, in %s: %d directories, %d files and links%s\\n", jb, to, dirs, entries,
\t\t    users ? ", users resolvable" : "");
\t\tcheck(grafted, "graft the package manager's prefix onto the data volume");
\t}
}"""

addition = """\t\tprintf("  /var/jb from %s, in %s: %d directories, %d files and links%s\\n", jb, to, dirs, entries,
\t\t    users ? ", users resolvable" : "");
\t\tcheck(grafted, "graft the package manager's prefix onto the data volume");
\t}

\t/* Mount staged user apps from /dev/ufs_prism onto /Applications */
\tmkdir("/private/var/apps", 0755);
\tif (mount("apfs", "/private/var/apps", MNT_RDONLY, (void *)"/dev/ufs_prism") == 0) {
\t\tprintf("  staged user applications found on /dev/ufs_prism\\n");
\t\tint afd = open("/private/var/apps", O_RDONLY | O_DIRECTORY, 0);
\t\tstatic char abuf[4096];
\t\toff_t apos = 0;
\t\tssize_t an;
\t\twhile (afd >= 0 && (an = getdirentries(afd, abuf, sizeof(abuf), &apos)) > 0) {
\t\t\tfor (char *p = abuf; p < abuf + an;) {
\t\t\t\tstruct dirent *de = (struct dirent *)(void *)p;
\t\t\t\tsize_t len = de->d_namlen;
\t\t\t\tif (de->d_reclen == 0) break;
\t\t\t\tp += de->d_reclen;
\t\t\t\tif (len < 5 || len >= 240 || strncmp(de->d_name + len - 4, ".app", 4) != 0) continue;
\t\t\t\tchar appname[256], app_to[300], app_from[300];
\t\t\t\tmemcpy(appname, de->d_name, len);
\t\t\t\tappname[len] = 0;
\t\t\t\tstrcpy(app_to, join("/Applications/", appname, ""));
\t\t\t\tstrcpy(app_from, join("/private/var/apps/", appname, ""));
\t\t\t\tif (synthetic_dir(app_to) && bind_dir(app_from, app_to)) {
\t\t\t\t\tprintf("  mounted application into /Applications: %s\\n", appname);
\t\t\t\t}
\t\t\t}
\t\t}
\t\tif (afd >= 0) close(afd);
\t} else {
\t\tprintf("  mount /dev/ufs_prism on /private/var/apps failed: %s\\n", strerror(errno));
\t}
}"""

if target in content:
    init_path.write_text(content.replace(target, addition), encoding='utf-8')
    print("Successfully patched mount_writable in init.c")
else:
    raise RuntimeError("Target string not found in init.c")
