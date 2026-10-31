"""Object layout of ASE files, the way the game's builder sorts them:
GEOM/HELP, with/without mesh, material, physique, animation.
    python ase_structure.py file.ase ...
"""
import collections
import os
import sys

sys.path.insert(0, r'X:\Projects\SMD-ANIM')
from smdanim.aseparse import parse_ase, find, find_all, val   # noqa: E402

for p in sys.argv[1:]:
    r = parse_ase(p)
    c = collections.Counter()
    for g in find_all(r, '*GEOMOBJECT') + find_all(r, '*HELPEROBJECT'):
        m = find(g, '*MESH')
        c[' '.join((g[0][1:5], 'mesh' if m and int(val(m, '*MESH_NUMVERTEX', '0')) > 0 else 'nomesh',
                    'mat' if find(g, '*MATERIAL_REF') is not None else 'nomat',
                    'phys' if find(g, '*PHYSIQUE') is not None else '-',
                    'anim' if find(g, '*TM_ANIMATION') is not None else '-'))] += 1
    print('%-40s %s' % (os.path.basename(os.path.dirname(p)) + '/' + os.path.basename(p), dict(sorted(c.items()))))
