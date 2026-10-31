"""Converter track (ASE semantics) vs the game rule, for one bone, at given ticks."""
import math, sys
import numpy as np
sys.path.insert(0, r'X:\Projects\SMD-ANIM')
from smdanim.smdfile import Model
from smdanim.convert import _anim_keys

path, bone = sys.argv[1], sys.argv[2]
ticks = [float(t) for t in sys.argv[3:]]
o = next(x for x in Model(path).objects if x.name == bone)
pos, rot, scl = _anim_keys(o)

def std(axis, ang):          # standard rotation matrix, angle about axis
    x, y, z = axis; c, s = math.cos(ang), math.sin(ang); C = 1 - c
    return np.array([[c + x*x*C, x*y*C - z*s, x*z*C + y*s], [y*x*C + z*s, c + y*y*C, y*z*C - x*s], [z*x*C - y*s, z*y*C + x*s, c + z*z*C]])

# ASE: orientation_i = orientation_{i-1} turned by key i;  rows_i = rows_{i-1} @ qmat(q_i).T = rows_{i-1} @ Std(q_i)
acc = []
R = np.eye(3)
for t, axis, ang in rot:
    R = R @ std(axis, ang)
    acc.append((t, R))
def ase_at(tick):
    i = max([k for k, (t, _r) in enumerate(acc) if t <= tick] or [0])
    if i + 1 < len(acc) and acc[i][0] <= tick < acc[i + 1][0]:
        f = (tick - acc[i][0]) / (acc[i + 1][0] - acc[i][0])
        return acc[i][1] @ std(rot[i + 1][1], rot[i + 1][2] * f)
    return acc[i][1]
for tick in ticks:
    lo = hi = None
    for s, e, idx, n in o.frames[0]:
        if e > s and s <= tick < e:
            lo, hi = idx, idx + n
    keys = [(o.rot_keys[k][0], np.array(o.prev_rot[k]).reshape(4, 4)[:3, :3], k) for k in range(lo, hi)]
    i = max([k for k, kk in enumerate(keys) if kk[0] <= tick] or [0])
    G = keys[i][1]
    if i + 1 < len(keys) and keys[i][0] <= tick < keys[i + 1][0]:
        x, y, z, w = o.rot_keys[keys[i + 1][2]][1:5]
        if w < 0:
            x, y, z, w = -x, -y, -z, -w
        s = math.sqrt(x * x + y * y + z * z)
        if s > 1e-12:
            ang = 2 * math.atan2(s, w)
            f = (tick - keys[i][0]) / (keys[i + 1][0] - keys[i][0])
            G = G @ std((x / s, y / s, z / s), ang * f)
    print('   next key at', keys[i + 1][0] if i + 1 < len(keys) else None)
    print('tick %d piece keys %d..%d, game key %d (t=%d)  |ASE - game| = %.4f'
          % (tick, lo, hi, keys[i][2], keys[i][0], np.abs(ase_at(tick) - G).max()))
    near = [(t, round(a, 4)) for t, ax, a in rot if abs(t - tick) <= 480]
    print('   ASE keys near:', near[:8])
    print('   smb keys near:', [(t, ) for t, *_ in o.rot_keys[lo:hi] if abs(t - tick) <= 480][:8])
