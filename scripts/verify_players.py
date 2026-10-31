"""Player bodies/heads vs the artists' original ASE files (old char folder).

For a sample of .smd files that have an original .ASE next to them, convert with the
class-skeleton rule and measure the nearest-neighbour distance of every skinned vertex
to the original mesh.  A wrong skeleton shows up as errors of several units.
"""
import os
import random
import sys
import tempfile

import numpy as np

sys.path.insert(0, r'X:\Projects\SMD-ANIM')
from smdanim.convert import Options, build_scene                   # noqa: E402
from smdanim.aseparse import parse_ase, find, find_all             # noqa: E402

G = sys.argv[2] if len(sys.argv) > 2 else r'X:\Projects\PT-World-Map\char\char\tmABCD'
pairs = []
for d, _s, files in os.walk(G):
    names = {n.lower(): n for n in files}
    pairs += [(os.path.join(d, n), os.path.join(d, names[n[:-4].lower() + '.ase']))
              for n in names.values() if n.lower().endswith('.smd') and n[:-4].lower() + '.ase' in names]
random.seed(3)
sample = random.sample(pairs, min(int(sys.argv[1]) if len(sys.argv) > 1 else 40, len(pairs)))
bad = 0
for smd, ase in sorted(sample):
    try:
        sc = build_scene(smd, Options(animation='none'))
    except Exception as e:
        print('%-16s FAILED %s' % (os.path.basename(smd), e))
        bad += 1
        continue
    mine = np.array([v for o in sc.objects if getattr(o, 'physique', None) for v in o.verts])
    root = parse_ase(ase)
    orig = []
    for g in find_all(root, '*GEOMOBJECT'):
        if find(g, '*PHYSIQUE') is not None:
            orig += [[float(x) for x in c[1].split()[1:4]] for c in find(find(g, '*MESH'), '*MESH_VERTEX_LIST')[2]]
    orig = np.array(orig)
    if not len(mine) or not len(orig):
        print('%-16s no skinned mesh (mine %d, original %d)' % (os.path.basename(smd), len(mine), len(orig)))
        continue
    d = np.concatenate([np.sqrt(((mine[i:i + 300, None] - orig[None]) ** 2).sum(-1)).min(1) for i in range(0, len(mine), 300)])
    flag = '' if np.median(d) < 0.05 else '   <-- CHECK'
    bad += bool(flag)
    print('%-16s %-8s %-40s median %.4f max %.4f%s' % (os.path.basename(smd), sc.skeleton_file, sc.rig.how[:40],
                                                     np.median(d), d.max(), flag))
print('checked %d, suspicious %d' % (len(sample), bad))
