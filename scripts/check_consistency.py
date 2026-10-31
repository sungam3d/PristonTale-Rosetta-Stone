"""Within a piece, is cached[j] == cached[j-1] * raw[j]?  Where are the exceptions?"""
import sys
import numpy as np
sys.path.insert(0, r'X:\Projects\SMD-ANIM')
from smdanim.smdfile import Model
from smdanim.convert import _quat_from_matrix, _qmul_xyzw

path = sys.argv[1]
m = Model(path)
total = bad = 0
where = {}
for o in m.objects:
    if not o.rot_keys:
        continue
    P = [_quat_from_matrix([[f[0], f[1], f[2]], [f[4], f[5], f[6]], [f[8], f[9], f[10]]]) for f in o.prev_rot]
    for s, e, idx, n in o.frames[0] or [(0, 1 << 30, 0, len(o.rot_keys))]:
        for j in range(idx + 1, idx + n):
            raw = o.rot_keys[j][1:5]
            exp = _qmul_xyzw(P[j - 1], raw)
            d = abs(sum(a * b for a, b in zip(exp, P[j])))
            nn = np.sqrt(sum(a * a for a in exp))
            total += 1
            if d / nn < 0.99999:
                bad += 1
                pos = 'last' if j == idx + n - 1 else ('first+1' if j == idx + 1 else 'middle')
                at_end = o.rot_keys[j][0] >= e
                where[(pos, at_end)] = where.get((pos, at_end), 0) + 1
print('%s: within-piece key pairs %d, inconsistent %d' % (path.replace('/', '\\').split('\\')[-1], total, bad), where)
