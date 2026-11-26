"""Update hakios.ufs.c, ramfs.c, and var_store.c for A51 perfect build."""
import pathlib

# 1. Update UFS_DARWIN_MIN in hakios.ufs.c
ufs_files = [
    pathlib.Path("/opt/a51-hakios/upstream-a51/hakios/drivers/storage/hakios.ufs.c"),
    pathlib.Path("/opt/a51-hakios/upstream-a51/hakios/xnu-src/xnu-8796.121.2/bsd/dev/hakios.ufs.c"),
]

for p in ufs_files:
    if p.exists():
        content = p.read_text(encoding="utf-8")
        if "#define UFS_DARWIN_MIN     5242875ULL" in content:
            content = content.replace("#define UFS_DARWIN_MIN     5242875ULL",
                                      "#define UFS_DARWIN_MIN     2048000ULL")
            p.write_text(content, encoding="utf-8")
            print(f"Updated UFS_DARWIN_MIN in {p}")
        else:
            print(f"UFS_DARWIN_MIN already updated or not found in {p}")

# 2. Update var_store.c SLOT_BYTES
var_store_path = pathlib.Path("/opt/a51-hakios/upstream-a51/hakios/userland/src/var_store.c")
if var_store_path.exists():
    content = var_store_path.read_text(encoding="utf-8")
    if "#define SLOT_BYTES      0x80000000LL" in content:
        content = content.replace("#define SLOT_BYTES      0x80000000LL",
                                  "#define SLOT_BYTES      0x3e000000LL")
        var_store_path.write_text(content, encoding="utf-8")
        print(f"Updated SLOT_BYTES in {var_store_path}")
    else:
        print(f"SLOT_BYTES already updated or not found in {var_store_path}")

# 3. Update ramfs_vfs_getattr in ramfs.c
ramfs_files = [
    pathlib.Path("/opt/a51-hakios/upstream-a51/hakios/xnu/files/bsd/miscfs/ramfs/ramfs.c"),
    pathlib.Path("/opt/a51-hakios/upstream-a51/hakios/xnu-src/xnu-8796.121.2/bsd/miscfs/ramfs/ramfs.c"),
]

target_getattr = """\tVFSATTR_RETURN(fsap, f_objcount, nodes);
\tVFSATTR_RETURN(fsap, f_bsize, PAGE_SIZE);
\tVFSATTR_RETURN(fsap, f_iosize, PAGE_SIZE);
\tVFSATTR_RETURN(fsap, f_blocks, rm->rm_max_pages);
\tVFSATTR_RETURN(fsap, f_bfree, rm->rm_max_pages - MIN(used, rm->rm_max_pages));
\tVFSATTR_RETURN(fsap, f_bavail, rm->rm_max_pages - MIN(used, rm->rm_max_pages));
\tVFSATTR_RETURN(fsap, f_bused, used);
\tVFSATTR_RETURN(fsap, f_files, rm->rm_max_pages);
\tVFSATTR_RETURN(fsap, f_ffree, rm->rm_max_pages - MIN(nodes, rm->rm_max_pages));"""

replacement_getattr = """\tuint64_t total_pages = (128ULL * 1024 * 1024 * 1024) / PAGE_SIZE;
\tuint64_t free_pages = ((104ULL * 1024 * 1024 * 1024) / PAGE_SIZE) - MIN(used, (104ULL * 1024 * 1024 * 1024) / PAGE_SIZE);
\tVFSATTR_RETURN(fsap, f_objcount, nodes);
\tVFSATTR_RETURN(fsap, f_bsize, PAGE_SIZE);
\tVFSATTR_RETURN(fsap, f_iosize, PAGE_SIZE);
\tVFSATTR_RETURN(fsap, f_blocks, total_pages);
\tVFSATTR_RETURN(fsap, f_bfree, free_pages);
\tVFSATTR_RETURN(fsap, f_bavail, free_pages);
\tVFSATTR_RETURN(fsap, f_bused, total_pages - free_pages);
\tVFSATTR_RETURN(fsap, f_files, total_pages);
\tVFSATTR_RETURN(fsap, f_ffree, free_pages);"""

for p in ramfs_files:
    if p.exists():
        content = p.read_text(encoding="utf-8")
        if target_getattr in content:
            content = content.replace(target_getattr, replacement_getattr)
            p.write_text(content, encoding="utf-8")
            print(f"Updated ramfs_vfs_getattr in {p}")
        else:
            print(f"getattr pattern not found in {p}")

print("All source updates complete.")
