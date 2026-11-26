import json
import glob
import os
import pathlib
from backup_a51 import verify_gpt

print("=== PARTITIONS IN GPT ===")
head = pathlib.Path('outputs/backups/RZ8N2032ZXE/gpt-head-before.bin').read_bytes()
tail = pathlib.Path('outputs/backups/RZ8N2032ZXE/gpt-tail-before.bin').read_bytes()
gpt = verify_gpt(head, tail)
for p in gpt['partitions']:
    name = p['name']
    mb = p['bytes'] // 1024 // 1024
    gb = mb / 1024.0
    print(f"{name:15} LBA {p['first_lba']:10}..{p['last_lba']:10} ({mb:8} MB / {gb:5.1f} GB) guid={p['guid']}")

print("\n=== AUDIO SCRIPTS AND FILES ===")
for f in glob.glob('outputs/scripts/*audio*') + glob.glob('devices/a51/drivers/audio/*'):
    print(f, os.path.getsize(f) if os.path.exists(f) else "N/A")

print("\n=== NETWORK / WIFI SCRIPTS AND FILES ===")
for f in glob.glob('outputs/scripts/*wifi*') + glob.glob('devices/a51/drivers/wifi/*'):
    print(f, os.path.getsize(f) if os.path.exists(f) else "N/A")
