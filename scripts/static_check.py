"""Static round trip check (maps, weapons, items): per object, world vertex positions, face
count and UV count must match.   python static_check.py original.ase exported.ase"""
import sys

import numpy as np

sys.path.insert(0, r'X:\Projects\SMD-ANIM')
from smdanim.aseparse import parse_ase, find, find_all, val, unquote   # noqa: E402


def load(p):
    out = {}
    for g in find_all(parse_ase(p), '*GEOMOBJECT'):
        m = find(g, '*MESH')
        if m is None or find(g, '*MATERIAL_REF') is None:
            continue
        vl = find(m, '*MESH_VERTEX_LIST')
        v = np.array([[float(x) for x in c[1].split()[1:4]] for c in (vl[2] or [])]) if vl else np.zeros((0, 3))
        out[unquote(val(g, '*NODE_NAME'))] = (v, int(val(m, '*MESH_NUMFACES', '0')), int(val(m, '*MESH_NUMTVERTEX', '0')))
    return out


a, b = load(sys.argv[1]), load(sys.argv[2])
worst = 0.0
for n, (va, fa, ta) in a.items():
    if n not in b:
        print('  missing object', n)
        continue
    vb, fb, tb = b[n]
    if va.shape == vb.shape and len(va):
        d = np.abs(va - vb).max()
    elif len(va) and len(vb):          # extra vertex copies (doubled faces): every original vertex must still exist
        d = max(np.sqrt(((va[i:i + 500, None] - vb[None]) ** 2).sum(-1)).min(1).max() for i in range(0, len(va), 500))
    else:
        d = float('nan')
    worst = max(worst, d if d == d else 9e9)
    print('  %-24s verts %6d/%-6d faces %6d/%-6d uvs %6d/%-6d max vertex diff %.6f' % (n, len(va), len(vb), fa, fb, ta, tb, d))
print('WORST %.6f' % worst)
