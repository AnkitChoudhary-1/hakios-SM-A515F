"""Compile the actual binding-table code with ASan/UBSan and exercise its lifetime.

Uses mock GL/CF handles; does not claim GPU rendering is verified.
"""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import subprocess
import tempfile

repo = Path('/opt/a51-hakios/upstream-a51/hakios')
out = Path(__file__).resolve().parents[1] / 'render-fix'
source = (repo / 'userland/src/eagl.c').read_text(encoding='utf-8')
image = source[source.index('struct image {'):source.index('\nstruct eagl {')]
functions = source[source.index('static struct image *\nimage_of('):
                   source.index("/* Apple's OpenGL ES takes blue-first pixels")]
test = r'''
#include <assert.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>
#include <stdio.h>
typedef unsigned GLuint, GLenum;
typedef int GLsizei;
struct surface { unsigned refs; };
typedef struct surface *IOSurfaceRef;
static unsigned mirrors_deleted;
static int fail_allocation;
static void *test_realloc(void *p, size_t bytes) {
    return fail_allocation ? NULL : realloc(p, bytes);
}
static void *CFRetain(IOSurfaceRef p) { p->refs++; return p; }
static void CFRelease(IOSurfaceRef p) { assert(p && p->refs); p->refs--; }
static void glDeleteTextures(int n, const GLuint *texture) {
    assert(n == 1 && *texture); mirrors_deleted++;
}
#define say(...) ((void)0)
#define realloc test_realloc
IMAGE_STRUCT
struct eagl { struct image *images; unsigned image_count, image_capacity; };
IMAGE_FUNCTIONS
#undef realloc
int main(void) {
    struct eagl e = {0};
    struct surface surfaces[2050] = {0};
    for (unsigned i=0; i<2048; i++) {
        struct image *p = image_new(&e, i+1, &surfaces[i]);
        assert(p && p->texture == i+1 && p->surface == &surfaces[i]);
        assert(e.image_count == i+1 && e.image_capacity >= e.image_count);
    }
    assert(e.image_capacity == 2048);
    for (unsigned i=0; i<2048; i++) {
        assert(image_of(&e,i+1)->surface == &surfaces[i]);
        assert(surfaces[i].refs == 1);
    }
    struct image *old_images=e.images;
    fail_allocation=1;
    assert(!image_new(&e,2049,&surfaces[2048]));
    assert(e.images==old_images && e.image_count==2048 && e.image_capacity==2048);
    assert(surfaces[2048].refs==0 && image_of(&e,123)->surface==&surfaces[122]);
    fail_allocation=0;
    assert(image_new(&e,2049,&surfaces[2048]));
    assert(e.image_count==2049 && e.image_capacity==4096);
    image_of(&e,123)->mirror=99;
    assert(image_new(&e,123,&surfaces[2049]));
    assert(e.image_count==2049 && mirrors_deleted==1);
    assert(surfaces[122].refs==0 && surfaces[2049].refs==1);
    image_forget(&e,1000); /* middle deletion must preserve the moved last binding */
    assert(!image_of(&e,1000) && image_of(&e,2049)->surface==&surfaces[2048]);
    assert(e.image_count==2048 && surfaces[999].refs==0);
    image_forget(&e,1000); /* deletion of an absent texture is harmless */
    assert(e.image_count==2048);
    while(e.image_count) image_forget(&e,e.images[0].texture);
    for(unsigned i=0;i<2050;i++) assert(!surfaces[i].refs);
    for(unsigned round=0;round<100;round++) {
        for(unsigned i=0;i<300;i++) assert(image_new(&e,i+1,&surfaces[i]));
        for(unsigned i=300;i;i--) image_forget(&e,i);
        assert(!e.image_count);
        for(unsigned i=0;i<300;i++) assert(!surfaces[i].refs);
    }
    free(e.images);
    puts("PASS: 2049 live bindings, four growth boundaries, allocation failure, replacement, compaction, 100 reuse cycles; no ASan/UBSan findings");
}
'''.replace('IMAGE_STRUCT', image).replace('IMAGE_FUNCTIONS', functions)
with tempfile.TemporaryDirectory(prefix='a51-render-fix-') as tmp:
    folder = Path(tmp)
    cfile, exe = folder/'bindings.c', folder/'bindings'
    cfile.write_text(test, encoding='utf-8')
    subprocess.run(['clang', '-std=c11', '-O1', '-g', '-Wall', '-Wextra',
                    '-fsanitize=address,undefined', str(cfile), '-o', str(exe)], check=True)
    result = subprocess.run([str(exe)], capture_output=True, text=True, check=True)
record = {'updated_at_utc': datetime.now(timezone.utc).isoformat(),
          'source_sha256': hashlib.sha256(source.encode()).hexdigest(),
          'passed': True, 'actual_source_functions_compiled': True,
          'hardware_rendering_verified': False, 'output': result.stdout.strip()}
out.mkdir(exist_ok=True)
(out/'binding-tests.json').write_text(json.dumps(record, indent=2)+'\n', encoding='utf-8')
print(record['output'])
