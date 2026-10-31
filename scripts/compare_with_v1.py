"""Regression check: SMD-ANIM converter vs the released PT-World-Map v1.0 converter.

Maps and static props must come out byte-identical; only files with animation
keys (now rebuilt from the game's cached rotations) may differ.
"""
import importlib.util
import os
import sys
import tempfile

FIELD = r'C:\Program Files (x86)\MasangSoft\PristonTale(Test)\Field'


def load(name, root):
    spec = importlib.util.spec_from_file_location(name, os.path.join(root, '__init__.py'),
                                                  submodule_search_locations=[root])
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return importlib.import_module(name + '.convert')


old = load('ptsmd_v1', r'X:\Projects\PT-World-Map\tools\ptsmd')
new = load('smdanim_new', r'X:\Projects\SMD-ANIM\smdanim')
files = []
for d, _s, names in os.walk(FIELD):
    files += [os.path.join(d, n) for n in names if n.lower().endswith('.smd')]
files.sort()
step = max(1, len(files) // int(sys.argv[1] if len(sys.argv) > 1 else 60))
tmp = tempfile.mkdtemp()
same = diff = 0
for f in files[::step]:
    a, b = os.path.join(tmp, 'a.ase'), os.path.join(tmp, 'b.ase')
    sa = old.convert_file(f, a, old.Options())
    new.convert_file(f, b, new.Options(split_objects=False))       # v1.0 wrote maps as one mesh
    if open(a, 'rb').read() == open(b, 'rb').read():
        same += 1
    else:
        diff += 1
        animated = any(o.rot_keys or o.pos_keys for o in sa.objects)
        print('DIFFERS %s (%s, animated=%s)' % (os.path.relpath(f, FIELD), sa.kind, animated))
print('identical %d, different %d' % (same, diff))
