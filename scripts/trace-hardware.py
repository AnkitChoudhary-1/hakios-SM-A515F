#!/usr/bin/env python3
"""Trace retained Linux references and boot headers; read phone firmware names."""
import datetime as dt
import json
import shutil
import struct
from pathlib import Path
from inventory import command, file_record, PROJECT, WORKSPACE

def main():
    source = WORKSPACE / 'kernel-work/source'
    groups = {
        'board': ['arch/arm64/boot/dts/samsung/exynos9611-a51*', 'arch/arm64/boot/dts/samsung/exynos9610.dtsi',
                  'arch/arm64/boot/dts/samsung/exynos9610-gpu.dtsi'],
        'display': ['drivers/video/fbdev/exynos/dpu20/decon_core.c', 'drivers/video/fbdev/exynos/dpu20/dsim_drv.c',
                    'drivers/video/fbdev/exynos/dpu20/panels/*a51*lcd_ctrl.c'],
        'touch': ['drivers/input/touchscreen/melfas/mss100/melfas_mss100.c'],
        'gpu': ['drivers/gpu/arm/exynos/Kbuild', 'drivers/gpu/arm/exynos/mali_exynos_kbase_entrypoint.c',
                'drivers/gpu/arm/exynos/frontend/gpex_clock.c', 'drivers/gpu/arm/exynos/frontend/gpex_pm.c',
                'drivers/gpu/arm/exynos/frontend/gpex_dvfs.c',
                'drivers/gpu/arm/exynos/backend/gpexbe_clock*.c',
                'drivers/gpu/arm/bv_r38p1/mali_kbase_core_linux.c'],
        'wifi_bluetooth': ['drivers/misc/samsung/scsc/platform_mif.c', 'drivers/misc/samsung/scsc/scsc_mx_impl.c',
                           'drivers/misc/samsung/scsc/platform_mif_9610.c',
                           'drivers/misc/samsung/scsc/fw*.c', 'drivers/net/wireless/scsc/dev.c',
                           'drivers/net/wireless/scsc/hip4.c', 'drivers/net/wireless/scsc/mlme.c',
                           'drivers/net/wireless/scsc/cfg80211_ops.c', 'drivers/net/wireless/scsc/fapi.h',
                           'drivers/misc/samsung/scsc_bt/*.c'],
        'audio': ['sound/soc/samsung/abox/abox.c', 'sound/soc/samsung/exynos9610-rt5665.c',
                  'sound/soc/codecs/rt5665.c','sound/soc/codecs/rt5510.c'],
        'charging': ['drivers/battery_v2/sm5713*.c','arch/arm64/boot/dts/samsung/exynos9611-if-pmic-sm5713.dtsi'],
        'ufs': ['drivers/scsi/ufs/ufs-exynos*.c','drivers/phy/samsung/phy-exynos-ufs*.c']}
    result = {'schema_version':1, 'captured_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
              'phone_writes':False,'linux_reference_groups':{},'boot_images':[]}
    for group,patterns in groups.items():
        matches = sorted({p for pattern in patterns for p in source.glob(pattern) if p.is_file()})
        result['linux_reference_groups'][group] = {'patterns':patterns,'files':[file_record(p) for p in matches],
                'status':'source references only; fitted hardware and firmware compatibility require device evidence'}
    for name in ('a51-pixelos-original-boot.img','a51-twrp-original-recovery.img'):
        path = WORKSPACE / 'everline-ksu/backups' / name
        with path.open('rb') as f:
            header=f.read(4096)
        if header[:8]!=b'ANDROID!': raise RuntimeError('unexpected boot magic '+str(path))
        values=struct.unpack_from('<10I',header,8)
        keys=('kernel_size','kernel_addr','ramdisk_size','ramdisk_addr','second_size','second_addr',
              'tags_addr','page_size','header_version','os_version')
        record=file_record(path)
        record['header']=dict(zip(keys,values))
        record['header']['name']=header[48:64].split(b'\0')[0].decode(errors='replace')
        record['header']['cmdline']=(header[64:576]+header[608:1632]).split(b'\0')[0].decode(errors='replace')
        if values[8] in (1,2):
            record['header']['recovery_dtbo_size']=struct.unpack_from('<I',header,1632)[0]
            record['header']['recovery_dtbo_offset']=struct.unpack_from('<Q',header,1636)[0]
            record['header']['header_size']=struct.unpack_from('<I',header,1644)[0]
        if values[8]==2:
            record['header']['dtb_size']=struct.unpack_from('<I',header,1648)[0]
            record['header']['dtb_addr']=struct.unpack_from('<Q',header,1652)[0]
        result['boot_images'].append(record)
    live=json.loads((PROJECT/'manifests/device-and-inputs.json').read_text())
    adb=shutil.which('adb')
    devices=live['connected_devices']
    result['device_queries']=[]
    if adb and len(devices)==1:
        prefix=[adb,'-s',devices[0],'shell']
        queries=[['cat','/sys/class/block/sda12/size'],['cat','/sys/class/block/sda10/size'],
                 ['cat','/sys/class/block/sda13/size'],['cat','/proc/iomem'],
                 ['cat','/sys/firmware/devicetree/base/model'],['cat','/sys/firmware/devicetree/base/compatible'],
                 ['find','/vendor/firmware','/vendor/etc/wifi','/vendor/etc/bluetooth','-type','f'],
                 ['ls','-l','/sys/bus/i2c/devices'],['ls','-l','/sys/class/graphics/fb0/device/driver']]
        result['device_queries']=[command(prefix+q,timeout=30) for q in queries]
    destination=PROJECT/'manifests/hardware-inputs.json'
    snapshots=PROJECT/'manifests/hardware-snapshots'
    snapshots.mkdir(exist_ok=True)
    stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    if destination.exists(): shutil.copy2(destination,snapshots/(stamp+'-previous.json'))
    (snapshots/(stamp+'.json')).write_text(json.dumps(result,indent=2)+'\n')
    destination.write_text(json.dumps(result,indent=2)+'\n')
    print('Wrote',destination)
    for group,data in result['linux_reference_groups'].items(): print(group,len(data['files']),'traced files')
    print('Read-only device queries:',len(result['device_queries']))

if __name__=='__main__': main()
