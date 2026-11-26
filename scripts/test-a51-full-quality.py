"""Exercise actual renderer/scaler/clock helpers, with host mocks and sanitizers.

Does not substitute for on-device rendering, voltage, thermal or FPS validation.
"""
from pathlib import Path
import hashlib
import json
import re
import subprocess
import tempfile
import os
from datetime import datetime, timezone
from boot_line_budget import validate_boot_line

repo = Path('/opt/a51-hakios/upstream-a51/hakios')
profile = os.environ.get('A51_PROFILE', 'full-quality')
assert profile in ('full-quality', 'full-quality-recovery')
out = Path(__file__).resolve().parents[1] / profile
gl = (repo / 'userland/src/eagl.c').read_text()
fb = (repo / 'xnu/files/iokit/Kernel/MiniIOMobileFramebuffer.cpp').read_text()
clock = (repo / 'devices/a51/drivers/gpu/hakios.a51gpu.c').read_text()


def function(source, name):
    match = re.search(r'static (?:inline )?[\w ]+\n' + name + r'\(.*?\n\}', source, re.S)
    assert match, name
    return match.group()


header = '''#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
'''
tests = {}
tests['clock'] = header + function(clock, 'a51_clock_rate_from_regs') + function(clock, 'a51_clock_level') + r'''
int main(void) {
    assert(a51_clock_rate_from_regs(0xa0f30311,0,0)==1053000);
    assert(a51_clock_rate_from_regs(0xa1500311,0,0)==1456000);
    assert(a51_clock_rate_from_regs(0xa0a00412,0,0)==260000);
    assert(!a51_clock_rate_from_regs(0x80a00412,0,0)); /* unlocked */
    assert(!a51_clock_rate_from_regs(0x20a00412,0,0)); /* disabled */
    assert(!a51_clock_rate_from_regs(0xa0a00012,0,0)); /* zero PDIV */
    assert(!a51_clock_rate_from_regs(0xa0000412,0,0)); /* zero MDIV */
    assert(!a51_clock_rate_from_regs(0xa0a00412,1,0)); /* switch parent */
    assert(!a51_clock_rate_from_regs(0xa0a00412,0x10000,0));
    assert(!a51_clock_rate_from_regs(0xa0a00412,0,0x10000));
    uint32_t levels[]={949000,839000,572000,260000};
    assert(a51_clock_level(260000,levels,4,0)==260000);
    assert(!a51_clock_level(260001,levels,4,0));
    assert(a51_clock_level(838500,levels,4,500)==839000);
    assert(!a51_clock_level(838499,levels,4,500));
    assert(!a51_clock_level(0,levels,4,500));
    uint32_t ambiguous[]={260000,260500};
    assert(!a51_clock_level(260250,ambiguous,2,500));
    puts("PASS clock: captured PLL rates, unlock/disable/transition faults, exact and rounded OPP boundaries");
}
'''
scaler = '\n'.join(function(fb, n) for n in ['blend', 'filtered_pixel', 'filtered_row', 'nearest_row'])
tests['scaler'] = header + scaler + r'''
static uint32_t rnd(void) { static uint32_t r=42; r^=r<<13; r^=r>>17; return r^=r<<5; }
static uint32_t reference(uint32_t a,uint32_t b,uint32_t w) {
    uint32_t v=0;
    for(unsigned k=0;k<4;k++) v|=((((a>>(8*k))&255)*(256-w)+((b>>(8*k))&255)*w)>>8)<<(8*k);
    return v;
}
int main(void) {
    uint32_t src[1130], cols[1081]; uint16_t weights[1081];
    uint32_t *raw=malloc(1085*4), *out;
    for(unsigned round=0;round<3000;round++) {
        for(unsigned i=0;i<1130;i++) src[i]=rnd();
        unsigned n=round%1082;
        for(unsigned i=0;i<n;i++) { cols[i]=rnd()%1125; weights[i]=rnd()%256; }
        /* Last source pixel has no neighbour and must remain in bounds. */
        if(n) { cols[n-1]=1129; weights[n-1]=0; }
        out=raw+1+(round&1);
        for(unsigned i=0;i<1085;i++) raw[i]=0xfeedface;
        filtered_row(out,src,cols,weights,n);
        for(unsigned i=0;i<n;i++) assert(out[i]==reference(src[cols[i]],src[cols[i]+(weights[i]!=0)],weights[i]));
        assert(out[-1]==0xfeedface && out[n]==0xfeedface);
        nearest_row(out,src,cols,n);
        for(unsigned i=0;i<n;i++) assert(out[i]==src[cols[i]]);
        assert(out[-1]==0xfeedface && out[n]==0xfeedface);
    }
    free(raw);
    puts("PASS scaler: 3000 random rows, both alignments, odd/even lengths, boundary columns, exact four-channel interpolation");
}
'''

image = gl[gl.index('struct image {'):gl.index('\nstruct eagl {')]
gl_mocks = r'''
typedef unsigned GLuint, GLenum; typedef int GLsizei, GLint;
#define GL_TEXTURE_2D 0x0de1
#define GL_TEXTURE_BINDING_2D 0x8069
#define GL_BGRA 0x80e1
#define GL_RGBA 0x1908
#define GL_UNSIGNED_BYTE 0x1401
#define GL_UNPACK_ROW_LENGTH 0x0cf2
#define GL_UNPACK_ALIGNMENT 0x0cf5
#define kIOSurfaceLockReadOnly 1
struct surface { uint8_t data[256]; unsigned row, planes, seed; };
typedef struct surface *IOSurfaceRef;
IMAGE
struct eagl { unsigned frames,uploads; uint64_t upload_bytes; struct image *images; unsigned image_count; };
static unsigned allocations,updates,locks,binding;
static uint8_t texture[256]; static int stored_w,stored_h;
static int trace_placing=0,still_seldom=0;
#define STILL_LOOKS 120
#define STILL_EVERY 8
#define say(...) ((void)0)
static size_t IOSurfaceGetBytesPerRow(IOSurfaceRef s) { return s->row; }
static size_t IOSurfaceGetBytesPerRowOfPlane(IOSurfaceRef s,uint32_t p) { (void)p; return s->row; }
static unsigned IOSurfaceGetPlaneCount(IOSurfaceRef s) { return s->planes; }
static void *IOSurfaceGetBaseAddress(IOSurfaceRef s) { return s->data; }
static void *IOSurfaceGetBaseAddressOfPlane(IOSurfaceRef s,uint32_t p) { (void)p; return s->data; }
static unsigned IOSurfaceGetID(IOSurfaceRef s) { (void)s; return 1; }
static unsigned IOSurfaceGetSeed(IOSurfaceRef s) { return s->seed; }
static int IOSurfaceLock(IOSurfaceRef s,unsigned flags,void *v) { (void)s;(void)flags;(void)v;locks++;return 0; }
static void IOSurfaceUnlock(IOSurfaceRef s,unsigned flags,void *v) { (void)s;(void)flags;(void)v;assert(locks);locks--; }
static unsigned bytes_a_pixel(GLenum format,GLenum type) { (void)type;return format==GL_BGRA?4:1; }
static GLenum internal_format(GLenum internal,GLenum format) { (void)format;return internal; }
static void glGetIntegerv(GLenum n,GLint *v) { *v=n==GL_TEXTURE_BINDING_2D?binding:4; }
static void glPixelStorei(GLenum n,GLint v) { (void)n;(void)v; }
static struct image *image_of(struct eagl *e,GLuint t) {
    for(unsigned i=0;i<e->image_count;i++) if(e->images[i].texture==t) return e->images+i;
    return NULL;
}
static void glTexImage2D(GLenum t,int l,GLint in,int w,int h,int b,GLenum f,GLenum ty,const void *p) {
    (void)t;(void)l;(void)in;(void)b;(void)ty;
    allocations++;stored_w=w;stored_h=h;memcpy(texture,p,w*h*bytes_a_pixel(f,ty));
}
static void glTexSubImage2D(GLenum t,int l,int x,int y,int w,int h,GLenum f,GLenum ty,const void *p) {
    (void)t;(void)l;(void)x;(void)y;
    assert(w==stored_w && h==stored_h);updates++;memcpy(texture,p,w*h*bytes_a_pixel(f,ty));
}
'''.replace('IMAGE', image)
tests['renderer'] = header + gl_mocks + '\n'.join(function(gl, n) for n in
    ['surface_changed', 'surface_to_texture', 'image_storage_forget']) + r'''
int main(void) {
    struct surface s={.row=3};
    struct image image={.texture=17,.surface=&s,.to=GL_TEXTURE_2D,.width=3,.height=1,.format=GL_RGBA};
    struct eagl e={.images=&image,.image_count=1}; binding=17;
    surface_to_texture(&e,&image);
    assert(allocations==1 && updates==0 && image.storage && !locks);
    s.data[2]=91;
    surface_to_texture(&e,&image);
    assert(allocations==1 && updates==1 && texture[2]==91 && !locks);
    image_storage_forget(&e,GL_TEXTURE_2D,1);assert(image.storage);
    image_storage_forget(&e,GL_TEXTURE_2D,0);assert(!image.storage);
    image.width=2;s.row=2;surface_to_texture(&e,&image);
    assert(allocations==2 && stored_w==2);
    binding=99;image_storage_forget(&e,GL_TEXTURE_2D,0);assert(image.storage);
    image.shared=true;surface_to_texture(&e,&image);assert(allocations==2 && updates==1);
    image.shared=false;
    /* Every possible final byte, lengths 1..39, must affect the actual checksum. */
    for(unsigned n=1;n<=39;n++) {
        memset(s.data,0,sizeof(s.data));s.row=n;image.width=n;image.height=1;
        image.sum=0;image.looked=0;e.frames++;
        assert(surface_changed(&e,&image));
        e.frames++;assert(!surface_changed(&e,&image));
        s.data[n-1]=127;e.frames++;assert(surface_changed(&e,&image));
    }
    /* Format/inversion still travel through the same conversion path. */
    image.storage=false;image.width=2;image.height=2;image.invert=true;s.row=2;
    s.data[0]=1;s.data[1]=2;s.data[2]=3;s.data[3]=4;
    surface_to_texture(&e,&image);assert(texture[0]==3 && texture[3]==2 && !locks);
    puts("PASS renderer: allocation/update, client redefinition, geometry, sharing, inversion, checksum tails 1..39");
}
'''

results = {}
with tempfile.TemporaryDirectory(prefix='a51-full-quality-') as tmp:
    tmp = Path(tmp)
    for name, source in tests.items():
        c, exe = tmp / (name + '.c'), tmp / name
        c.write_text(source)
        subprocess.run(['clang', '-std=c11', '-O1', '-g', '-Wall', '-Wextra',
                        '-fsanitize=address,undefined', str(c), '-o', str(exe)], check=True)
        result = subprocess.run([str(exe)], text=True, capture_output=True, check=True)
        results[name] = result.stdout.strip()
        print(result.stdout.strip())
    # Check generated ARM64 code uses wide stores without FP/SIMD registers.
    c = tmp / 'scaler.c'
    c.write_text('typedef unsigned int uint32_t; typedef unsigned short uint16_t; '
                 'typedef unsigned long uint64_t,uintptr_t;\n'
                 '#define memcpy __builtin_memcpy\n' + scaler +
                 '\nvoid scale(uint32_t *o,const uint32_t *f,const uint32_t *c,const uint16_t *w,uint32_t n) '
                 '{ filtered_row(o,f,c,w,n); }\n')
    assembly = subprocess.check_output(['clang', '-target', 'aarch64-none-elf', '-O2',
                                       '-mgeneral-regs-only', '-S', str(c), '-o', '-'], text=True)
    assert re.search(r'\bstr\s+x\d+', assembly), 'No wide framebuffer store emitted'
    assert not re.search(r'\b[qdsv]\d+\b', assembly), 'Unexpected FP/SIMD register'
    (out / 'scaler-arm64.s').write_text(assembly)
    results['arm64'] = 'General-register 64-bit stores verified; no SIMD registers'

budget = validate_boot_line('cpus=7 ufs=2 loader_return_after=0 touch_lat=1', 'test-version')
assert budget['maximum_prefix_bytes'] > 70
try:
    validate_boot_line('cpus=7 ufs=2 ' + 'x' * 550, 'test-version')
except ValueError:
    pass
else:
    raise AssertionError('Effective command-line overflow accepted')
assert validate_boot_line('battery=1', 'test-version')['maximum_prefix_bytes'] > budget['maximum_prefix_bytes']
results['boot_line'] = 'Loader prefix and tracing/manual return reserved; overflow rejected'
# Both redefinition entry points and the per-binding reset must invalidate storage.
assert gl.count('image_storage_forget(e, target, level);') == 2
assert 'memset(image, 0, sizeof(*image));' in gl
record = {'at_utc': datetime.now(timezone.utc).isoformat(), 'passed': True,
          'results': results, 'hardware_rendering_or_fps_verified': False,
          'sources': {name: hashlib.sha256(s.encode()).hexdigest() for name, s in
                      [('eagl', gl), ('framebuffer', fb), ('clock', clock)]}}
(out / 'correctness-tests.json').write_text(json.dumps(record, indent=2) + '\n')
print('All full-quality host correctness tests passed. Hardware validation pending.')
