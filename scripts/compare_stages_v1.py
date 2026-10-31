"""Every map (stage .smd) in one-mesh mode must be byte-identical to the v1.0 converter.

  python scripts/compare_stages_v1.py
"""
import os
import sys
import tempfile

sys.argv = sys.argv[:1] + ['1']
here = os.path.dirname(os.path.abspath(__file__))
exec(open(os.path.join(here, 'compare_with_v1.py'), encoding='utf-8').read().split('files = []')[0])
import smdanim_new.smdfile as sf   # noqa: E402

files = []
for d, _s, names in os.walk(FIELD):
    files += [os.path.join(d, n) for n in names if n.lower().endswith('.smd')]
tmp = tempfile.mkdtemp()
same = diff = 0
for f in sorted(files):
    with open(f, 'rb') as fh:
        if not fh.read(32).startswith(sf.STAGE_HEADER):
            continue
    a, b = os.path.join(tmp, 'a.ase'), os.path.join(tmp, 'b.ase')
    old.convert_file(f, a, old.Options())
    new.convert_file(f, b, new.Options(split_objects=False))
    if open(a, 'rb').read() == open(b, 'rb').read():
        same += 1
    else:
        diff += 1
        print('DIFFERS', f)
print('stages identical %d, different %d' % (same, diff))
