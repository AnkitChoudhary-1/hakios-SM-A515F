import pathlib

path = pathlib.Path('/opt/a51-hakios/upstream-a51/hakios/userland/build.sh')
txt = path.read_text(encoding='utf-8')
old = '\tcp ${RC_JOBS:-rc.jobs} root/etc/rc.jobs\n'
new = old + '\tprintf "nameserver 1.1.1.1\\nnameserver 8.8.8.8\\nnameserver 1.0.0.1\\n" > root/etc/resolv.conf\n\tprintf "l\\t/etc/resolv.conf\\t/private/var/run/resolv.conf\\n" >> root/etc/var.skel\n'

if old in txt and 'nameserver 1.1.1.1' not in txt:
    path.write_text(txt.replace(old, new, 1), encoding='utf-8')
    print('Updated userland/build.sh with DNS resolver fallback')
else:
    print('Already present or marker not found')
