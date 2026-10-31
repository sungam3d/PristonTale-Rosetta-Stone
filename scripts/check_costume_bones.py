"""Which bone does each vertex follow: artist ASE vs the game's .smd?
    python check_costume_bones.py <artist.ASE> <game.smd>
"""
import collections
import sys

import numpy as np

sys.path.insert(0, r'X:\Projects\SMD-ANIM')
from smdanim.aseparse import parse_ase, find, find_all                 # noqa: E402
from smdanim.convert import Options, build_scene                        # noqa: E402

ase, smd = sys.argv[1:3]
sc = build_scene(smd, Options(animation='none'))
gv, gb = [], []
for o in sc.objects:
    if getattr(o, 'physique', None):
        gv += o.verts
        gb += o.physique
gv = np.array(gv)
av, ab = [], []
for g in find_all(parse_ase(ase), '*GEOMOBJECT'):
    ph = find(g, '*PHYSIQUE')
    if ph is None:
        continue
    verts = [[float(x) for x in c[1].split()[1:4]] for c in find(find(g, '*MESH'), '*MESH_VERTEX_LIST')[2]]
    names = {}
    for c in ph[2]:
        if c[0].startswith('*PHYSIQUE_VERTEXASSIGNMENT'):
            i, bn = c[1].split(None, 1)
            names[int(i)] = bn.strip().strip('"')
    for i, v in enumerate(verts):
        av.append(v)
        ab.append(names.get(i, '?'))
av = np.array(av)
d = np.sqrt(((gv[:, None] - av[None]) ** 2).sum(-1))
j = d.argmin(1)
diff = collections.Counter((gb[i], ab[j[i]]) for i in range(len(gv)) if gb[i] != ab[j[i]])
print('vertices %d, on a different bone: %d' % (len(gv), sum(diff.values())))
for (g, a), n in diff.most_common(12):
    print('  %3d  game: %-22s artist: %s' % (n, g, a))
