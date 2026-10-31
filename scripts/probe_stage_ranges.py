"""For a stage .smd whose faces are in the original ASE order (e.g. village-1):
are each object's vertices a separate, contiguous index range in the .smd?

  python scripts/probe_stage_ranges.py <original.ASE> <stage.smd>
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from smdanim.aseparse import parse_ase, find, find_all, val, unquote   # noqa: E402
from smdanim.smdfile import Stage                                       # noqa: E402

root = parse_ase(sys.argv[1])
st = Stage(sys.argv[2])
objs = []
for g in find_all(root, '*GEOMOBJECT'):
    m = find(g, '*MESH')
    if m is not None:
        objs.append((unquote(val(g, '*NODE_NAME', '')), int(val(m, '*MESH_NUMVERTEX', 0)),
                     int(val(m, '*MESH_NUMFACES', 0))))
f0 = 0
owner = {}
shared = contiguous = 0
prev_hi = -1
order_ok = 0
for i, (name, nv, nf) in enumerate(objs):
    vs = set()
    for a, b, c, m in st.faces[f0:f0 + nf]:
        vs.update((a, b, c))
    f0 += nf
    if not vs:
        continue
    lo, hi = min(vs), max(vs)
    if hi - lo + 1 == len(vs):
        contiguous += 1
    if lo > prev_hi:
        order_ok += 1
    prev_hi = max(prev_hi, hi)
    sh = sum(1 for v in vs if v in owner)
    if sh:
        shared += 1
        if shared < 6:
            print('shares', sh, 'verts:', name, 'with', set(owner[v] for v in vs if v in owner))
    for v in vs:
        owner.setdefault(v, name)
    if i < 12:
        print('%-20s ase v%-5d f%-5d | smd v%-5d range %d..%d' % (name, nv, nf, len(vs), lo, hi))
print('objects', len(objs), 'contiguous', contiguous, 'in order', order_ok, 'sharing vertices', shared,
      'faces used', f0, '/', st.n_face, 'verts', len(owner), '/', st.n_vertex)
