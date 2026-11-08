"""Check the .inx decompiler / compiler against a client folder.

    python check_inx.py <client folder> [--show N]

1) every shipped text file (.ini / .in / .inf) next to its .inx: compile_ini() == the game's .inx
2) every .inx: compile_ini(inx_to_ini(inx)) == the .inx   (byte for byte)
"""
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from smdanim import clientfiles as cf          # noqa: E402

root = sys.argv[1]
show = int(sys.argv[sys.argv.index('--show') + 1]) if '--show' in sys.argv else 5


def first_diff(a, b, L):
    for i in range(min(len(a), len(b))):
        if a[i] != b[i]:
            if L.motions <= i < L.count:
                k, r = divmod(i - L.motions, L.rec)
                return 'motion %d byte %d (%d vs %d)' % (k, r, a[i], b[i])
            return 'offset %d (%d vs %d)' % (i, a[i], b[i])
    return 'size %d vs %d' % (len(a), len(b))


inx = []
for d, _s, fs in os.walk(root):
    for f in fs:
        if f.lower().endswith('.inx'):
            inx.append(os.path.join(d, f))
ok = bad = 0
shown = 0
for p in sorted(inx):
    rel = os.path.relpath(p, root)
    b = open(p, 'rb').read()
    try:
        mi = cf.read_inx(b)
        text = cf.inx_to_ini(mi, rel)
        b2 = cf.compile_ini(text, rel, mi.layout.rec, folder=mi.folder or None, code=mi.code)
    except Exception as e:
        bad += 1
        print('ERROR', rel, e)
        continue
    if b2 == b:
        ok += 1
    else:
        bad += 1
        if shown < show:
            shown += 1
            print('round trip differs:', rel, first_diff(b, b2, mi.layout))
print('round trip: %d identical, %d differ, of %d' % (ok, bad, len(inx)))

ok = bad = 0
shown = 0
for p in sorted(inx):
    base = os.path.splitext(p)[0]
    for ext in ('.ini', '.in', '.inf'):
        cands = [os.path.join(os.path.dirname(p), f) for f in os.listdir(os.path.dirname(p))
                 if f.lower() == os.path.basename(base).lower() + ext]
        if cands:
            break
    if not cands:
        continue
    rel = os.path.relpath(p, root)
    b = open(p, 'rb').read()
    L = cf.LAYOUTS[len(b)]
    text = open(cands[0], 'rb').read().decode('cp949', 'replace')
    b2 = cf.compile_ini(text, rel, L.rec)
    if b2 == b:
        ok += 1
    else:
        bad += 1
        if shown < show:
            shown += 1
            print('compile differs:', os.path.relpath(cands[0], root), first_diff(b, b2, L))
print('shipped text -> .inx: %d identical, %d differ' % (ok, bad))
