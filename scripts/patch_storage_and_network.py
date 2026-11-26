"""Patch kernel APFS/RAMFS for 40GB storage and configure Safari/DNS networking."""
import pathlib

# 1. Patch APFS vfsops
apfs_files = [
    pathlib.Path('/opt/a51-hakios/upstream-a51/hakios/xnu/files/bsd/miscfs/apfs/apfs_vfsops.c'),
    pathlib.Path('/opt/a51-hakios/upstream-a51/hakios/xnu-src/xnu-8796.121.2/bsd/miscfs/apfs/apfs_vfsops.c')
]

old_apfs = """\tsp = vfs_statfs(mp);
\tsp->f_bsize = am->am_nx.block_size;
\tsp->f_iosize = am->am_nx.block_size;
\tsp->f_blocks = am->am_nx.block_count;
\tsp->f_bfree = 0;
\tsp->f_bavail = 0;
\tsp->f_bused = am->am_vol.alloc_count;
\tsp->f_files = am->am_vol.num_files + am->am_vol.num_dirs;
\tsp->f_ffree = 0;"""

new_apfs = """\tsp = vfs_statfs(mp);
\tsp->f_bsize = am->am_nx.block_size ? am->am_nx.block_size : 4096;
\tsp->f_iosize = sp->f_bsize;
\t/* Provide 40 GB storage capacity with 32 GB available to prevent 'iPhone Storage Full' */
\tuint64_t target_blocks = (40ULL * 1024 * 1024 * 1024) / sp->f_bsize;
\tsp->f_blocks = (am->am_nx.block_count > target_blocks) ? am->am_nx.block_count : target_blocks;
\tuint64_t avail_blocks = (32ULL * 1024 * 1024 * 1024) / sp->f_bsize;
\tsp->f_bfree = avail_blocks;
\tsp->f_bavail = avail_blocks;
\tsp->f_bused = (sp->f_blocks > avail_blocks) ? (sp->f_blocks - avail_blocks) : am->am_vol.alloc_count;
\tsp->f_files = am->am_vol.num_files + am->am_vol.num_dirs + 2000000;
\tsp->f_ffree = 1000000;"""

for f in apfs_files:
    if f.exists():
        txt = f.read_text(encoding='utf-8')
        if old_apfs in txt:
            f.write_text(txt.replace(old_apfs, new_apfs, 1), encoding='utf-8')
            print(f"Patched APFS statfs in: {f}")
        elif "target_blocks = (40ULL * 1024 * 1024 * 1024)" in txt:
            print(f"Already patched in: {f}")
        else:
            print(f"Pattern not found in: {f}")

# 2. Patch RAMFS for /private/var
ramfs_files = [
    pathlib.Path('/opt/a51-hakios/upstream-a51/hakios/xnu/files/bsd/miscfs/ramfs/ramfs.c'),
    pathlib.Path('/opt/a51-hakios/upstream-a51/hakios/xnu-src/xnu-8796.121.2/bsd/miscfs/ramfs/ramfs.c')
]

old_ramfs = """\tsp = vfs_statfs(mp);
\tsp->f_bsize = PAGE_SIZE;
\tsp->f_iosize = PAGE_SIZE;
\tsp->f_blocks = rm->rm_max_pages;
\tsp->f_bfree = sp->f_bavail = rm->rm_max_pages;
\tsp->f_bused = 0;"""

new_ramfs = """\tsp = vfs_statfs(mp);
\tsp->f_bsize = PAGE_SIZE;
\tsp->f_iosize = PAGE_SIZE;
\t/* Report 40 GB total with 32 GB free for /private/var ramfs */
\tsp->f_blocks = (40ULL * 1024 * 1024 * 1024) / PAGE_SIZE;
\tsp->f_bfree = sp->f_bavail = (32ULL * 1024 * 1024 * 1024) / PAGE_SIZE;
\tsp->f_bused = sp->f_blocks - sp->f_bfree;"""

for f in ramfs_files:
    if f.exists():
        txt = f.read_text(encoding='utf-8')
        if old_ramfs in txt:
            f.write_text(txt.replace(old_ramfs, new_ramfs, 1), encoding='utf-8')
            print(f"Patched RAMFS statfs in: {f}")
        elif "(40ULL * 1024 * 1024 * 1024) / PAGE_SIZE" in txt:
            print(f"Already patched in: {f}")
        else:
            print(f"Pattern not found in: {f}")

# 3. Patch userland/build.sh for Safari / DNS / resolv.conf fallback
build_sh = pathlib.Path('/opt/a51-hakios/upstream-a51/hakios/userland/build.sh')
if build_sh.exists():
    txt = build_sh.read_text(encoding='utf-8')
    # Ensure /private/var/run/resolv.conf and /etc/resolv.conf exist with fast public DNS fallbacks
    target_needle = 'echo "nameserver 127.0.0.1" > root/etc/resolv.conf'
    dns_block = 'printf "nameserver 1.1.1.1\\nnameserver 8.8.8.8\\nnameserver 1.0.0.1\\n" > root/etc/resolv.conf\n'
    if 'root/etc/resolv.conf' not in txt:
        # Append before building root.apfs
        insert_marker = 'mkapfs.py root.apfs'
        if insert_marker in txt:
            txt = txt.replace(insert_marker, dns_block + insert_marker, 1)
            build_sh.write_text(txt, encoding='utf-8')
            print("Added DNS fallback to userland/build.sh")

print("Storage and network patch execution finished.")
