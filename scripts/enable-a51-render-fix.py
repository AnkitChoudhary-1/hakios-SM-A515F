"""Apply the evidence-based IOSurface table fix to the existing WSL checkout.

Host files only. Preserve source before/after, patch and content hashes.
"""
from pathlib import Path
from datetime import datetime, timezone
import difflib
import hashlib
import json

REPO = Path('/opt/a51-hakios/upstream-a51/hakios')
OUT = Path(__file__).resolve().parents[1] / 'render-fix'
OUT.mkdir(exist_ok=True)


def replace_once(text, old, new):
    if new in text:
        return text
    if text.count(old) != 1:
        raise RuntimeError('Unexpected source context: ' + old[:100])
    return text.replace(old, new, 1)


rel = 'userland/src/eagl.c'
path = REPO / rel
before = path.read_text(encoding='utf-8')
after = replace_once(before, '\tstruct image images[256];\n\tunsigned image_count;',
    '\tstruct image *images;          /* live IOSurface bindings, grown as needed */\n'
    '\tunsigned image_count, image_capacity;')
after = replace_once(after, '''		if (e->image_count == sizeof(e->images) / sizeof(e->images[0])) {
			say("hakios-gl: more textures with IOSurfaces than there is room for\\n");
			return NULL;
		}''', '''		if (e->image_count == e->image_capacity) {
			/* A Settings/app tour exceeds 256 live bindings. Keep all of them:
			 * dropping an attachment leaves its texture without the requested pixels.
			 * No pointers into this table survive an image_new() call. */
			if (e->image_capacity > UINT32_MAX / 2) {
				return NULL;
			}
			unsigned capacity = e->image_capacity ? e->image_capacity * 2 : 256;
			if ((size_t)capacity > SIZE_MAX / sizeof(*e->images)) {
				return NULL;
			}
			struct image *images = realloc(e->images, (size_t)capacity * sizeof(*images));
			if (images == NULL) {
				say("hakios-gl: IOSurface binding allocation failed at %u live textures\\n", e->image_count);
				return NULL;       /* old allocation and bindings remain intact */
			}
			e->images = images;
			e->image_capacity = capacity;
			say("hakios-gl: IOSurface binding capacity %u, live %u\\n", capacity, e->image_count);
		}''')
after = replace_once(after, '\t\t*image = e->images[--e->image_count];',
    '\t\tunsigned last = --e->image_count;\n'
    '\t\t*image = e->images[last];\n'
    '\t\tmemset(&e->images[last], 0, sizeof(*image));')
after = replace_once(after, '\t\thakios_gl_destroy(e->gl);\n\t\tfree(e);',
    '\t\thakios_gl_destroy(e->gl);\n'
    '\t\tfor (unsigned i = 0; i < e->image_count; i++) {\n'
    '\t\t\tCFRelease(e->images[i].surface);\n\t\t}\n'
    '\t\tfree(e->images);\n\t\tfree(e);')

for kind, contents in [('source-before', before), ('source', after)]:
    dest = OUT / kind / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    if kind != 'source-before' or not dest.exists():
        dest.write_text(contents, encoding='utf-8')
path.write_text(after, encoding='utf-8')
original = (OUT / 'source-before' / rel).read_text(encoding='utf-8')
(OUT / 'render-fix.patch').write_text(''.join(difflib.unified_diff(
    original.splitlines(True), after.splitlines(True), fromfile='a/'+rel,
    tofile='b/'+rel)), encoding='utf-8')
manifest = {
    'updated_at_utc': datetime.now(timezone.utc).isoformat(),
    'file': str(path),
    'before_sha256': hashlib.sha256(original.encode()).hexdigest(),
    'source_sha256': hashlib.sha256(after.encode()).hexdigest(),
    'reason': 'Hardware logs show the fixed 256-entry IOSurface binding table filled and later attachments failed.',
    'phone_writes': False,
}
(OUT / 'source-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
print(json.dumps(manifest, indent=2))
