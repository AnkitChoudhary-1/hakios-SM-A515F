"""Apply audio driver fix, userland sound test, and UI smoothness settings."""
import os
import subprocess
from pathlib import Path

BASE = Path(__file__).resolve().parent

# 1. Update prepare_boot.py: ensure fb_threads=1 (fastest for write-combined RAM) and clean bootline
prep_path = BASE / 'prepare_boot.py'
prep_content = prep_path.read_text(encoding='utf-8')
prep_content = prep_content.replace('fb_threads=3', 'fb_threads=1')
prep_content = prep_content.replace(' touch_poll_us=4000', '')
prep_path.write_text(prep_content, encoding='utf-8', newline='\n')
print("Updated prepare_boot.py (fb_threads=1, no touch_poll_us)")

# 2. Normalize CRLF -> LF for scripts
for fname in ['rc.jobs.a51-smooth', 'patch_speaker_audio.py', 'build-a51-smooth.sh']:
    fpath = BASE / fname
    if fpath.exists():
        data = fpath.read_bytes().replace(b'\r\n', b'\n')
        fpath.write_bytes(data)
        print(f"Normalized {fname}")

# 3. Run patch_speaker_audio.py inside WSL
wsl_cmd = "python3 /mnt/c/Users/Ankit/Documents/Codex/2026-11-21/hi-2/outputs/scripts/patch_speaker_audio.py"
print(f"Running in WSL: {wsl_cmd}")
res = subprocess.run(["wsl", "bash", "-c", wsl_cmd], capture_output=True, text=True)
print("WSL stdout:", res.stdout)
print("WSL stderr:", res.stderr)
assert res.returncode == 0, "patch_speaker_audio.py failed"

# 4. Copy rc.jobs.a51-smooth to userland in WSL
cp_cmd = "cp /mnt/c/Users/Ankit/Documents/Codex/2026-11-21/hi-2/outputs/scripts/rc.jobs.a51-smooth /opt/a51-hakios/upstream-a51/hakios/userland/root/etc/rc.jobs"
res_cp = subprocess.run(["wsl", "bash", "-c", cp_cmd], capture_output=True, text=True)
print("Copied rc.jobs to userland:", res_cp.returncode)
assert res_cp.returncode == 0, "Failed to copy rc.jobs"

print("All audio and smoothness modifications successfully applied!")
