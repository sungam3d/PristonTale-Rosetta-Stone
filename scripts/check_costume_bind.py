"""Is the game's <name>.smd built from this artist ASE?

Re-seat every artist vertex from its own bone (artist bind TM) onto the game's class
skeleton bind TM and compare with the game's converted bind-pose mesh.
    python check_costume_bind.py <artist.ASE> <game.smd>
"""
import sys

import numpy as np

sys.path.insert(0, r'X:\Projects\SMD-ANIM')
from smdanim.aseparse import parse_ase, find, find_all, val, unquote   # noqa: E402
from smdanim.convert import Options, build_scene                        # noqa: E402

ase, smd = sys.argv[1:3]
sc = build_scene(smd, Options(animation='none'))
game = np.array([v for o in sc.objects if getattr(o, 'physique', None) for v in o.verts])
gbones = {o.name: (np.array(o.rows), np.array(o.pos)) for o in sc.objects if o.kind == 'bone'}

root = parse_ase(ase)
abones = {}
for g in find_all(root, '*GEOMOBJECT') + find_all(root, '*HELPEROBJECT'):
    tm = find(g, '*NODE_TM')
    f = [float(x) for k in ('*TM_ROW0', '*TM_ROW1', '*TM_ROW2', '*TM_ROW3') for x in val(tm, k).split()]
    abones[unquote(val(g, '*NODE_NAME'))] = (np.array(f[:9]).reshape(3, 3), np.array(f[9:12]))
reseated, raw, skipped = [], [], 0
for g in find_all(root, '*GEOMOBJECT'):
    ph = find(g, '*PHYSIQUE')
    if ph is None:
        continue
    verts = [np.array([float(x) for x in c[1].split()[1:4]]) for c in find(find(g, '*MESH'), '*MESH_VERTEX_LIST')[2]]
    for c in ph[2]:
        if not c[0].startswith('*PHYSIQUE_VERTEXASSIGNMENT'):
            continue
        i, bn = c[1].split(None, 1)
        bn = bn.strip().strip('"')
        v = verts[int(i)]
        raw.append(v)
        if bn in gbones and bn in abones:
            R, t = abones[bn]
            local = (v - t) @ np.linalg.inv(R)                     # row vectors: world = local @ R + t
            GR, Gt = gbones[bn]
            reseated.append(local @ GR + Gt)
        else:
            skipped += 1


def nn(a, b):
    return np.concatenate([np.sqrt(((a[i:i + 400, None] - b[None]) ** 2).sum(-1)).min(1) for i in range(0, len(a), 400)])


d0 = nn(game, np.array(raw))
d1 = nn(game, np.array(reseated))
print('game %d verts, artist %d (%d on bones the game skeleton lacks)' % (len(game), len(raw), skipped))
print('artist mesh as is      : NN median %.4f max %.4f' % (np.median(d0), d0.max()))
print('artist re-seated on m8 : NN median %.4f max %.4f' % (np.median(d1), d1.max()))
