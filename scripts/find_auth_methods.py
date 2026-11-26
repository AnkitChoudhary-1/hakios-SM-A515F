import re

paths = [
    "/opt/a51-hakios/apps/Payload/Instagram.app/Instagram",
    "/opt/a51-hakios/apps/Payload/Instagram.app/Frameworks/FBSharedFramework.framework/FBSharedFramework"
]

for path in paths:
    with open(path, "rb") as f:
        data = f.read()
    print("===", path)
    auths = set(re.findall(rb"request[A-Za-z0-9_]*[aA]uthorization[A-Za-z0-9_:]*", data))
    for m in sorted(auths):
        print("Auth:", m.decode("latin1"))
    accs = set(re.findall(rb"request[A-Za-z0-9_]*[aA]ccess[A-Za-z0-9_:]*", data))
    for m in sorted(accs):
        print("Access:", m.decode("latin1"))
