import hashlib
import json
import pathlib

manifest_paths = [
    pathlib.Path("outputs/boot-package-manifest.json"),
    pathlib.Path("outputs/high-fps-visuals/boot-package-manifest.json"),
]

for manifest_path in manifest_paths:
    if not manifest_path.exists():
        continue
    comp_dir = manifest_path.parent / "boot-components"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))

    # Compute actual hashes and sizes
    comp_map = {
        "kernel": ("kernel", "kernel"),
        "root.apfs": ("ramdisk", "root.apfs"),
        "flashboot.apfs": ("resident", "flashboot.apfs"),
    }

    for filename, (entry_name, _) in comp_map.items():
        comp_file = comp_dir / filename
        if not comp_file.exists():
            continue
        content = comp_file.read_bytes()
        sha256 = hashlib.sha256(content).hexdigest()
        size = len(content)

        if "components" in data and filename in data["components"]:
            data["components"][filename]["sha256"] = sha256
            data["components"][filename]["bytes"] = size

        if "payload" in data and "entries" in data["payload"] and entry_name in data["payload"]["entries"]:
            data["payload"]["entries"][entry_name]["sha256"] = sha256
            data["payload"]["entries"][entry_name]["bytes"] = size

        for pkg in data.get("packages", []):
            if "payload" in pkg and "entries" in pkg["payload"] and entry_name in pkg["payload"]["entries"]:
                pkg["payload"]["entries"][entry_name]["sha256"] = sha256
                pkg["payload"]["entries"][entry_name]["bytes"] = size

    manifest_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"Updated {manifest_path}")
