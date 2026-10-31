"""ASE material list vs stage materials, and which stage materials each object uses.

  python scripts/probe_stage_mats.py <original.ASE> <stage.smd>
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from smdanim.aseparse import parse_ase, find, find_all, val, unquote   # noqa: E402
from smdanim.smdfile import Stage                                       # noqa: E402

r = parse_ase(sys.argv[1])
st = Stage(sys.argv[2])
mats = find_all(find(r, '*MATERIAL_LIST'), '*MATERIAL')
tot = 0
for i, m in enumerate(mats):
    ns = int(val(m, '*NUMSUBMTLS', '0'))
    print(i, unquote(val(m, '*MATERIAL_NAME', '')), 'subs', ns, 'first stage index', tot)
    tot += max(ns, 1)
print('ase mats', len(mats), 'flattened', tot, 'stage mats', len(st.materials))
f0 = 0
for g in find_all(r, '*GEOMOBJECT'):
    m = find(g, '*MESH')
    nf = int(val(m, '*MESH_NUMFACES', 0))
    used = sorted(set(f[3] for f in st.faces[f0:f0 + nf]))
    f0 += nf
    print('%-16s ref %-4s stage mats %s' % (unquote(val(g, '*NODE_NAME', ''))[:16], val(g, '*MATERIAL_REF'), used[:14]))
