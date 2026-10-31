"""Can MmbA34.smd + a class skeleton reproduce the original MmbA34.ASE bind pose?"""
import os, sys
import numpy as np
sys.path.insert(0, r'X:\Projects\SMD-ANIM')
from smdanim.smdfile import Model
from smdanim.convert import _model_world, _xform
from smdanim.aseparse import parse_ase, find, find_all, val, unquote

G = r'C:\Program Files (x86)\MasangSoft\PristonTale(Test)\char\tmABCD'
smd = Model(os.path.join(G, 'MmbA34.smd'))
root = parse_ase(os.path.join(G, 'MmbA34.ASE'))
orig_verts = []
orig_bones = {}
for g in find_all(root, '*GEOMOBJECT') + find_all(root, '*HELPEROBJECT'):
    name = unquote(val(g, '*NODE_NAME'))
    tm = find(g, '*NODE_TM')
    orig_bones[name] = [float(x) for k in ('*TM_ROW0', '*TM_ROW1', '*TM_ROW2', '*TM_ROW3') for x in val(tm, k).split()]
    if find(g, '*PHYSIQUE') is not None:
        m = find(g, '*MESH')
        orig_verts += [tuple(float(x) for x in c[1].split()[1:4]) for c in find(m, '*MESH_VERTEX_LIST')[2]]
O = np.array(orig_verts)


def nn_err(W):
    W = np.array(W)
    d = np.sqrt(((W[:, None, :] - O[None, :, :]) ** 2).sum(-1)).min(1) if len(W) * len(O) < 4e7 else None
    if d is None:
        out = []
        for i in range(0, len(W), 500):
            out.append(np.sqrt(((W[i:i + 500, None, :] - O[None, :, :]) ** 2).sum(-1)).min(1))
        d = np.concatenate(out)
    return d


for skel in ('m1.smb',):
    b = Model(os.path.join(G, skel))
    bones = {o.name: _model_world(o) for o in b.objects}
    # 1) does the skeleton's bind pose equal the bone objects saved in the original ASE?
    worst_bone = 0.0
    for name, (rows, t) in bones.items():
        if name in orig_bones:
            ob = orig_bones[name]
            mine = [v for r in rows for v in r] + list(t)
            worst_bone = max(worst_bone, max(abs(a - c) for a, c in zip(mine, ob)))
    print('%s: bones also in ASE: %d/%d, max TM difference %.4f' % (skel, sum(n in orig_bones for n in bones), len(bones), worst_bone))
    # 2) nearest-neighbour vertex error
    W = [_xform(lv, *bones[bn]) for o in smd.objects if o.physique for lv, bn in zip(o.local_verts, o.physique)]
    d = nn_err(W)
    print('   vertices %d (orig %d): nearest-neighbour error median %.4f  95%% %.4f  max %.4f'
          % (len(W), len(O), np.median(d), np.percentile(d, 95), d.max()))
    # 3) same, but using the bone TMs stored in the original ASE (the true bind pose)
    ab = {}
    for name, f in orig_bones.items():
        ab[name] = ([f[0:3], f[3:6], f[6:9]], f[9:12])
    W2 = [_xform(lv, *ab[bn]) for o in smd.objects if o.physique for lv, bn in zip(o.local_verts, o.physique) if bn in ab]
    d2 = nn_err(W2)
    print('   with the ASE\'s own bone TMs: median %.4f  max %.4f' % (np.median(d2), d2.max()))
