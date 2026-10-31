"""The game's own pose math (reference for importer tests).

posed_vertices(smd, smb, frame) -> numpy array of skinned vertex world positions, computed
the way Priston Tale does it: keys of the playing motion piece only, cached rotation at the
previous key turned by the given fraction of the next key's delta, linear positions, static
transform for pieces without keys; vertex = bone-local vertex x bone world matrix.
"""
import math
import sys

import numpy as np

sys.path.insert(0, r'X:\Projects\SMD-ANIM')
from smdanim.smdfile import Model          # noqa: E402


def qmat_rows(x, y, z, w):
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y + z * w), 2 * (x * z - y * w)],
                     [2 * (x * y - z * w), 1 - 2 * (x * x + z * z), 2 * (y * z + x * w)],
                     [2 * (x * z + y * w), 2 * (y * z - x * w), 1 - 2 * (x * x + y * y)]])


def piece_range(o, which, tick):
    for s, e, idx, n in (o.frames[which] if o.frames and o.frames[which] else []):
        if e > s and s <= tick < e:
            return idx, idx + n
    return 0, len([o.rot_keys, o.pos_keys, o.scale_keys][which])


def bone_local(o, tick):
    lo, hi = piece_range(o, 0, tick)
    if hi > lo:
        acc = [(o.rot_keys[k][0], np.array(o.prev_rot[k], dtype=float).reshape(4, 4)[:3, :3]) for k in range(lo, hi)]
        i = max([k for k, (t, _q) in enumerate(acc) if t <= tick] or [0])
        R = acc[i][1]
        if i + 1 < len(acc) and acc[i][0] <= tick < acc[i + 1][0]:
            f = (tick - acc[i][0]) / float(acc[i + 1][0] - acc[i][0])
            _t, x, y, z, w = o.rot_keys[lo + i + 1]
            if w < 0.0:
                x, y, z, w = -x, -y, -z, -w
            s = math.sqrt(x * x + y * y + z * z)
            if s > 1e-12:
                h = math.atan2(s, w) * f
                k = math.sin(h) / s
                R = R @ qmat_rows(x * k, y * k, z * k, math.cos(h)).T
    else:
        R = qmat_rows(*o.quat).T

    def interp(which, keys, default):
        lo, hi = piece_range(o, which, tick)
        keys = keys[lo:hi]
        if not keys:
            return np.array(default, dtype=float)
        i = max([k for k, kk in enumerate(keys) if kk[0] <= tick] or [0])
        a = np.array(keys[i][1:4], dtype=float)
        if i + 1 < len(keys) and keys[i][0] <= tick:
            b = np.array(keys[i + 1][1:4], dtype=float)
            return a + (b - a) * (tick - keys[i][0]) / float(keys[i + 1][0] - keys[i][0])
        return a
    return np.diag(interp(2, o.scale_keys, o.scale)) @ R, interp(1, o.pos_keys, o.pos)


def posed_vertices(smd, smb, frame):
    skel, mesh = Model(smb), Model(smd)
    tick = frame * 160.0
    world = {}
    for b in skel.objects:
        R, p = bone_local(b, tick)
        if b.parent in world:
            PR, Pp = world[b.parent]
            R, p = R @ PR, p @ PR + Pp
        world[b.name] = (R, p)
    out = []
    for o in mesh.objects:
        if o.physique:
            for lv, bn in zip(o.local_verts, o.physique):
                if bn in world:
                    R, p = world[bn]
                    out.append(np.array(lv) @ R + p)
                else:
                    out.append(np.array([np.nan] * 3))
    return np.array(out)
