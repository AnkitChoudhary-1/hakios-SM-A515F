import hashlib
import json
import pathlib
import subprocess
import re

package_dir = pathlib.Path("outputs/full-quality-recovery")
comp_dir = package_dir / "boot-components"

# 1. Copy files from WSL
print("Copying newly built kernel, root.apfs, and flashboot.apfs from WSL...")
subprocess.run(['wsl', 'cp', '/opt/a51-hakios/upstream-a51/hakios/hakios-kernel', 
                f"/mnt/c/Users/Ankit/Documents/Codex/2026-11-21/hi-2/{comp_dir.as_posix()}/kernel"], check=True)
subprocess.run(['wsl', 'cp', '/opt/a51-hakios/upstream-a51/hakios/userland/root.apfs', 
                f"/mnt/c/Users/Ankit/Documents/Codex/2026-11-21/hi-2/{comp_dir.as_posix()}/root.apfs"], check=True)
subprocess.run(['wsl', 'cp', '/opt/a51-hakios/upstream-a51/hakios/userland/flashboot.apfs', 
                f"/mnt/c/Users/Ankit/Documents/Codex/2026-11-21/hi-2/{comp_dir.as_posix()}/flashboot.apfs"], check=True)

# 2. Update manifest
manifest_path = package_dir / "boot-package-manifest.json"
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

comp_map = {
    "kernel": ("kernel", "kernel"),
    "root.apfs": ("ramdisk", "root.apfs"),
    "flashboot.apfs": ("resident", "flashboot.apfs"),
}

for filename, (entry_name, _) in comp_map.items():
    comp_file = comp_dir / filename
    content = comp_file.read_bytes()
    sha256 = hashlib.sha256(content).hexdigest()
    size = len(content)

    if "components" in manifest and filename in manifest["components"]:
        manifest["components"][filename]["sha256"] = sha256
        manifest["components"][filename]["bytes"] = size

    if "payload" in manifest and "entries" in manifest["payload"] and entry_name in manifest["payload"]["entries"]:
        manifest["payload"]["entries"][entry_name]["sha256"] = sha256
        manifest["payload"]["entries"][entry_name]["bytes"] = size

    for pkg in manifest.get("packages", []):
        if "payload" in pkg and "entries" in pkg["payload"] and entry_name in pkg["payload"]["entries"]:
            pkg["payload"]["entries"][entry_name]["sha256"] = sha256
            pkg["payload"]["entries"][entry_name]["bytes"] = size

def fix_cmdline(cmdline):
    # Ensure critical flags
    cmdline = re.sub(r'\bufs_write=\d+\b', 'ufs_write=1', cmdline)
    cmdline = re.sub(r'\bvar_store=\d+\b', 'var_store=1', cmdline)
    cmdline = re.sub(r'\btouch_lat=\d+\b', 'touch_lat=0', cmdline)
    cmdline = re.sub(r'\ba51gpu_clock=\d+\b', 'a51gpu_clock=3', cmdline)
    
    # Strip redundant parameters that exceed budget (defaults already achieve max 1742/2314/1053 MHz)
    cmdline = re.sub(r'\s*\ba51cpu0_khz=\d+\b', '', cmdline)
    cmdline = re.sub(r'\s*\ba51cpu1_khz=\d+\b', '', cmdline)
    cmdline = re.sub(r'\s*\ba51gpu_mhz=\d+\b', '', cmdline)
    cmdline = re.sub(r'\s*\ba51mif_khz=\d+\b', '', cmdline)
    cmdline = re.sub(r'\s*\ba51int_khz=\d+\b', '', cmdline)
    cmdline = re.sub(r'\s*\ba51gpu_report=\d+\b', '', cmdline)
    cmdline = re.sub(r'\s*\ba51audio=\d+\b', '', cmdline)
    
    if "a51battery=" not in cmdline:
        cmdline = cmdline + " a51battery=2"
    else:
        cmdline = re.sub(r'\ba51battery=\d+\b', 'a51battery=2', cmdline)
        
    return cmdline.strip()

if "cmdline" in manifest:
    manifest["cmdline"] = fix_cmdline(manifest["cmdline"])

for pkg in manifest.get("packages", []):
    if "cmdline" in pkg:
        pkg["cmdline"] = fix_cmdline(pkg["cmdline"])
        print(f"Updated package {pkg.get('mode')} cmdline ({len(pkg['cmdline'])} chars): {pkg['cmdline']}")

manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
print(f"Successfully updated {manifest_path}")
