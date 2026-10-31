"""Compare a converted character ASE with the artist's original ASE.

    python verify_char.py converted.ase original.ASE
Bone transforms are compared by name; skinned vertices by nearest neighbour
(the original has extra vertices where 3ds Max split UV seams)."""
import sys
import numpy as np
sys.path.insert(0, r'X:\Projects\SMD-ANIM')
from smdanim.aseparse import parse_ase, find, find_all, val, unquote


def load(path):
    root = parse_ase(path)
    tms, verts, phys = {}, [], {}
    for g in find_all(root, '*GEOMOBJECT') + find_all(root, '*HELPEROBJECT'):
        name = unquote(val(g, '*NODE_NAME'))
        tm = find(g, '*NODE_TM')
        tms[name] = np.array([float(x) for k in ('*TM_ROW0', '*TM_ROW1', '*TM_ROW2', '*TM_ROW3')
                              for x in val(tm, k).split()])
        ph = find(g, '*PHYSIQUE')
        if ph is not None:
            vl = find(find(g, '*MESH'), '*MESH_VERTEX_LIST')[2]
            vs = [tuple(float(x) for x in c[1].split()[1:4]) for c in vl]
            names = [c[1].split(None, 1)[1].strip().strip('"') for c in ph[2]
                     if c[0] == '*PHYSIQUE_VERTEXASSIGNMENT_NONBLENDED_RIGIDTYPE']
            verts += vs
            for v, n in zip(vs, names):
                phys[v] = n
    return tms, np.array(verts), phys


mine, orig = sys.argv[1], sys.argv[2]
t1, v1, p1 = load(mine)
t2, v2, p2 = load(orig)
common = sorted(set(t1) & set(t2))
err = max((np.abs(t1[n] - t2[n]).max() for n in common), default=0)
print('bones/objects: mine %d, original %d, common %d, max TM difference %.4f' % (len(t1), len(t2), len(common), err))
print('missing from mine:', sorted(set(t2) - set(t1))[:10])
d = []
same_bone = 0
keys2 = list(p2.keys())
for i in range(0, len(v1), 400):
    blk = v1[i:i + 400]
    dist = np.sqrt(((blk[:, None, :] - v2[None, :, :]) ** 2).sum(-1))
    j = dist.argmin(1)
    d.append(dist.min(1))
    for a, b in zip(blk, j):
        same_bone += p1.get(tuple(a)) == p2.get(tuple(v2[b]))
d = np.concatenate(d)
print('skinned vertices: mine %d, original %d; nearest-neighbour error median %.4f, max %.4f'
      % (len(v1), len(v2), np.median(d), d.max()))
print('vertices assigned to the same bone as their original twin: %d / %d' % (same_bone, len(v1)))
