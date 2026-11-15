"""Byte-exact, bounded A51 commands. Importing this file never touches a device."""
from __future__ import annotations
import datetime as dt
import re
import subprocess
from phase4_support import pin, require, write_json

SERIAL = "A51_SERIAL_HERE"
BOOT = "/dev/block/sda12"
BASELINE_SHA256 = "eb30609a62999e3282ac81e0a5e56411ef12ec1a39c107171bf3e01209c7cb67"


class Device:
    def __init__(self, packet):
        self.packet = packet
        self.records = []

    def adb(self, name, args, *, timeout=45, limit=2097152, check=True, framed=False):
        argv = ["adb", "-s", SERIAL, *args]
        started = dt.datetime.now(dt.timezone.utc).isoformat()
        try:
            proc = subprocess.run(argv, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            proc = subprocess.CompletedProcess(argv, 124, exc.stdout or b"", (exc.stderr or b"") + b"\nTIMEOUT")
        raw = proc.stdout
        rc = proc.returncode
        if framed:
            (self.packet / (name + ".frame.bin")).write_bytes(raw)
            footer = re.search(rb"\nHAKIOS_REMOTE_EXIT:([0-9]{1,3})\n$", raw)
            if footer and int(footer[1]) <= 255:
                rc = rc or int(footer[1])
                raw = raw[:footer.start()]
            else:
                rc = rc or 125
        out = self.packet / (name + ".stdout.bin")
        err = self.packet / (name + ".stderr.bin")
        out.write_bytes(raw)
        err.write_bytes(proc.stderr)
        self.records.append({"name": name, "argv": argv, "started": started,
            "finished": dt.datetime.now(dt.timezone.utc).isoformat(), "exit_code": rc,
            "transport_exit_code": proc.returncode, "framed_remote_exit": framed,
            "stdout": pin(out), "stderr": pin(err)})
        write_json(self.packet / "commands.json", self.records)
        print({"command": name, "exit_code": rc, "bytes": len(raw)}, flush=True)
        require(len(raw) <= limit, name + ": output exceeded bound")
        if check:
            require(rc == 0, name + ": command failed, exit " + str(rc))
        return raw

    def root(self, name, command, *, recovery=False, **kwargs):
        frame = "{ " + command + "; }; hakios_capture_rc=$?; printf '\\nHAKIOS_REMOTE_EXIT:%d\\n' \"$hakios_capture_rc\""
        args = ["exec-out", "sh", "-c", frame] if recovery else ["exec-out", "su", "-c", frame]
        return self.adb(name, args, framed=True, **kwargs)

    def text(self, name, command, **kwargs):
        return self.root(name, command, **kwargs).decode("utf-8", "replace").strip()

    def mode(self, name):
        return self.adb(name, ["get-state"], timeout=8, check=False).decode("ascii", "replace").strip()
