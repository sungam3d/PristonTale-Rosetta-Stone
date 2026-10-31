"""A split map must hold exactly the faces of the one-mesh conversion (positions, UVs, colours, material).

  python scripts/check_split_same.py <map.smd> ...
"""
import os
import sys
import tempfile
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from smdanim.aseparse import parse_ase, find, find_all, val, unquote   # noqa: E402
from smdanim.convert import Options, convert_file                      # noqa: E402


def faces(path):
    out = Counter()
    names = []
    for g in find_all(parse_ase(path), '*GEOMOBJECT'):
        names.append(unquote(val(g, '*NODE_NAME', '')))
        m = find(g, '*MESH')
        V = [c[1].split()[1:4] for c in find(m, '*MESH_VERTEX_LIST')[2] or []]
        F = []
        for c in find(m, '*MESH_FACE_LIST')[2] or []:
            t = c[1].replace(':', ' : ').split()
            F.append((int(t[t.index('A') + 2]), int(t[t.index('B') + 2]), int(t[t.index('C') + 2]),
                      t[t.index('*MESH_MTLID') + 1]))
        tl, tf = find(m, '*MESH_TVERTLIST'), find(m, '*MESH_TFACELIST')
        TV = [c[1].split()[1:3] for c in (tl[2] or [])] if tl else []
        TF = [c[1].split()[1:4] for c in (tf[2] or [])] if tf else []
        cl, cf = find(m, '*MESH_CVERTLIST'), find(m, '*MESH_CFACELIST')
        CV = [c[1].split()[1:4] for c in (cl[2] or [])] if cl else []
        CF = [c[1].split()[1:4] for c in (cf[2] or [])] if cf else []
        for i, (a, b, c, mid) in enumerate(F):
            key = (tuple(tuple(V[x]) for x in (a, b, c)), mid,
                   tuple(tuple(TV[int(x)]) for x in TF[i]) if TF else (),
                   tuple(tuple(CV[int(x)]) for x in CF[i]) if CF else ())
            out[key] += 1
    return out, names


bad = 0
tmp = tempfile.mkdtemp()
for f in sys.argv[1:]:
    a, b = os.path.join(tmp, 'one.ase'), os.path.join(tmp, 'split.ase')
    convert_file(f, a, Options(split_objects=False))
    convert_file(f, b, Options())
    fa, na = faces(a)
    fb, nb = faces(b)
    ok = fa == fb and len(set(nb)) == len(nb)
    bad += not ok
    print('%-24s %s  faces %d  objects %d -> %d' % (os.path.basename(f), 'same' if ok else 'DIFFERENT',
                                                    sum(fa.values()), len(na), len(nb)))
print('FAILED' if bad else 'all same')
