"""Read phone partitions through adb exec-out; preserve binary bytes and verify hashes.

No command in this script writes a phone block device. Backup files are local only.
"""
import hashlib
import json
import pathlib
import subprocess
import uuid
import zlib
import struct
import shlex
import time

BASE = pathlib.Path(__file__).resolve().parents[1]
DEST = BASE / "outputs" / "backups" / "RZ8N2032ZXE"
ADB = r"C:\Android\platform-tools\adb.exe"
SERIAL = "RZ8N2032ZXE"
DISK_BYTES = 249888768 * 512
BLOCK = 4096


def adb_read(command, destination, expected):
    if destination.exists():
        raise RuntimeError(f"Refusing to overwrite {destination}")
    partial = destination.with_suffix(destination.suffix + ".partial")
    digest = hashlib.sha256()
    size = 0
    reported = time.monotonic()
    process = subprocess.Popen(
        [ADB, "-s", SERIAL, "exec-out", "su -c " + shlex.quote(command)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    with partial.open("xb") as output:
        while chunk := process.stdout.read(1024 * 1024):
            output.write(chunk)
            digest.update(chunk)
            size += len(chunk)
            if time.monotonic() - reported >= 30:
                print(f"{destination.name}: {size:,}/{expected:,} bytes ({100*size/expected:.1f}%)", flush=True)
                reported = time.monotonic()
    errors = process.stderr.read().decode(errors="replace")
    code = process.wait()
    if code or size != expected:
        raise RuntimeError(f"Backup failed: exit={code}, bytes={size}/{expected}, stderr={errors}")
    partial.rename(destination)
    return {"file": str(destination), "bytes": size, "sha256": digest.hexdigest()}


def remote_hash(partition):
    result = subprocess.run(
        [ADB, "-s", SERIAL, "shell", "su -c " + shlex.quote(f"sha256sum /dev/block/by-name/{partition}")],
        capture_output=True, text=True, check=True,
    )
    digest = result.stdout.strip().split()[0]
    if len(digest) != 64:
        raise RuntimeError(f"Unexpected checksum response: {result.stdout!r}")
    return digest


def header(blob, offset):
    if blob[offset:offset+8] != b"EFI PART":
        raise RuntimeError("Missing GPT signature")
    length, expected_crc = struct.unpack_from("<II", blob, offset+12)
    data = bytearray(blob[offset:offset+length])
    data[16:20] = b"\0" * 4
    actual_crc = zlib.crc32(data) & 0xffffffff
    if actual_crc != expected_crc:
        raise RuntimeError("GPT header CRC mismatch")
    return {
        "header_crc": expected_crc,
        "current_lba": struct.unpack_from("<Q", blob, offset+24)[0],
        "backup_lba": struct.unpack_from("<Q", blob, offset+32)[0],
        "first_usable_lba": struct.unpack_from("<Q", blob, offset+40)[0],
        "last_usable_lba": struct.unpack_from("<Q", blob, offset+48)[0],
        "disk_guid": str(uuid.UUID(bytes_le=blob[offset+56:offset+72])),
        "entries_lba": struct.unpack_from("<Q", blob, offset+72)[0],
        "entry_count": struct.unpack_from("<I", blob, offset+80)[0],
        "entry_size": struct.unpack_from("<I", blob, offset+84)[0],
        "entries_crc": struct.unpack_from("<I", blob, offset+88)[0],
    }


def verify_gpt(head, tail):
    primary = header(head, BLOCK)
    secondary = header(tail, len(tail)-BLOCK)
    if primary["current_lba"] != 1 or primary["backup_lba"] != DISK_BYTES // BLOCK - 1:
        raise RuntimeError("GPT disk geometry mismatch")
    if secondary["backup_lba"] != 1 or secondary["current_lba"] != primary["backup_lba"]:
        raise RuntimeError("Backup GPT disk geometry mismatch")
    if primary["disk_guid"] != secondary["disk_guid"]:
        raise RuntimeError("GPT disk GUID mismatch")
    size = primary["entry_count"] * primary["entry_size"]
    first = primary["entries_lba"] * BLOCK
    first_tail = secondary["entries_lba"] * BLOCK - (DISK_BYTES-len(tail))
    entries = head[first:first+size]
    entries_tail = tail[first_tail:first_tail+size]
    if entries != entries_tail or len(entries) != size:
        raise RuntimeError("Primary and backup partition entries disagree")
    for table, meta in [(entries,primary),(entries_tail,secondary)]:
        if zlib.crc32(table) & 0xffffffff != meta["entries_crc"]:
            raise RuntimeError("GPT partition table CRC mismatch")
    partitions = []
    for index in range(primary["entry_count"]):
        entry = entries[index*primary["entry_size"]:(index+1)*primary["entry_size"]]
        if entry[:16] == b"\0"*16:
            continue
        begin, end = struct.unpack_from("<QQ", entry, 32)
        partitions.append({
            "number": index+1,
            "name": entry[56:128].decode("utf-16le").rstrip("\0"),
            "type_guid": str(uuid.UUID(bytes_le=entry[:16])),
            "guid": str(uuid.UUID(bytes_le=entry[16:32])),
            "first_lba": begin, "last_lba": end,
            "bytes": (end-begin+1)*BLOCK,
        })
    ranges = sorted(partitions,key=lambda item:item["first_lba"])
    for item in ranges:
        if item["first_lba"] < primary["first_usable_lba"] or item["last_lba"] > primary["last_usable_lba"]:
            raise RuntimeError(f"Partition outside usable range: {item['name']}")
    for before, after in zip(ranges,ranges[1:]):
        if before["last_lba"] >= after["first_lba"]:
            raise RuntimeError("Overlapping GPT partitions")
    return {"logical_block_size": BLOCK,"primary":primary,"secondary":secondary,"partitions":partitions}


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    results = []
    for name, sectors in [("boot",120832),("recovery",138880)]:
        print(f"Backing up {name} ({sectors*512} bytes)...",flush=True)
        result = adb_read(f"dd if=/dev/block/by-name/{name} bs=1048576 2>/dev/null",DEST/f"{name}-before.img",sectors*512)
        result["phone_sha256"] = remote_hash(name)
        if result["phone_sha256"] != result["sha256"]:
            raise RuntimeError(f"Phone checksum mismatch for {name}")
        results.append(result)
        print(f"Verified {name}: {result['sha256']}",flush=True)
        (DEST/"backup-progress.json").write_text(json.dumps(results,indent=2))
    print("Backing up both GPT regions...",flush=True)
    for label,skip in [("head",0),("tail",DISK_BYTES//BLOCK-256)]:
        results.append(adb_read(f"dd if=/dev/block/sda bs=4096 skip={skip} count=256 2>/dev/null",DEST/f"gpt-{label}-before.bin",1024*1024))
    gpt = verify_gpt((DEST/"gpt-head-before.bin").read_bytes(),(DEST/"gpt-tail-before.bin").read_bytes())
    (DEST/"gpt-verified.json").write_text(json.dumps(gpt,indent=2))
    (DEST/"backup-manifest.json").write_text(json.dumps({"serial":SERIAL,"backups":results,"gpt_verified":True},indent=2))
    print("Backups and GPT validation completed.",flush=True)
    for item in gpt["partitions"]:
        if item["name"] in ["boot","recovery","userdata","darwin"]: print(json.dumps(item),flush=True)


if __name__ == "__main__":
    main()
