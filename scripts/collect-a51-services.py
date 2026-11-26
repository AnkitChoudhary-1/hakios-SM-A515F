"""Read Android's working power/audio state; no settings or device writes."""
from pathlib import Path
from datetime import datetime, timezone
import subprocess
import shlex
import json

OUT=Path(__file__).resolve().parents[1]/'device-services'/'android-reference'
OUT.mkdir(parents=True,exist_ok=True)
ADB=r'C:\Android\platform-tools\adb.exe'
commands={
 'battery': 'id; getprop sys.boot_completed; dumpsys battery; for p in /sys/class/power_supply/*; do echo "$p"; cat "$p/uevent"; done',
 'hardware-files': 'ls -la /sys/bus/i2c/devices/1-0049/ /sys/bus/i2c/devices/1-0071/ /sys/bus/i2c/devices/7-004c/; ls -la /sys/class/power_supply/battery/; ls -la /sys/bus/iio/devices/; ls /sys/kernel/debug/regmap/',
 'audio': 'cat /proc/asound/cards /proc/asound/pcm; ls -la /sys/devices/platform/14a50000.abox/; cat /sys/kernel/debug/asoc/codecs; dmesg | grep -iE "tas2562|sm5713|fuelgauge|abox|adc" | tail -350',
}
records=[]
for name,command in commands.items():
 result=subprocess.run([ADB,'-s','RZ8N2032ZXE','shell','su -c '+shlex.quote(command)],capture_output=True,timeout=35)
 target=OUT/(name+'.txt')
 target.write_bytes(result.stdout+b'\n'+result.stderr)
 records.append({'name':name,'command':command,'exit_code':result.returncode,'file':target.name})
 print(name, 'exit',result.returncode, 'bytes',target.stat().st_size)
(OUT/'manifest.json').write_text(json.dumps({'at_utc':datetime.now(timezone.utc).isoformat(),'commands':records,'phone_writes':False},indent=2)+'\n',encoding='utf-8')
