"""Compare two character/monster ASE files: bones, skin and poses over the timeline.

    python roundtrip_check.py <original.ase> <exported.ase> [--anim FILE] [--ticks N]
"""
import sys

import numpy as np

sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.abspath(__file__)))
from ase_pose import Rig      # noqa: E402

args = sys.argv[1:]
anim = None
if '--anim' in args:
    i = args.index('--anim')
    anim = args[i + 1]
    del args[i:i + 2]
nn = '--nn' in args
if nn:
    args.remove('--nn')
nt = 12
if '--ticks' in args:
    i = args.index('--ticks')
    nt = int(args[i + 1])
    del args[i:i + 2]
a, b = Rig(args[0], anim), Rig(args[1], anim)          # --anim: the shared motions file, for both
print('bones: original %d, exported %d, common %d' % (len(a.bones), len(b.bones), len(set(a.bones) & set(b.bones))))
dt = max((np.abs(a.bones[n].R - b.bones[n].R).max() + np.abs(a.bones[n].t - b.bones[n].t).max())
         for n in set(a.bones) & set(b.bones))
print('bone rest transforms: max difference %.6f' % dt)
print('skinned vertices: original %d, exported %d; same bone %d / %d' % (
    len(a.verts), len(b.verts), sum(x == y for x, y in zip(a.vbone, b.vbone)), min(len(a.vbone), len(b.vbone))))
last = max([k[0] for r in (a, b) for bo in r.bones.values() for k in bo.pos + bo.rot] or [0])
ticks = sorted(set([0, last] + [int(last * (i + 0.37) / nt) for i in range(nt)]))
worst = 0.0
for t in ticks:
    pa, pb = a.pose(t), b.pose(t)
    if nn:                                   # different vertex order: nearest neighbour
        d = np.concatenate([np.sqrt(((pa[i:i + 400, None] - pb[None]) ** 2).sum(-1)).min(1) for i in range(0, len(pa), 400)])
    else:
        n = min(len(pa), len(pb))
        d = np.sqrt(((pa[:n] - pb[:n]) ** 2).sum(1))
    worst = max(worst, d.max())
    print('  tick %8d (frame %6.1f): vertex difference median %.5f  max %.5f' % (t, t / 160.0, np.median(d), d.max()))
print('WORST %.5f' % worst)
