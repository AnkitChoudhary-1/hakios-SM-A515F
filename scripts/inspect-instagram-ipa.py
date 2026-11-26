"""Inspect IPA metadata and Mach-O headers without executing or changing app files."""
import argparse
import hashlib
import json
import plistlib
import struct
import zipfile
from pathlib import Path


def version(n):
    return f"{n >> 16}.{(n >> 8) & 255}.{n & 255}"


def cstr(data):
    return data.split(b"\0", 1)[0].decode("utf-8", "replace")


def macho(data):
    if data[:4] in (b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf"):
        wide = data[3] == 191
        count = struct.unpack_from(">I", data, 4)[0]
        slices = []
        for i in range(count):
            entry = struct.unpack_from(">IIQQII" if wide else ">IIIII", data,
                                       8 + i * (32 if wide else 20))
            offset, size = entry[2:4]
            slices.extend(macho(data[offset:offset + size]))
        return slices
    if data[:4] != b"\xcf\xfa\xed\xfe":
        raise ValueError("Expected little-endian 64-bit Mach-O")
    _, cpu, sub, kind, count, cmd_bytes, flags, _ = struct.unpack_from("<8I", data)
    result = {"cpu_type": hex(cpu), "cpu_subtype": hex(sub),
              "architecture": {0: "arm64", 1: "arm64v8", 2: "arm64e"}.get(sub & 0xffffff, "other")
              if cpu == 0x100000c else "other", "file_type": kind,
              "flags": hex(flags), "dependencies": [], "rpaths": [],
              "encryption": [], "initializers": [], "initializer_offsets": [],
              "entitlements": None}
    pos = 32
    symbols = {}
    symtab = None
    for _ in range(count):
        cmd, size = struct.unpack_from("<II", data, pos)
        if size < 8 or pos + size > 32 + cmd_bytes or pos + size > len(data):
            raise ValueError("Invalid load-command size")
        command = data[pos:pos + size]
        if cmd in (0xc, 0x80000018, 0x8000001f, 0x20, 0x80000023):
            name, timestamp, current, compat = struct.unpack_from("<4I", command, 8)
            result["dependencies"].append({"path": cstr(command[name:]),
                "kind": {0xc: "strong", 0x80000018: "weak", 0x8000001f: "reexport",
                         0x20: "lazy", 0x80000023: "upward"}[cmd],
                "current_version": version(current), "compatibility_version": version(compat)})
        elif cmd == 0x8000001c:
            result["rpaths"].append(cstr(command[struct.unpack_from("<I", command, 8)[0]:]))
        elif cmd in (0x21, 0x2c):
            offset, length, cryptid = struct.unpack_from("<III", command, 8)
            result["encryption"].append({"cryptid": cryptid, "offset": offset, "size": length})
        elif cmd == 0x32:
            platform, minimum, sdk, _ = struct.unpack_from("<4I", command, 8)
            result["platform"] = platform
            result["minimum_os"] = version(minimum)
            result["sdk"] = version(sdk)
        elif cmd == 0x25:
            minimum, sdk = struct.unpack_from("<II", command, 8)
            result["minimum_os"] = version(minimum)
            result["sdk"] = version(sdk)
        elif cmd == 0x1b:
            result["uuid"] = command[8:24].hex()
        elif cmd == 0x2:
            symtab = struct.unpack_from("<4I", command, 8)
        elif cmd == 0x19:
            nsects = struct.unpack_from("<I", command, 64)[0]
            for j in range(nsects):
                section = struct.unpack_from("<16s16sQQIIIIIIII", command, 72 + j * 80)
                name, segment, addr, length, offset = section[:5]
                if cstr(name) == "__mod_init_func":
                    result["initializers"].extend(hex(x[0]) for x in struct.iter_unpack("<Q", data[offset:offset + length]))
                if cstr(name) == "__init_offsets":
                    result["initializer_offsets"].extend(hex(x[0]) for x in struct.iter_unpack("<I", data[offset:offset + length]))
        elif cmd == 0x1d:
            offset, length = struct.unpack_from("<II", command, 8)
            sig = data[offset:offset + length]
            if len(sig) >= 12 and struct.unpack_from(">I", sig)[0] == 0xfade0cc0:
                for j in range(struct.unpack_from(">I", sig, 8)[0]):
                    slot, start = struct.unpack_from(">II", sig, 12 + j * 8)
                    if slot == 5:
                        bloblen = struct.unpack_from(">I", sig, start + 4)[0]
                        result["entitlements"] = plistlib.loads(sig[start + 8:start + bloblen])
        pos += size
    if symtab:
        offset, count, stroff, strlen = symtab
        strings = data[stroff:stroff + strlen]
        for i in range(count):
            strx, typ, sect, desc, value = struct.unpack_from("<IBBHQ", data, offset + i * 16)
            if value:
                symbols.setdefault(hex(value), []).append(cstr(strings[strx:]))
        result["initializer_symbols"] = {p: symbols.get(p, []) for p in result["initializers"]}
        result["diagnostic_symbols"] = [name for names in symbols.values() for name in names
                                        if "hakios_app_init" in name or "uncaught_exception" in name]
    return [result]


def inspect_ipa(path):
    with path.open("rb") as f:
        digest = hashlib.file_digest(f, "sha256").hexdigest()
    report = {"path": str(path), "size": path.stat().st_size, "sha256": digest, "binaries": []}
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        executables = set(n for n in names if n.endswith(".dylib"))
        for name in sorted(names):
            if not name.startswith("Payload/") or not name.endswith("/Info.plist"):
                continue
            try:
                info = plistlib.loads(archive.read(name))
            except plistlib.InvalidFileException:
                continue
            exe = info.get("CFBundleExecutable")
            if exe:
                binary = name.rsplit("/", 1)[0] + "/" + exe
                if binary in names:
                    executables.add(binary)
            if name.count("/") == 2:
                fields = ("CFBundleIdentifier", "CFBundleShortVersionString", "CFBundleVersion",
                          "CFBundleExecutable", "MinimumOSVersion", "DTPlatformVersion",
                          "DTSDKName", "UIRequiredDeviceCapabilities", "UIDeviceFamily")
                report["app_info"] = {key: info.get(key) for key in fields}
        for name in sorted(executables):
            data = archive.read(name)
            try:
                slices = macho(data)
            except ValueError as e:
                slices = {"error": str(e)}
            report["binaries"].append({"path": name, "size": len(data),
                                      "sha256": hashlib.sha256(data).hexdigest(), "slices": slices})
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--binary", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.binary:
        data = args.path.read_bytes()
        report = {"path": str(args.path), "sha256": hashlib.sha256(data).hexdigest(), "slices": macho(data)}
    else:
        report = inspect_ipa(args.path)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Saved inspection: {args.output}")
