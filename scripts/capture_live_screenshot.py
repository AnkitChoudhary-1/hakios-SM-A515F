import subprocess
import pathlib
import sys
import zlib
import struct

FASTBOOT = r'C:\Android\platform-tools\fastboot.exe'
USB_SERIAL = 'xnuloader'
ARTIFACT_DIR = pathlib.Path(r'C:\Users\Ankit\.gemini\antigravity\brain\266e5754-252f-4c13-b53a-a4ee6f21917c')

def get_var(name):
    res = subprocess.run([FASTBOOT, '-s', USB_SERIAL, 'getvar', name],
                         capture_output=True, text=True, timeout=5)
    out = res.stdout + res.stderr
    for line in out.splitlines():
        if f'{name}:' in line:
            return line.split(f'{name}:')[1].strip()
    return None

def write_png(buf, width, height, path):
    # Standard PNG writer from raw RGB
    def chunk(tag, data):
        return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff)
    
    ihdr = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    raw_lines = bytearray()
    stride = width * 3
    for y in range(height):
        raw_lines.append(0) # filter type none
        raw_lines.extend(buf[y*stride:(y+1)*stride])
    idat = zlib.compress(bytes(raw_lines), 9)
    png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr) + chunk(b'IDAT', idat) + chunk(b'IEND', b'')
    path.write_bytes(png)

def main():
    geom = get_var('screen')
    if not geom:
        print("Failed to get screen geometry")
        return 1
    width, height, stride = map(int, geom.split())
    print(f"Screen: {width}x{height}, stride={stride}")

    res = subprocess.run([FASTBOOT, '-s', USB_SERIAL, 'oem', 'screenshot'], capture_output=True, text=True, timeout=5)
    print("oem screenshot:", res.stdout.strip() or res.stderr.strip())

    bgrx_path = ARTIFACT_DIR / 'live_capture.bgrx'
    res = subprocess.run([FASTBOOT, '-s', USB_SERIAL, 'get_staged', str(bgrx_path)], capture_output=True, text=True, timeout=10)
    print("get_staged:", res.stdout.strip() or res.stderr.strip())

    raw = bgrx_path.read_bytes()
    print(f"Captured {len(raw)} bytes")

    # Convert BGRX to RGB
    rgb = bytearray(width * height * 3)
    for y in range(height):
        src_row = raw[y*stride : y*stride + width*4]
        dst_offset = y * width * 3
        for x in range(width):
            b = src_row[x*4]
            g = src_row[x*4 + 1]
            r = src_row[x*4 + 2]
            rgb[dst_offset + x*3] = r
            rgb[dst_offset + x*3 + 1] = g
            rgb[dst_offset + x*3 + 2] = b

    png_path = ARTIFACT_DIR / 'live_instagram_feed.png'
    write_png(rgb, width, height, png_path)
    print(f"Saved PNG to {png_path}")

    # Also make a preview
    from PIL import Image
    im = Image.open(png_path)
    preview = im.resize((width // 2, height // 2), Image.Resampling.LANCZOS)
    preview.save(ARTIFACT_DIR / 'live_instagram_feed_preview.png')
    print("Saved preview!")
    return 0

if __name__ == '__main__':
    sys.exit(main())
